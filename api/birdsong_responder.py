''' birdsong_responder.py
    REST API for the birdsong database
'''

from datetime import date, datetime, timedelta
import inspect
import json
import os
import platform
import re
import sys
from time import time
from flask import (Flask, g, make_response, redirect, render_template, request,
                   send_file, jsonify)
from flask.json import JSONEncoder
from flask_cors import CORS
from flask_swagger import swagger
import jwt
from oauthlib.oauth2 import WebApplicationClient
import pymysql.cursors
import pymysql.err
import requests

import birdsong_utilities
from birdsong_utilities import (InvalidUsage, call_responder, check_permission,
                                generate_sql, get_banding, get_banding_and_location,
                                get_user_by_name, random_string, sql_error, validate_user)

# SQL statements
READ = {
    'CVREL': "SELECT subject,relationship,object FROM cv_relationship_vw "
             + "WHERE subject_id=%s OR object_id=%s",
    'CVTERMREL': "SELECT subject,relationship,object FROM "
                 + "cv_term_relationship_vw WHERE subject_id=%s OR "
                 + "object_id=%s",
    'BSUMMARY': "SELECT * FROM bird_vw ORDER BY name DESC",
    'CSUMMARY': "SELECT * FROM clutch_vw ORDER BY name DESC",
    'LSUMMARY': "SELECT c.name,display_name,definition,COUNT(b.id) AS cnt FROM cv_term c "
                + "LEFT OUTER JOIN bird b ON (b.location_id=c.id) "
                + "WHERE cv_id=getCvId('location','') group by 1,2,3",
    'NSUMMARY': "SELECT * FROM nest_vw ORDER BY name DESC",
}
WRITE = {
    'INSERT_CV': "INSERT INTO cv (name,definition,display_name,version,"
                 + "is_current) VALUES (%s,%s,%s,%s,%s)",
    'INSERT_CVTERM': "INSERT INTO cv_term (cv_id,name,definition,display_name"
                     + ",is_current,data_type) VALUES (getCvId(%s,''),%s,%s,"
                     + "%s,%s,%s)",
    'INSERT_USER': "INSERT INTO user (name,first,last,janelia_id,email,organization) "
                   + "VALUES (%s,%s,%s,%s,%s,%s)",
}


# pylint: disable=C0302,C0103,W0703

class CustomJSONEncoder(JSONEncoder):
    ''' Define a custom JSON encoder
    '''
    def default(self, obj):   # pylint: disable=E0202, W0221
        try:
            if isinstance(obj, datetime):
                return obj.strftime("%a, %-d %b %Y %H:%M:%S")
            if isinstance(obj, timedelta):
                seconds = obj.total_seconds()
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                seconds = seconds % 60
                return f"{hours:02d}:{minutes:02d}:{seconds:.02f}"
            iterable = iter(obj)
        except TypeError:
            pass
        else:
            return list(iterable)
        return JSONEncoder.default(self, obj)

__version__ = "0.0.1"
app = Flask(__name__, template_folder="templates")
app.json_encoder = CustomJSONEncoder
app.config.from_pyfile("config.cfg")
# Override Flask's usual behavior of sorting keys (interferes with prioritization)
app.config["JSON_SORT_KEYS"] = False
CORS(app, supports_credentials=True)
try:
    CONN = pymysql.connect(host=app.config["MYSQL_DATABASE_HOST"],
                           user=app.config["MYSQL_DATABASE_USER"],
                           password=app.config["MYSQL_DATABASE_PASSWORD"],
                           db=app.config["MYSQL_DATABASE_DB"],
                           cursorclass=pymysql.cursors.DictCursor)
    CURSOR = CONN.cursor()
except Exception as erro:
    ttemplate = "An exception of type {0} occurred. Arguments:\n{1!r}"
    tmessage = ttemplate.format(type(erro).__name__, erro.args)
    print(tmessage)
    sys.exit(-1)
# OAuth2 client setup
CLIENT = WebApplicationClient(app.config["GOOGLE_CLIENT_ID"])
app.config["STARTTIME"] = time()
app.config["STARTDT"] = datetime.now()
app.config["LAST_TRANSACTION"] = time()
IDCOLUMN = 0
START_TIME = ''


# *****************************************************************************
# * Flask                                                                     *
# *****************************************************************************

@app.before_request
def before_request():
    ''' Set transaction start time and increment counters.
        If needed, initilize global variables.
    '''
    # pylint: disable=W0603
    global START_TIME
    g.db = CONN
    g.c = CURSOR
    START_TIME = time()
    app.config["COUNTER"] += 1
    endpoint = request.endpoint if request.endpoint else "(Unknown)"
    app.config["ENDPOINTS"][endpoint] = app.config["ENDPOINTS"].get(endpoint, 0) + 1
    if request.method == "OPTIONS":
        result = initialize_result()
        return generate_response(result)
    return None


# ******************************************************************************
# * Utility functions                                                          *
# ******************************************************************************


def decode_token(token):
    ''' Decode a given JWT token
        Keyword arguments:
          token: JWT token
        Returns:
          decoded token JSON
    '''
    try:
        response = jwt.decode(token, verify=False)
    except jwt.ExpiredSignatureError:
        raise InvalidUsage("Token is expired", 401) from jwt.ExpiredSignatureError
    except jwt.InvalidSignatureError:
        raise InvalidUsage("Signature verification failed for token", 401) \
              from jwt.InvalidSignatureError
    except Exception as err:
        raise InvalidUsage("Could not decode token", 500) from err
    return response


def initialize_result():
    ''' Initialize the result dictionary
        An auth header with a JWT token is required for all POST and DELETE requests
        Returns:
          decoded partially populated result dictionary
    '''
    result = {"rest": {"requester": request.remote_addr,
                       "url": request.url,
                       "endpoint": request.endpoint,
                       "error": False,
                       "elapsed_time": "",
                       "row_count": 0,
                       "pid": os.getpid()}}
    if "Authorization" in request.headers:
        token = re.sub(r'Bearer\s+', "", request.headers["Authorization"])
        dtok = {}
        birdsong_utilities.BEARER = token
        if token in app.config["AUTHORIZED"]:
            authuser = app.config["AUTHORIZED"][token]
        else:
            dtok = decode_token(token)
            if not dtok or "email" not in dtok:
                raise InvalidUsage("Invalid token used for authorization", 401)
            authuser = dtok["email"]
            if not get_user_id(authuser):
                raise InvalidUsage(f"User {authuser} is not known to the Birdsong system")
            app.config["AUTHORIZED"][token] = authuser
        result["rest"]["user"] = authuser
        app.config["USERS"][authuser] = app.config["USERS"].get(authuser, 0) + 1
    elif request.method in ["DELETE", "POST"] or request.endpoint in app.config["REQUIRE_AUTH"]:
        raise InvalidUsage('You must authorize to use this endpoint', 401)
    if app.config["LAST_TRANSACTION"] and time() - app.config["LAST_TRANSACTION"] \
       >= app.config["RECONNECT_SECONDS"]:
        print("Seconds since last transaction: %d" % (time() - app.config["LAST_TRANSACTION"]))
        g.db.ping()
    app.config["LAST_TRANSACTION"] = time()
    return result


def execute_sql(result, sql, container, query=False):
    ''' Build and execute a SQL statement.
        Keyword arguments:
          result: result dictionary
          sql: base SQL statement
          container: name of dictionary in result disctionary to return rows
          query: uses "id" column if true
        Returns:
          True if successful
    '''
    # pylint: disable=W0603
    global IDCOLUMN
    sql, bind, IDCOLUMN = generate_sql(request, result, sql, query)
    if app.config["DEBUG"]: # pragma: no cover
        if bind:
            print(sql % bind)
        else:
            print(sql)
    try:
        if bind:
            g.c.execute(sql, bind)
        else:
            g.c.execute(sql)
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    result[container] = []
    if rows:
        result[container] = rows
        result["rest"]["row_count"] = len(rows)
        result["rest"]["sql_statement"] = g.c.mogrify(sql, bind)
        return True
    raise InvalidUsage(f"No rows returned for query {sql}", 404)


def show_columns(result, table):
    ''' Return the columns in a given table/view
        Keyword arguments:
          result: result dictionary
          table: MySQL table
        Returns:
          True if successful
    '''
    result["columns"] = []
    try:
        g.c.execute("SHOW COLUMNS FROM " + table)
        rows = g.c.fetchall()
        if rows:
            result["columns"] = rows
            result['rest']['row_count'] = len(rows)
        return True
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err


def get_additional_cv_data(sid):
    ''' Return CV relationships
        Keyword arguments:
          sid: CV ID
        Returns:
          fetched CV relationship data
    '''
    sid = str(sid)
    g.c.execute(READ["CVREL"], (sid, sid))
    cvrel = g.c.fetchall()
    return cvrel


def get_cv_data(result, cvs):
    ''' Get data for a CV
        Keyword arguments:
          result: result dictionary
          cvs: rows of data from cv table
        Returns:
          CV data list
    '''
    result["data"] = []
    try:
        for col in cvs:
            tcv = col
            if ("id" in col) and (not IDCOLUMN):
                cvrel = get_additional_cv_data(col["id"])
                tcv["relationships"] = list(cvrel)
            result['data'].append(tcv)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err


def get_additional_cv_term_data(sid):
    ''' Return CV term relationships
        Keyword arguments:
          sid: CV term ID
        Returns:
          fgetched CV term relationship data
    '''
    sid = str(sid)
    g.c.execute(READ["CVTERMREL"], (sid, sid))
    cvrel = g.c.fetchall()
    return cvrel


def get_cv_term_data(result, cvterms):
    ''' Get data for a CV term
        Keyword arguments:
          result: result dictionary
          cvterms: rows of data from cv table
        Returns:
          CV term data list
    '''
    result["data"] = []
    try:
        for col in cvterms:
            cvterm = col
            if ("id" in col) and (not IDCOLUMN):
                cvtermrel = get_additional_cv_term_data(col["id"])
                cvterm["relationships"] = list(cvtermrel)
            result["data"].append(cvterm)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err


def generate_response(result):
    ''' Generate a response to a request
        Keyword arguments:
          result: result dictionary
        Returns:
          JSON response
    '''
    result["rest"]["elapsed_time"] = str(timedelta(seconds=(time() - START_TIME)))
    return jsonify(**result)


def receive_payload(result):
    ''' Get a request payload (form or JSON).
        Keyword arguments:
          result: result dictionary
        Returns:
          payload dictionary
    '''
    pay = {}
    if not request.get_data():
        return pay
    try:
        if request.form:
            result["rest"]["form"] = request.form
            for itm in request.form:
                pay[itm] = request.form[itm]
        elif request.json:
            result["rest"]["json"] = request.json
            pay = request.json
    except Exception as err:
        temp = "{2}: An exception of type {0} occurred. Arguments:\n{1!r}"
        mess = temp.format(type(err).__name__, err.args, inspect.stack()[0][3])
        raise InvalidUsage(mess, 500) from err
    return pay


def check_missing_parms(ipd, required):
    ''' Check for missing parameters
        Keyword arguments:
          ipd: request payload
          required: list of required parameters
    '''
    missing = ""
    for prm in required:
        if prm not in ipd:
            missing = missing + prm + " "
    if missing:
        raise InvalidUsage("Missing arguments: " + missing)


def valid_cv_term(cv, cv_term):
    ''' Determine if a CV term is valid for a given CV
        Keyword arguments:
          cv: CV
          cv_term: CV term
    '''
    if cv not in app.config["VALID_TERMS"]:
        g.c.execute("SELECT cv_term FROM cv_term_vw WHERE cv=%s", (cv))
        cv_terms = g.c.fetchall()
        app.config["VALID_TERMS"][cv] = []
        for term in cv_terms:
            app.config["VALID_TERMS"][cv].append(term["cv_term"])
    return bool(cv_term in app.config["VALID_TERMS"][cv])


def apply_color(text, true_color, condition=True, false_color=None, false_text=None):
    ''' Return colorized text
        Keyword arguments:
          text: text to colorize
          true_color: color if condition is true
          condition: condition to determine color
          false_color: color if condition is false
          false_text: text replacement if condition is false
        Returns:
          colorized text
    '''
    if not condition:
        if false_text:
            text = false_text
        if not false_color:
            return text
    return "<span style='color:%s'>%s</span>" \
           % ((true_color, text) if condition else (false_color, text))


def get_bird_events(bird):
    ''' Get a bird's events
        Keyword arguments:
          bird: bird name
        Returns: Events records
    '''
    try:
        g.c.execute("SELECT * FROM bird_event_vw WHERE name=%s ORDER BY event_date", (bird,))
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    return rows


def get_bird_properties(bird):
    ''' Get a bird's properties
        Keyword arguments:
          bird: bird record
        Returns: HTML
    '''
    bprops = []
    bprops.append(["Name:", bird["name"]])
    bprops.append(["Band:", bird["band"]])
    bprops.append(["Nest:", '<a href="/nest/%s">%s</a>' % tuple([bird["nest"]]*2)])
    bprops.append(["Location:", bird['location']])
    bprops.append(["Claimed by:", apply_color(bird["username"] or "UNCLAIMED", "gold",
                                              (not bird["user"]))])
    bprops.append(["Sex:", bird["sex"]])
    bprops.append(["Sire:", '<a href="/bird/%s">%s</a>' % tuple([bird["sire"]]*2)])
    bprops.append(["Damsel:", '<a href="/bird/%s">%s</a>' % tuple([bird["damsel"]]*2)])
    early = str(bird["hatch_early"]).split(' ', maxsplit=1)[0]
    late = str(bird["hatch_late"]).split(' ', maxsplit=1)[0]
    bprops.append(["Hatch date:", " - ".join([early, late])])
    if bird["alive"]:
        bprops.append(["Current age:", bird["current_age"]])
    alive = apply_color("YES", "lime", bird["alive"], "red", "NO")
    if not bird["alive"]:
        bprops.append(["Death date:", bird["death_date"]])
    bprops.append(["Alive:", alive])
    bprops.append(["Notes:", bird["notes"]])
    try:
        g.c.execute("SELECT type_display,value FROM bird_property_vw WHERE name=%s"
                    "ORDER BY 1", (bird["name"],))
        props = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    for prop in props:
        if not prop["value"]:
            continue
        bprops.append([prop["type_display"], prop["value"]])
    rows = get_bird_events(bird["name"])
    events = ""
    if rows:
        header = ['Status', 'Nest', 'Location', 'User', 'Notes', 'Terminal']
        events = '''
        <h3>Events</h3>
        <table id="events" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        events += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr>' + ''.join("<td>%s</td>")*(len(header)-1) \
                   + '<td style="text-align: center">%s</td></tr>'
        for row in rows:
            terminal = apply_color("YES", "red", row["terminal"], "lime", "NO")
            outcol = [row["status"], row["nest"], row["location"], row["user"],
                      row["notes"], terminal]
            events += template % tuple(outcol)
        events += "</tbody></table>"
    return bprops, events


def get_record(id_or_name, what="clutch"):
    ''' Get a clutch record
        Keyword arguments:
          id_or_name: clutch ID or name
          what: bird, clutch, or nest
        Returns:
          Record
    '''
    sql = f"SELECT * FROM {what}_vw WHERE "
    if id_or_name.isnumeric():
        sql += "id=%s"
    else:
        sql += "name=%s"
    try:
        g.c.execute(sql, (id_or_name))
        result = g.c.fetchone()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    return result


def get_clutch_properties(clutch):
    ''' Get a clutch's properties
        Keyword arguments:
          clutch" cliutch record
    '''
    cprops = []
    nest = '<a href="/nest/%s">%s</a>' % tuple([clutch['nest']]*2)
    cprops.append(["Name:", clutch["name"]])
    cprops.append(["Nest:", nest])
    cprops.append(["End date:", clutch["clutch_start"]])
    cprops.append(["End date:", clutch["clutch_end"]])
    cprops.append(["Notes:", clutch["notes"]])
    return cprops


def get_birds_in_nest(nest, dnd):
    ''' Get the birds in a nest
        Keyword arguments:
          nest: nest record
          dnd: birds to not display
        Returns:
          Birds in nest
    '''
    try:
        g.c.execute("SELECT * FROM bird_vw WHERE nest=%s ORDER BY 1", (nest["name"]))
        irows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    rows = []
    for row in irows:
        if row["name"] in dnd:
            continue
        rows.append(row)
    if rows:
        header = ['Name', 'Band', 'Location', 'Sex', 'Notes',
                  'Current age', 'Alive']
        birds = '''
        <h3>Additional birds</h3>
        <table id="birds" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        birds += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr class="%s">' + ''.join("<td>%s</td>")*len(header) + "</tr>"
        for row in rows:
            rclass = 'alive' if row['alive'] else 'dead'
            bird = '<a href="/bird/%s">%s</a>' % tuple([row['name']]*2)
            if not row['alive']:
                row['current_age'] = '-'
            alive = apply_color("YES", "lime", row["alive"], "red", "NO")
            outcol = [rclass, bird, row['band'], row['location'], row['sex'],
                      row['notes'], row['current_age'], alive]
            birds += template % tuple(outcol)
        birds += "</tbody></table>"
    else:
        birds = "There are no additional birds in this nest."
    return birds


def get_nest_properties(nest):
    ''' Get a nest's properties
        Keyword arguments:
          nest: nest record
        Returns:
          Properties, birds, and clutches
    '''
    nprops = []
    nprops.append(["Name:", nest["name"]])
    nprops.append(["Band:", nest["band"]])
    nprops.append(["Location:", nest["location"]])
    if (nest["sire"] and nest["damsel"]):
        nprops.append(["Sire:", '<a href="/bird/%s">%s</a>' % tuple([nest["sire"]]*2)])
        nprops.append(["Damsel:", '<a href="/bird/%s">%s</a>' % tuple([nest["damsel"]]*2)])
        dnd = [nest["sire"], nest["damsel"]]
    else:
        dnd = []
        for idx in range(1, 4):
            print(nest["female" + str(idx)])
            if nest["female" + str(idx)]:
                nprops.append(["Female " + str(idx), '<a href="/bird/%s">%s</a>'
                               % tuple([nest["female" + str(idx)]]*2)])
                dnd.append(nest["female" + str(idx)])
    nprops.append(["Create date:", nest["create_date"]])
    nprops.append(["Notes:", nest["notes"]])
    active = apply_color("YES", "lime", nest["active"], "red", "NO")
    nprops.append(["Active:", active])
    uses = []
    for use in app.config["UTILIZATION"]:
        if nest[use]:
            uses.append(use)
    if uses:
        nprops.append(["Utilization:", ", ".join(uses)])
    # Bird list
    birds = get_birds_in_nest(nest, dnd)
    # Clutch list
    try:
        g.c.execute("SELECT * FROM clutch_vw WHERE nest=%s ORDER BY 1", (nest["name"]))
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    if rows:
        header = ['Name', 'Notes', 'Clutch start']
        clutches = '''
        <h3>Clutches</h3>
        <table id="clutches" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        clutches += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr>' + ''.join("<td>%s</td>")*len(header) + "</tr>"
        for row in rows:
            nname = '<a href="/clutch/%s">%s</a>' % tuple([row['name']]*2)
            outcol = [nname, row['notes'], row['clutch_start']]
            clutches += template % tuple(outcol)
        clutches += "</tbody></table>"
    else:
        clutches = "There are no clutches in this nest."
    return nprops, birds, clutches


def bird_summary_query(ipd, user):
    ''' Build a bird summary query
        Keyword arguments:
          ipd: request payload
          user: user
        Returns:
          SQL query
    '''
    sql = READ["BSUMMARY"]
    clause = []
    if "start_date" in ipd and ipd["start_date"]:
        clause.append(" (DATE(hatch_early) >= '%s' OR DATE(hatch_late) >= '%s')"
                      % tuple([ipd['start_date']]*2))
    if "stop_date" in ipd and ipd["stop_date"]:
        clause.append(" (DATE(hatch_early) <= '%s' OR DATE(hatch_late) >= '%s')"
                      % tuple([ipd["stop_date"]]*2))
    if "which" in ipd:
        if ipd["which"] == "mine":
            clause.append(" user='%s'" % user)
        elif ipd["which"] == "eligible":
            clause.append(" (user='%s' OR user IS NULL)" % user)
    if clause:
        where = ' AND '.join(clause)
        sql = sql.replace("ORDER BY", "WHERE "  + where + " ORDER BY")
    return sql


def clutch_summary_query(ipd):
    ''' Build a clutch summary query
        Keyword arguments:
          ipd: request payload
        Returns:
          SQL query
    '''
    sql = READ["CSUMMARY"]
    clause = []
    if "start_date" in ipd and ipd["start_date"]:
        clause.append(" (DATE(clutch_start) >= '%s' OR DATE(clutch_end) >= '%s')"
                      % tuple([ipd['start_date']]*2))
    if "stop_date" in ipd and ipd["stop_date"]:
        clause.append(" (DATE(clutch_start) <= '%s' OR DATE(clutch_end) >= '%s')"
                      % tuple([ipd["stop_date"]]*2))
    if clause:
        where = ' AND '.join(clause)
        sql = sql.replace("ORDER BY", "WHERE "  + where + " ORDER BY")
    return sql


def nest_summary_query(ipd):
    ''' Build a nest summary query
        Keyword arguments:
          ipd: request payload
        Returns:
          SQL query
    '''
    sql = READ["NSUMMARY"]
    clause = []
    if "start_date" in ipd and ipd["start_date"]:
        clause.append(" DATE(create_date) >= '%s'" % ipd['start_date'])
    if "stop_date" in ipd and ipd["stop_date"]:
        clause.append(" DATE(create_date) <= '%s'" % ipd['stop_date'])
    if clause:
        where = " AND ".join(clause)
        sql = sql.replace("ORDER BY", "WHERE " + where + " ORDER BY")
    return sql


def get_user_id(user):
    ''' Get a user's ID from the "user" table
        Keyword arguments:
          user: user
    '''
    try:
        g.c.execute("SELECT id FROM user WHERE name='%s'" % user)
        row = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    if not row or "id" not in row:
        raise InvalidUsage(f"User {user} was not found", 404)
    return row['id']


def add_user_permissions(result, user, permissions):
    ''' Add permissions for an existing user
        Keyword arguments:
          result: result dictionary
          user: user
          permissions: list of permissions
    '''
    user_id = get_user_id(user)
    for permission in permissions:
        sql = "INSERT INTO user_permission (user_id,permission_id) VALUES " \
              + "(%s,getCvTermId('permission','%s','')) " \
              + "ON DUPLICATE KEY UPDATE permission_id=permission_id"
        try:
            bind = (user_id, permission,)
            g.c.execute(sql % bind)
            result["rest"]["row_count"] += g.c.rowcount
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err


def generate_bird_pulldown(sex, sid):
    ''' Generate pulldown menu of all live birds of a particular sex
        Keyword arguments:
          sex: sex
          sid: select ID
          use: nest use (breeding or fostering)
        Returns:
          HTML menu
    '''
    controls = ''
    # Exclusions
    sql = "SELECT * FROM nest_vw"
    try:
        g.c.execute(sql)
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    exclude = {}
    for row in rows:
        for rname in ["sire", "damsel", "female1", "female2", "female3"]:
            if row[rname]:
                exclude[row[rname]] = 1
    # Birds
    sql = "SELECT id,name FROM bird where sex='%s' AND alive=1 ORDER BY 2" % (sex)
    try:
        g.c.execute(sql)
        irows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    rows = []
    for row in irows:
        if row["name"] not in exclude:
            rows.append(row)
    if not rows:
        return '<span style="color:red">No birds available</span>'
    controls = '<select id="%s"><option value="">Select a bird...</option>' % (sid)
    for row in rows:
        controls += '<option value="%s">%s</option>' \
                    % (row["id"], row["name"])
    controls += "</select>"
    return controls


def generate_color_pulldown(sid):
    ''' Generate pulldown menu of all colors
        Keyword arguments:
          sid: select ID
        Returns:
          HTML menu
    '''
    controls = ''
    sql = "SELECT cv_term,definition FROM cv_term_vw where cv='color' ORDER BY 1"
    try:
        g.c.execute(sql)
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    controls = '<select id="%s"><option value="">Select a color...</option>' % (sid)
    for row in rows:
        controls += '<option value="%s">%s</option>' \
                    % (row["cv_term"], row["cv_term"])
    controls += "</select>"
    return controls


def generate_location_pulldown(this_id, item_type=None, current=None):
    ''' Generate pulldown menu of all locations (except the current one)
        Keyword arguments:
          this_id: bird or nest ID
          item_type: type of item to move (bird, nest)
          current: current location
        Returns:
          HTML menu
    '''
    controls = ""
    try:
        g.c.execute("SELECT id,display_name FROM cv_term_vw WHERE cv='location' ORDER BY 1")
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    if this_id:
        controls = "Move %s to " % ("birds" if item_type != "bird" else "bird")
    controls += '<select id="location" onchange="select_location(' + str(this_id) + ',this);">' \
                + '<option value="">Select a new location...</option>'
    for row in rows:
        if row["display_name"] == current:
            continue
        controls += '<option value="%s">%s</option>' \
                    % (row['id'], row['display_name'])
    controls += "</select><br><br>"
    return controls


def generate_nest_pulldown(ntype, clutch_or_nest_id=None):
    ''' Generate pulldown menu of all nests (with conditions)
        Keyword arguments:
          ntype: nest type
          clutch_id: clutch ID or current_nest ID
        Returns:
          HTML menu
    '''
    sql = "SELECT id,name FROM nest WHERE active=1 AND "
    clause = []
    if 'breeding' in ntype:
        clause.append("(sire_id IS NOT NULL AND damsel_id IS NOT NULL AND breeding=1)")
    if 'fostering' in ntype:
        clause.append("(fostering=1)")
    sql += " OR ".join(clause) + " ORDER BY 2"
    try:
        g.c.execute(sql)
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    if not rows:
        return '<span style="color:red">No nests available</span>'
    if clutch_or_nest_id:
        controls = '<select id="nest" onchange="select_nest(' + str(clutch_or_nest_id) \
                   + ',this);"><option value="">Select a new nest...</option>'
    else:
        controls = '<select id="nest"><option value="">Select a nest...</option>'
    for row in rows:
        controls += '<option value="%s">%s</option>' \
                    % (row['id'], row['name'])
    controls += "</select><br><br>"
    return controls


def log_bird_event(bird_id=None, status="hatched", user=None, **kwarg):
    ''' Log a bird event
        Keyword arguments:
          bird_id: bird ID
          status: event status
          user: user that logged event
          location: location
          location_id: location ID
          nest_id: nest ID
          terminal: event is terminal
        Returns:
          HTML menu
    '''
    columns = ["bird_id", "status_id", "user_id"]
    values = ["%s", "getCvTermId('bird_status',%s, '')", "%s"]
    bind = [bird_id, status, get_user_id(user)]
    if "location" in kwarg:
        columns.append("location_id")
        values.append("getCvTermId('location', %s, '')")
        bind.append(kwarg["location"])
    elif "location_id" in kwarg:
        columns.append("location_id")
        values.append("%s")
        bind.append(kwarg["location_id"])
    if "nest_id" in kwarg:
        columns.append("nest_id")
        values.append("%s")
        bind.append(kwarg["nest_id"])
    if "terminal" in kwarg and kwarg["terminal"]:
        columns.append("terminal")
        values.append("1")
    sql = "INSERT INTO bird_event (%s) VALUES (%s)"  % (",".join(columns), ",".join(values))
    try:
        print(sql % tuple(bind))
        g.c.execute(sql, tuple(bind))
    except Exception as err:
        raise render_template("error.html", urlroot=request.url_root,
                              title="SQL error", message=sql_error(err))
    #PLUG fix return/raise


def generate_user_pulldown(org, category):
    ''' Generate pulldown menu of all users and organizations
        Keyword arguments:
          org: allowable organizations (None=all)
          category: menu category
        Returns:
          HTML menu
    '''
    controls = ''
    try:
        g.c.execute('SELECT DISTINCT u.* FROM user_vw u JOIN task t ON (u.name=t.user) ' \
                    + 'ORDER BY last,first')
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    controls = "Show " + category
    controls += ' for <select id="proofreader" onchange="select_proofreader(this);">' \
               + '<option value="">Select a proofreader...</option>'
    for row in rows:
        if org:
            rec = get_user_by_name(row["name"])
            if rec["organization"] not in org:
                continue
        controls += '<option value="%s">%s</option>' \
                    % (row['name'], ', '.join([row['last'], row['first']]))
    controls += "</select><br><br>"
    return controls, rows


def build_permissions_table(calling_user, user):
    ''' Generate a user permission table.
        Keyword arguments:
          caslling_user: calling user
          user: user instance
    '''
    permissions = user["permissions"].split(",") if user["permissions"] else []
    template = '<tr><td style="width:300px">%s</td><td style="text-align: center">%s</td></tr>'
    g.c.execute("SELECT cv_term,display_name FROM cv_term_vw WHERE cv='permission' ORDER BY 1")
    rows = g.c.fetchall()
    # Premissions
    parray = []
    disabled = "" if check_permission(calling_user, ["admin"]) else "disabled"
    for row in rows:
        perm = row["cv_term"]
        display = row["display_name"]
        val = 'checked="checked"' if perm in permissions else ''
        check = '<input type="checkbox" %s id="%s" %s onchange="changebox(this);">' \
                % (val, row["cv_term"], disabled)
        if row["cv_term"] in permissions:
            permissions.remove(row["cv_term"])
        parray.append(template % (display, check))
    ptable = '<table><thead><tr style="color:#069"><th>Permission</th>' \
             + '<th>Enabled</th></tr></thead><tbody>' \
             + ''.join(parray) + '</tbody></table>'
    return ptable


def which_birds_user():
    ''' Return a pulldown menu to select bird claimant
        Keyword arguments:
          None
        Returns:
          HTML
    '''
    return '''
    <div style='float: left;margin-left: 10px;'>
    Birds to show:
    <select id="which">
    <option value="mine" selected>Claimed by me</option>
    <option value="eligible">Claimed by me or unclaimed</option>
    <option value="all">All birds</option>
    </select>
    </div>
    '''


def get_user_profile():
    ''' Get the username and picture
        Keyword arguments:
          None
        Returns:
          user: user ID (gmail)
          face: Google profile picture
    '''
    if not request.cookies.get(app.config["TOKEN"]):
        return False, False, False
    token = request.cookies.get(app.config["TOKEN"])
    resp = decode_token(token)
    user = resp["email"]
    face = '<img class="user_image" src="%s" alt="%s">' % (resp['picture'], user)
    permissions = check_permission(user)
    return user, face, permissions


def get_google_provider_cfg():
    ''' Get the Google discovery configuration
        Keyword arguments:
          None
        Returns:
          Google discovery configuration
    '''
    return requests.get(app.config["GOOGLE_DISCOVERY_URL"]).json()


def generate_navbar(active, permissions=None):
    ''' Generate the web navigation bar
        Keyword arguments:
          active: name of active nav
          permissions
        Returns:
          Navigation bar
    '''
    if not permissions:
        permissions = []
    nav = '''
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
      <div class="collapse navbar-collapse" id="navbarSupportedContent">
        <ul class="navbar-nav mr-auto">
    '''
    for heading in ['Birds', 'Clutches', 'Nests', 'Locations', 'Users']:
        basic = '<li class="nav-item active">' if heading == active else '<li class="nav-item">'
        if heading == 'Birds' and set(['admin', 'manager']).intersection(permissions):
            nav += '<li class="nav-item dropdown active">' \
                if heading == active else '<li class="nav-item">'
            nav += '<a class="nav-link dropdown-toggle" href="#" id="navbarDropdown" ' \
                   + 'role="button" data-toggle="dropdown" aria-haspopup="true" ' \
                   + 'aria-expanded="false">Birds</a><div class="dropdown-menu" '\
                   + 'aria-labelledby="navbarDropdown">'
            nav += '<a class="dropdown-item" href="/birdlist">Show</a>' \
                   + '<a class="dropdown-item" href="/newbird">Add</a>'
            nav += '</div></li>'
        elif heading == 'Clutches' and set(['admin', 'manager']).intersection(permissions):
            nav += '<li class="nav-item dropdown active">' \
                if heading == active else '<li class="nav-item">'
            nav += '<a class="nav-link dropdown-toggle" href="#" id="navbarDropdown" ' \
                   + 'role="button" data-toggle="dropdown" aria-haspopup="true" ' \
                   + 'aria-expanded="false">Clutches</a><div class="dropdown-menu" '\
                   + 'aria-labelledby="navbarDropdown">'
            nav += '<a class="dropdown-item" href="/clutchlist">Show</a>' \
                   + '<a class="dropdown-item" href="/newclutch">Add</a>'
            nav += '</div></li>'
        elif heading == 'Nests' and set(['admin', 'manager']).intersection(permissions):
            nav += '<li class="nav-item dropdown active">' \
                if heading == active else '<li class="nav-item">'
            nav += '<a class="nav-link dropdown-toggle" href="#" id="navbarDropdown" ' \
                   + 'role="button" data-toggle="dropdown" aria-haspopup="true" ' \
                   + 'aria-expanded="false">Nests</a><div class="dropdown-menu" '\
                   + 'aria-labelledby="navbarDropdown">'
            nav += '<a class="dropdown-item" href="/nestlist">Show</a>' \
                   + '<a class="dropdown-item" href="/newnest">Add</a>'
            nav += '</div></li>'
        elif heading == 'Users':
            nav += '<li class="nav-item dropdown active">' \
                if heading == active else '<li class="nav-item">'
            nav += '<a class="nav-link dropdown-toggle" href="#" id="navbarDropdown" ' \
                   + 'role="button" data-toggle="dropdown" aria-haspopup="true" ' \
                   + 'aria-expanded="false">Users</a><div class="dropdown-menu" '\
                   + 'aria-labelledby="navbarDropdown">'
            nav += '<a class="dropdown-item" href="/userlist">Show</a>'
            nav += '</div></li>'
        else:
            nav += basic
            link = ('/' + heading[:-1] + 'list').lower()
            nav += '<a class="nav-link" href="%s">%s</a>' % (link, heading)
            nav += '</li>'
    nav += '</ul></div></nav>'
    return nav


def create_downloadable(name, header, template, content):
    ''' Generate a dowenloadabe content file
        Keyword arguments:
          name: base file name
          header: table header
          template: header row template
          content: table content
        Returns:
          File name
    '''
    fname = "%s_%s_%s.tsv" % (name, random_string(), datetime.today().strftime("%Y%m%d%H%M%S"))
    with open("/tmp/%s" % (fname), "w", encoding="utf8") as text_file:
        text_file.write(template % tuple(header))
        text_file.write(content)
    return fname


@app.errorhandler(InvalidUsage)
def handle_invalid_usage(error):
    ''' Error handler
        Keyword arguments:
          error: error object
    '''
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response


# *****************************************************************************
# * Web content                                                               *
# *****************************************************************************

@app.route("/login")
def login():
    ''' Initial login
    '''
    # Find out the Google login URL
    google_provider_cfg = get_google_provider_cfg()
    authorization_endpoint = google_provider_cfg["authorization_endpoint"]

    # Use library to construct the request for Google login and provide
    # scopes that let you retrieve user's profile from Google
    print(request.base_url + "/callback")
    request_uri = CLIENT.prepare_request_uri(
        authorization_endpoint,
        redirect_uri=request.base_url + "/callback",
        scope=["openid", "email", "profile"]
    )
    return redirect(request_uri)


@app.route("/login/callback")
def login_callback():
    ''' Login callback
    '''
    # Get authorization code Google sent back to you
    code = request.args.get("code")

    # Find out what URL to hit to get tokens that allow you to ask for
    # things on behalf of a user
    google_provider_cfg = get_google_provider_cfg()
    token_endpoint = google_provider_cfg["token_endpoint"]

    # Get tokens
    token_url, headers, body = CLIENT.prepare_token_request(
        token_endpoint,
        authorization_response=request.url,
        redirect_url=request.base_url,
        code=code
    )
    token_response = requests.post(
        token_url,
        headers=headers,
        data=body,
        auth=(app.config['GOOGLE_CLIENT_ID'], app.config['GOOGLE_CLIENT_SECRET']),
    )

    # Parse the token
    CLIENT.parse_request_body_response(json.dumps(token_response.json()))

    # Get the user's profile information
    userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
    uri, headers, body = CLIENT.add_token(userinfo_endpoint)
    userinfo_response = requests.get(uri, headers=headers, data=body)
    my_token = token_response.json().get("id_token")

    # Verify the user's email
    if not userinfo_response.json().get("email_verified"):
        return "User email not available or not verified by Google.", 400

    # Set token and send user back to homepage
    response = make_response(redirect("/"))
    response.set_cookie(app.config['TOKEN'], my_token)
    return response


@app.route('/profile')
def profile():
    ''' Show user profile
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message="User %s is not registered" % user)
    try:
        rec = get_user_by_name(user)
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    if not rec:
        return render_template("error.html", urlroot=request.url_root,
                               title='User error', message=("Could not find user %s" % user))
    uprops = []
    name = []
    for nkey in ['first', 'last']:
        if nkey in rec:
            name.append(rec[nkey])
    uprops.append(['Name:', ' '.join(name)])
    uprops.append(['Janelia ID:', rec['janelia_id']])
    uprops.append(['Organization:', rec['organization']])
    uprops.append(['Permissions:', '<br>'.join(rec['permissions'].split(','))])
    token = request.cookies.get(app.config['TOKEN'])
    return render_template('profile.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], user=user,
                           navbar=generate_navbar('Users', permissions), uprops=uprops, token=token)


@app.route('/userlist')
def user_list():
    ''' Show list of users
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message="User %s is not registered" % user)
    if not set(['admin', 'manager']).intersection(permissions):
        return redirect("/profile")
    try:
        g.c.execute('SELECT * FROM user_vw ORDER BY janelia_id')
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    urows = ''
    template = '<tr class="%s">' + ''.join("<td>%s</td>")*6 + "</tr>"
    organizations = {}
    for row in rows:
        rclass = re.sub('[^0-9a-zA-Z]+', '_', row['organization'])
        organizations[rclass] = row['organization']
        link = '<a href="/user/%s">%s</a>' % (row['name'], row['name'])
        if not row['permissions']:
            row['permissions'] = '-'
        else:
            showarr = []
            for perm in row['permissions'].split(','):
                if perm in app.config['PROTOCOLS']:
                    this_perm = '<span style="color:cyan">%s</span>' % app.config['PROTOCOLS'][perm]
                elif perm in app.config['GROUPS']:
                    this_perm = '<span style="color:gold">%s</span>' % perm
                else:
                    this_perm = '<span style="color:orange">%s</span>' % perm
                showarr.append(this_perm)
            row['permissions'] = ', '.join(showarr)
        urows += template % (rclass, ', '.join([row['last'], row['first']]), link,
                             row['janelia_id'], row['email'], row['organization'],
                             row['permissions'])
    adduser = ''
    if set(["admin"]).intersection(permissions):
        adduser = '''
        <br>
        <h3>Add a user</h3>
        <div class="form-group">
          <div class="col-md-3">
            <label for="Input1">Gmail address</label>
            <input type="text" class="form-control" id="user_name" aria-describedby="usernameHelp" placeholder="Enter Google email address">
            <small id="usernameHelp" class="form-text text-muted">This will be the username.</small>
          </div>
        </div>
        <div id="myRadioGroup">
        HHMI user <input type="radio" name="hhmi_radio" checked="checked" value="hhmi" onclick="change_usertype('hhmi');" />
        &nbsp;&nbsp;&nbsp;
        Non-HHMI <input type="radio" name="hhmi_radio" value="non_hhmi" onclick="change_usertype('non_hhmi');"/>
        <div id="hhmi" class="hhmidesc">
        <div class="form-group">
          <div class="col-md-3">
            <label for="Input2">Janelia ID</label>
            <input type="text" class="form-control" id="janelia_id" aria-describedby="jidHelp" placeholder="Enter Janelia ID">
            <small id="jidHelp" class="form-text text-muted">Enter the Janelia user ID.</small>
          </div>
        </div>
        </div>
        <div id="non_hhmi" class="hhmidesc" style="display: none;">
        <div class="form-group">
          <div class="col-md-3">
            <label for="Input3">First name</label>
            <input type="text" class="form-control" id="first_name" aria-describedby="jidHelp" placeholder="Enter first name">
            <small id="jidHelp" class="form-text text-muted">Enter the user's first name.</small>
          </div>
        </div>
        <div class="form-group">
          <div class="col-md-3">
            <label for="Input3">Last name</label>
            <input type="text" class="form-control" id="last_name" aria-describedby="jidHelp" placeholder="Enter last name">
            <small id="jidHelp" class="form-text text-muted">Enter the user's last name.</small>
          </div>
        </div>
        <div class="form-group">
          <div class="col-md-3">
            <label for="Input3">Preferred email</label>
            <input type="text" class="form-control" id="email" aria-describedby="jidHelp" placeholder="Enter preferred email">
            <small id="jidHelp" class="form-text text-muted">Enter the user's preferred email address.</small>
          </div>
        </div>
        </div>
        <button type="submit" id="sb" class="btn btn-primary" onclick="add_user();" href="#">Add user</button>
        '''
    return render_template('userlist.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], user=user,
                           navbar=generate_navbar('Users', permissions),
                           organizations=organizations, userrows=urows, adduser=adduser)


@app.route('/user/<string:uname>')
def user_config(uname):
    ''' Show user profile
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message="User %s is not registered" % user)
    if not set(["admin"]).intersection(permissions) and (uname != user):
        return render_template("error.html", urlroot=request.url_root,
                               title='Permission error',
                               message="You don't have permission to view another user's profile")
    try:
        rec = get_user_by_name(uname)
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    if not rec:
        return render_template("error.html", urlroot=request.url_root,
                               title='Not found',
                               message="User %s was not found" % uname)
    uprops = []
    uprops.append(['Name:', ' '.join([rec['first'], rec['last']])])
    uprops.append(['Janelia ID:', rec['janelia_id']])
    uprops.append(['Email:', rec['email']])
    uprops.append(['Organization:', rec['organization']])
    ptable = build_permissions_table(user, rec)
    return render_template('user.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], user=uname,
                           navbar=generate_navbar('Users', permissions),
                           uprops=uprops, ptable=ptable)


@app.route('/logout')
def logout():
    ''' Log out
    '''
    if not request.cookies.get(app.config['TOKEN']):
        return render_template("error.html", urlroot=request.url_root,
                               title='You are not logged in',
                               message="You can't log out unless you're logged in")
    response = make_response(render_template('logout.html', urlroot=request.url_root))
#    response.set_cookie(app.config['TOKEN'], '', domain='.janelia.org', expires=0)
    response.set_cookie(app.config['TOKEN'], '', expires=0)
    return response


@app.route('/download/<string:fname>')
def download(fname):
    ''' Downloadable content
    '''
    try:
        return send_file('/tmp/' + fname, attachment_filename=fname)
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title='Download error', message=err)


@app.route('/')
@app.route('/birdlist', methods=['GET', 'POST'])
def show_birds(): # pylint: disable=R0914,R0912,R0915
    ''' Birds
    '''
    if not request.cookies.get(app.config['TOKEN']):
        return redirect(request.base_url + "/login")
    token = request.cookies.get(app.config['TOKEN'])
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message="User {user} is not registered")
    result = initialize_result()
    ipd = receive_payload(result)
    if not ipd or ("which" not in ipd):
        ipd = {"which": "mine"}
    try:
        g.c.execute(bird_summary_query(ipd, user))
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    controls = which_birds_user()
    if rows:
        header = ['Name', 'Band', 'Nest', 'Location', 'Sex', 'Notes',
                  'Current age', 'Alive']
        if ipd["which"] != "mine":
            header.insert(3, "Claimed by")
        birds = '''
        <table id="birds" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        birds += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr class="%s">' + ''.join("<td>%s</td>")*len(header) + "</tr>"
        fileoutput = ''
        ftemplate = "\t".join(["%s"]*len(header)) + "\n"
        for row in rows:
            outcol = [row['name'], row['band'], row['nest'], row['location'],
                      row['sex'], row['notes'], row['current_age'], row['alive']]
            if ipd["which"] != "mine":
                outcol.insert(3, row["username"])
            fileoutput += ftemplate % tuple(outcol)
            rclass = 'alive' if row['alive'] else 'dead'
            bird = '<a href="/bird/%s">%s</a>' % tuple([row['name']]*2)
            if not row['alive']:
                row['current_age'] = '-'
            alive = apply_color("YES", "lime", row["alive"], "red", "NO")
            nest = '<a href="/nest/%s">%s</a>' % tuple([row['nest']]*2)
            outcol = [rclass, bird, row['band'], nest, row['location'], row['sex'],
                      row['notes'], row['current_age'], alive]
            if ipd["which"] != "mine":
                outcol.insert(4, row["username"])
            birds += template % tuple(outcol)
        birds += "</tbody></table>"
        downloadable = create_downloadable('birds', header, ftemplate, fileoutput)
        birds = '<a class="btn btn-outline-info btn-sm" href="/download/%s" ' \
                   % (downloadable) + 'role="button">Download table</a>' + birds
    else:
        birds = "There are no birds"
    if request.method == 'POST':
        return {"birds": birds}
    if not token:
        token = ''
    response = make_response(render_template('birdlist.html', urlroot=request.url_root,
                                             face=face, dataset=app.config['DATASET'],
                                             navbar=generate_navbar('Birds', permissions),
                                             controls=controls, birds=birds))
    response.set_cookie(app.config['TOKEN'], token, domain='.janelia.org')
    return response


@app.route('/bird/<string:bname>')
def show_bird(bname):
    ''' Show information for a bird
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message="User %s is not registered" % user)
    try:
        g.c.execute("SELECT * FROM bird_vw WHERE name=%s", (bname,))
        bird = g.c.fetchone()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    if not bird:
        return render_template("error.html", urlroot=request.url_root,
                               title='Not found', message="Bird %s was not found" % bname)
    try:
        g.c.execute("SELECT * FROM bird WHERE name=%s", (bname,))
        nest = g.c.fetchone()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    controls = '<br>'
    if bird["alive"] and set(['admin', 'edit', 'manager']).intersection(permissions):
        if bird["user"] == user:
            nestpull = generate_nest_pulldown(["fostering", "tutoring"], nest['id'])
            if "No nest" not in nestpull:
                controls += "Move bird to " + nestpull
            controls += generate_location_pulldown(bird['id'], "bird", bird['location'])
            controls += '''
            <button type="button" class="btn btn-warning btn-sm" onclick='update_bird(%s,"unclaim");'>Unclaim bird</button>
            '''
            controls = controls % (bird['id'])
            controls += '''
            <button type="button" class="btn btn-danger btn-sm" onclick='update_bird(%s,"dead");'>Report bird as dead</button>
            '''
            controls = controls % (bird['id'])
        elif not bird["user"]:
            if set(['admin', 'manager']).intersection(permissions):
                controls += generate_location_pulldown(bird['id'], "bird", bird['location'])
            controls += '''
            <button type="button" class="btn btn-success btn-sm" onclick='update_bird(%s,"claim");'>Claim bird</button>
            '''
            controls = controls % (bird['id'])
    if not(bird["alive"]) and set(['admin', 'manager']).intersection(permissions):
        controls += '''
        <button type="button" class="btn btn-info btn-sm" onclick='update_bird(%s,"alive");'>Mark bird as alive</button>
        '''
        controls = controls % (bird['id'])
    bprops, events = get_bird_properties(bird)
    return render_template('bird.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Birds', permissions),
                           bird=bname, bprops=bprops, events=events, controls=controls)


@app.route('/newbird')
def new_bird():
    ''' Register a new bird
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message="User %s is not registered" % user)
    if not set(['admin', 'manager']).intersection(permissions):
        return render_template("error.html", urlroot=request.url_root,
                               title='Not permitted',
                               message="You don't have permission to register a new bird")
    return render_template('newbird.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Birds', permissions),
                           nestselect=generate_nest_pulldown(["breeding"]))


@app.route('/clutchlist', methods=['GET', 'POST'])
def show_clutches(): # pylint: disable=R0914,R0912,R0915
    ''' Clutches
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message="User %s is not registered" % user)
    result = initialize_result()
    ipd = receive_payload(result)
    try:
        g.c.execute(clutch_summary_query(ipd))
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    if rows:
        header = ['Name', 'Nest', 'Start', 'End', 'Notes']
        clutches = '''
        <table id="clutches" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        clutches += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr class="open">' + ''.join("<td>%s</td>")*5 + "</tr>"
        fileoutput = ''
        ftemplate = "\t".join(["%s"]*5) + "\n"
        for row in rows:
            fileoutput += ftemplate % (row['name'], row['nest'], row['clutch_start'],
                                       row['clutch_end'], row['notes'])
            nest = '<a href="/nest/%s">%s</a>' % tuple([row['nest']]*2)
            clutch = '<a href="/clutch/%s">%s</a>' % tuple([row['name']]*2)
            clutches += template % (clutch, nest, row['clutch_start'], row['clutch_end'],
                                    row['notes'])
        clutches += "</tbody></table>"
        downloadable = create_downloadable('clutches', header, ftemplate, fileoutput)
        clutches = f'<a class="btn btn-outline-info btn-sm" href="/download/{downloadable}" ' \
                   + 'role="button">Download table</a>' + clutches
    else:
        clutches = "There are no clutches"
    if request.method == 'POST':
        return {"clutches": clutches}
    response = make_response(render_template('clutchlist.html', urlroot=request.url_root,
                                             face=face, dataset=app.config['DATASET'],
                                             navbar=generate_navbar('Clutches', permissions),
                                             clutches=clutches))
    return response


@app.route('/clutch/<string:cname>')
def show_clutch(cname):
    ''' Show information for a clutch
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message=f"User {user} is not registered")
    clutch = get_record(cname, "clutch")
    if not clutch:
        return render_template("error.html", urlroot=request.url_root,
                               title="Not found", message=f"Clutch {cname} was not found")
    controls = ""
    print(clutch)
    if set(['admin', 'manager']).intersection(permissions):
        controls += "<br>Move clutch to " \
                    + generate_nest_pulldown(["breeding", "fostering"], clutch["id"])
    return render_template('clutch.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Clutches', permissions),
                           clutch=cname, nprops=get_clutch_properties(clutch), controls=controls)


@app.route('/newclutch')
def new_clutch():
    ''' Register a new clutch
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message="User %s is not registered" % user)
    if not set(['admin', 'manager']).intersection(permissions):
        return render_template("error.html", urlroot=request.url_root,
                               title='Not permitted',
                               message="You don't have permission to register a new clutch")
    return render_template('newclutch.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Clutches', permissions),
                           start=date.today().strftime("%Y-%m-%d"),
                           nestselect=generate_nest_pulldown(["breeding", "fostering"]))


@app.route('/nestlist', methods=['GET', 'POST'])
def show_nests(): # pylint: disable=R0914,R0912,R0915
    ''' Nest
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message="User %s is not registered" % user)
    result = initialize_result()
    ipd = receive_payload(result)
    try:
        g.c.execute(nest_summary_query(ipd))
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    if rows:
        header = ['Name', 'Band', 'Sire', 'Damsel', 'Location', 'Notes']
        nests = '''
        <table id="nests" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        nests += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr class="open">' + ''.join("<td>%s</td>")*6 + "</tr>"
        fileoutput = ''
        ftemplate = "\t".join(["%s"]*6) + "\n"
        for row in rows:
            fileoutput += ftemplate % (row['name'], row['band'], row['sire'],
                                       row['damsel'], row['location'], row['notes'])
            nest = '<a href="/nest/%s">%s</a>' % tuple([row['name']]*2)
            sire = '<a href="/bird/%s">%s</a>' % tuple([row['sire']]*2)
            damsel = '<a href="/bird/%s">%s</a>' % tuple([row['damsel']]*2)
            nests += template % (nest, row['band'], sire, damsel,
                                 row['location'], row['notes'])
        nests += "</tbody></table>"
        downloadable = create_downloadable('nests', header, ftemplate, fileoutput)
        nests = f'<a class="btn btn-outline-info btn-sm" href="/download/{downloadable}" ' \
                 + 'role="button">Download table</a>' + nests
    else:
        nests = "There are no nests"
    if request.method == 'POST':
        return {"nests": nests}
    response = make_response(render_template('nestlist.html', urlroot=request.url_root,
                                             face=face, dataset=app.config['DATASET'],
                                             navbar=generate_navbar('Nests', permissions),
                                             nests=nests))
    return response


@app.route('/nest/<string:nname>')
def show_nest(nname):
    ''' Show information for a nest
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message=f"User {user} is not registered")
    nest = get_record(nname, "nest")
    if not nest:
        return render_template("error.html", urlroot=request.url_root,
                               title="Not found", message=f"Nest {nname} was not found")
    controls = '<br>'
    if set(['admin', 'manager']).intersection(permissions):
        nestpull = generate_nest_pulldown(["fostering", "tutoring"], nest['id'])
        if "No nest" not in nestpull:
            controls += "Move birds to " + nestpull
        controls += generate_location_pulldown(nest['id'], "nest")
    nprops, birds, clutches = get_nest_properties(nest)
    return render_template('nest.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Nests', permissions),
                           nest=nname, nprops=nprops, birds=birds, clutches=clutches,
                           controls=controls)


@app.route('/newnest')
def new_nest():
    ''' Register a new nest
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message="User %s is not registered" % user)
    if not set(['admin', 'manager']).intersection(permissions):
        return render_template("error.html", urlroot=request.url_root,
                               title='Not permitted',
                               message="You don't have permission to register a new nest")
    return render_template('newnest.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Nests', permissions),
                           start=date.today().strftime("%Y-%m-%d"),
                           color1select=generate_color_pulldown("color1"),
                           color2select=generate_color_pulldown("color2"),
                           locationselect=generate_location_pulldown(0),
                           sire1select=generate_bird_pulldown("M", "sire"),
                           damsel1select=generate_bird_pulldown("F", "damsel"),
                           female1select=generate_bird_pulldown("F", "female1"),
                           female2select=generate_bird_pulldown("F", "female2"),
                           female3select=generate_bird_pulldown("F", "female3"))


@app.route('/locationlist', methods=['GET', 'POST'])
def show_locations(): # pylint: disable=R0914,R0912,R0915
    ''' Locations
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message=f"User {user} is not registered")
    try:
        g.c.execute(READ['LSUMMARY'])
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    locrows = ''
    if rows:
        header = ['Location', 'Description', 'Number of birds']
        template = '<tr class="open">' + ''.join("<td>%s</td>")*(len(header)-1) \
                   + '<td style="text-align: center">%s</td></tr>'
        fileoutput = ''
        ftemplate = "\t".join(["%s"]*len(header)) + "\n"
        for row in rows:
            fileoutput += ftemplate % (row['display_name'], row['definition'], row['cnt'])
            locrows += template % (row['display_name'], row['definition'], row['cnt'])
        downloadable = create_downloadable('locations', header, ftemplate, fileoutput)
        locations = f'<a class="btn btn-outline-info btn-sm" href="/download/{downloadable}" ' \
                    + 'role="button">Download table</a>'
    else:
        locations = "There are no locations"
    if request.method == 'POST':
        return {"locations": locations}
    addloc = ''
    if set(['admin', 'edit', 'manager']).intersection(permissions):
        addloc = '''
        <br>
        <h3>Add a location</h3>
        <div class="form-group">
          <div class="col-md-5">
            <label for="Input1">Location</label>
            <input type="text" size="100" class="form-control" id="display_name" aria-describedby="itemHelp" placeholder="Enter location name">
            <small id="itemHelp" class="form-text text-muted">Enter the location name.</small>
          </div>
        </div>
        <div class="form-group">
          <div class="col-md-5">
            <label for="Input2">Description</label>
            <input type="text" class="form-control" id="definition" aria-describedby="itemHelp" placeholder="Enter description (option)">
            <small id="itemHelp" class="form-text text-muted">Enter the description.</small>
          </div>
        </div>
        <button type="submit" id="sb" class="btn btn-primary" onclick="add_location();" href="#">Add location</button>
        '''
    response = make_response(render_template('locationlist.html', urlroot=request.url_root,
                                             face=face, dataset=app.config['DATASET'],
                                             navbar=generate_navbar('Locations', permissions),
                                             locations=locations, locationrows=locrows,
                                             addlocation=addloc))
    return response


# *****************************************************************************
# * Endpoints                                                                 *
# *****************************************************************************

@app.route('/help')
def show_swagger():
    ''' Show Swagger docs
    '''
    return render_template('swagger_ui.html')


@app.route("/spec")
def spec():
    ''' Show specification
    '''
    return get_doc_json()


@app.route('/doc')
def get_doc_json():
    ''' Show documentation
    '''
    swag = swagger(app)
    swag['info']['version'] = __version__
    swag['info']['title'] = "Birdsong Responder"
    return jsonify(swag)


@app.route("/stats")
def stats():
    '''
    Show stats
    Show uptime/requests statistics
    ---
    tags:
      - Diagnostics
    responses:
      200:
          description: Stats
      400:
          description: Stats could not be calculated
    '''
    tbt = time() - app.config['LAST_TRANSACTION']
    result = initialize_result()
    db_connection = True
    try:
        g.db.ping(reconnect=False)
    except Exception as err:
        temp = "{2}: An exception of type {0} occurred. Arguments:\n{1!r}"
        mess = temp.format(type(err).__name__, err.args, inspect.stack()[0][3])
        result['rest']['error'] = mess
        db_connection = False
    try:
        start = datetime.fromtimestamp(app.config['STARTTIME']).strftime('%Y-%m-%d %H:%M:%S')
        up_time = datetime.now() - app.config['STARTDT']
        result['stats'] = {"version": __version__,
                           "requests": app.config['COUNTER'],
                           "start_time": start,
                           "uptime": str(up_time),
                           "python": sys.version,
                           "pid": os.getpid(),
                           "endpoint_counts": app.config['ENDPOINTS'],
                           "user_counts": app.config['USERS'],
                           "time_since_last_transaction": tbt,
                           "database_connection": db_connection}
        if None in result['stats']['endpoint_counts']:
            del result['stats']['endpoint_counts']
    except Exception as err:
        temp = "{2}: An exception of type {0} occurred. Arguments:\n{1!r}"
        mess = temp.format(type(err).__name__, err.args, inspect.stack()[0][3])
        raise InvalidUsage(mess, 500) from err
    return generate_response(result)


@app.route("/dbstats")
def dbstats():
    '''
    Show database stats
    Show database statistics
    ---
    tags:
      - Diagnostics
    responses:
      200:
          description: Database tats
      400:
          description: Database stats could not be calculated
    '''
    result = initialize_result()
    sql = "SELECT TABLE_NAME,TABLE_ROWS FROM INFORMATION_SCHEMA.TABLES WHERE " \
          + "TABLE_SCHEMA='assignment' AND TABLE_NAME NOT LIKE '%vw'"
    g.c.execute(sql)
    rows = g.c.fetchall()
    result['rest']['row_count'] = len(rows)
    result['rest']['sql_statement'] = g.c.mogrify(sql)
    result['data'] = {}
    for r in rows:
        result['data'][r['TABLE_NAME']] = r['TABLE_ROWS']
    return generate_response(result)


@app.route('/processlist/columns', methods=['GET'])
def get_processlist_columns():
    '''
    Get columns from the system processlist table
    Show the columns in the system processlist table, which may be used to
     filter results for the /processlist endpoints.
    ---
    tags:
      - Diagnostics
    responses:
      200:
          description: Columns in system processlist table
    '''
    result = initialize_result()
    show_columns(result, "information_schema.processlist")
    return generate_response(result)


@app.route('/processlist', methods=['GET'])
def get_processlist_info():
    '''
    Get processlist information (with filtering)
    Return a list of processlist entries (rows from the system processlist
     table). The caller can filter on any of the columns in the system
     processlist table. Inequalities (!=) and some relational operations
     (&lt;= and &gt;=) are supported. Wildcards are supported (use "*").
     Specific columns from the system processlist table can be returned with
     the _columns key. The returned list may be ordered by specifying a column
     with the _sort key. In both cases, multiple columns would be separated
     by a comma.
    ---
    tags:
      - Diagnostics
    responses:
      200:
          description: List of information for one or database processes
      404:
          description: Processlist information not found
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM information_schema.processlist', 'data')
    for row in result['data']:
        row['HOST'] = 'None' if not row['HOST'] else row['HOST'] #.decode("utf-8")
    return generate_response(result)


@app.route('/processlist/host', methods=['GET'])
def get_processlist_host_info(): # pragma: no cover
    '''
    Get processlist information for this host
    Return a list of processlist entries (rows from the system processlist
     table) for this host.
    ---
    tags:
      - Diagnostics
    responses:
      200:
          description: Database process list information for the current host
      404:
          description: Processlist information not found
    '''
    result = initialize_result()
    hostname = platform.node() + '%'
    try:
        sql = "SELECT * FROM information_schema.processlist WHERE host LIKE %s"
        bind = (hostname)
        g.c.execute(sql, bind)
        rows = g.c.fetchall()
        result['rest']['row_count'] = len(rows)
        result['rest']['sql_statement'] = g.c.mogrify(sql, bind)
        for row in rows:
            row['HOST'] = 'None' if row['HOST'] is None else row['HOST'].decode("utf-8")
        result['data'] = rows
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    return generate_response(result)


@app.route("/ping")
def pingdb():
    '''
    Ping the database connection
    Ping the database connection and reconnect if needed
    ---
    tags:
      - Diagnostics
    responses:
      200:
          description: Ping successful
      400:
          description: Ping unsuccessful
    '''
    result = initialize_result()
    try:
        g.db.ping()
    except Exception as err:
        raise InvalidUsage(sql_error(err)) from err
    return generate_response(result)


# *****************************************************************************
# * Test endpoints                                                            *
# *****************************************************************************
@app.route('/test_sqlerror', methods=['GET'])
def testsqlerror():
    ''' Test function
    '''
    result = initialize_result()
    try:
        sql = "SELECT some_column FROM non_existent_table"
        result['rest']['sql_statement'] = sql
        g.c.execute(sql)
        rows = g.c.fetchall()
        return rows
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err


@app.route('/test_other_error', methods=['GET'])
def testothererror():
    ''' Test function
    '''
    result = initialize_result()
    try:
        testval = 4 / 0
        result['testval'] = testval
        return result
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err


# *****************************************************************************
# * View endpoints                                                            *
# *****************************************************************************

@app.route('/columns/cv_term', methods=['GET'])
@app.route('/columns/bird', methods=['GET'])
@app.route('/columns/bird_event', methods=['GET'])
@app.route('/columns/bird_property', methods=['GET'])
@app.route('/columns/bird_relationship', methods=['GET'])
@app.route('/columns/nest', methods=['GET'])
@app.route('/columns/nest_event', methods=['GET'])
@app.route('/columns/user', methods=['GET'])
@app.route('/columns/user_permission', methods=['GET'])
def get_view_columns():
    '''
    Get columns from a view
    Show the columns in the bird_vw table, which may be used to filter
     results for the /birds and /bird_ids endpoints.
    ---
    tags:
      - Bird
    responses:
      200:
          description: Columns in specified view
    '''
    result = initialize_result()
    table = re.search("/columns/([^/]+)", request.url, re.IGNORECASE)
    if table:
        table = table.group(1)
    show_columns(result, table + "_vw")
    return generate_response(result)


@app.route('/view/cv_term', methods=['GET'])
@app.route('/view/bird', methods=['GET'])
@app.route('/view/bird_event', methods=['GET'])
@app.route('/view/bird_property', methods=['GET'])
@app.route('/view/bird_relationship', methods=['GET'])
@app.route('/view/nest', methods=['GET'])
@app.route('/view/nest_event', methods=['GET'])
@app.route('/view/user', methods=['GET'])
@app.route('/view/user_permission', methods=['GET'])
def get_view_rows():
    '''
    Get view rows (with filtering)
    Return a list of birds (rows from the bird_vw table). The
     caller can filter on any of the columns in the bird_vw table.
     Inequalities (!=) and some relational operations (&lt;= and &gt;=) are
     supported. Wildcards are supported (use "*"). Specific columns from the
     bird_vw table can be returned with the _columns key. The returned
     list may be ordered by specifying a column with the _sort key. In both
     cases, multiple columns would be separated by a comma.
    ---
    tags:
      - Bird
    responses:
      200:
          description: rows from specified view
      404:
          description: Rows not found
    '''
    result = initialize_result()
    statement = re.search("/view/([^/]+)$", request.url, re.IGNORECASE)
    if statement:
        table = statement.group(1)
        table = re.sub("[?;].*", "", table)
    execute_sql(result, f"SELECT * FROM {table}_vw", "data")
    return generate_response(result)


# *****************************************************************************
# * CV/CV term endpoints                                                      *
# *****************************************************************************

@app.route('/cv_ids', methods=['GET'])
def get_cv_ids():
    '''
    Get CV IDs (with filtering)
    Return a list of CV IDs. The caller can filter on any of the columns in the
     cv table. Inequalities (!=) and some relational operations (&lt;= and &gt;=)
     are supported. Wildcards are supported (use "*"). The returned list may be
     ordered by specifying a column with the _sort key. Multiple columns should
     be separated by a comma.
    ---
    tags:
      - CV
    responses:
      200:
          description: List of one or more CV IDs
      404:
          description: CVs not found
    '''
    result = initialize_result()
    if execute_sql(result, 'SELECT id FROM cv', 'temp'):
        result['data'] = []
        for col in result['temp']:
            result['data'].append(col['id'])
        del result['temp']
    return generate_response(result)


@app.route('/cvs/<string:sid>', methods=['GET'])
def get_cv_by_id(sid):
    '''
    Get CV information for a given ID
    Given an ID, return a row from the cv table. Specific columns from the cv
     table can be returned with the _columns key. Multiple columns should be
     separated by a comma.
    ---
    tags:
      - CV
    parameters:
      - in: path
        name: sid
        schema:
          type: string
        required: true
        description: CV ID
    responses:
      200:
          description: Information for one CV
      404:
          description: CV ID not found
    '''
    result = initialize_result()
    if execute_sql(result, 'SELECT * FROM cv', 'temp', sid):
        get_cv_data(result, result['temp'])
        del result['temp']
    return generate_response(result)


@app.route('/cvs', methods=['GET'])
def get_cv_info():
    '''
    Get CV information (with filtering)
    Return a list of CVs (rows from the cv table). The caller can filter on
     any of the columns in the cv table. Inequalities (!=) and some relational
     operations (&lt;= and &gt;=) are supported. Wildcards are supported
     (use "*"). Specific columns from the cv table can be returned with the
     _columns key. The returned list may be ordered by specifying a column with
     the _sort key. In both cases, multiple columns would be separated by a
     comma.
    ---
    tags:
      - CV
    responses:
      200:
          description: List of information for one or more CVs
      404:
          description: CVs not found
    '''
    result = initialize_result()
    if execute_sql(result, 'SELECT * FROM cv', 'temp'):
        get_cv_data(result, result['temp'])
        del result['temp']
    return generate_response(result)


@app.route('/cv', methods=['OPTIONS', 'POST'])
def add_cv(): # pragma: no cover
    '''
    Add CV
    ---
    tags:
      - CV
    parameters:
      - in: query
        name: name
        schema:
          type: string
        required: true
        description: CV name
      - in: query
        name: definition
        schema:
          type: string
        required: true
        description: CV description
      - in: query
        name: display_name
        schema:
          type: string
        required: false
        description: CV display name (defaults to CV name)
      - in: query
        name: version
        schema:
          type: string
        required: false
        description: CV version (defaults to 1)
      - in: query
        name: is_current
        schema:
          type: string
        required: false
        description: is CV current? (defaults to 1)
    responses:
      200:
          description: CV added
      400:
          description: Missing arguments
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    check_missing_parms(ipd, ['definition', 'name'])
    if 'display_name' not in ipd:
        ipd['display_name'] = ipd['name']
    if 'version' not in ipd:
        ipd['version'] = 1
    if 'is_current' not in ipd:
        ipd['is_current'] = 1
    if not result['rest']['error']:
        try:
            bind = (ipd['name'], ipd['definition'], ipd['display_name'],
                    ipd['version'], ipd['is_current'],)
            g.c.execute(WRITE['INSERT_CV'], bind)
            result['rest']['row_count'] = g.c.rowcount
            result['rest']['inserted_id'] = g.c.lastrowid
            result['rest']['sql_statement'] = g.c.mogrify(WRITE['INSERT_CV'], bind)
            g.db.commit()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
    return generate_response(result)


@app.route('/cvterm', methods=['OPTIONS', 'POST'])
def add_cv_term(): # pragma: no cover
    '''
    Add CV term
    ---
    tags:
      - CV
    parameters:
      - in: query
        name: cv
        schema:
          type: string
        required: true
        description: CV name
      - in: query
        name: name
        schema:
          type: string
        required: true
        description: CV term name
      - in: query
        name: definition
        schema:
          type: string
        required: true
        description: CV term description
      - in: query
        name: display_name
        schema:
          type: string
        required: false
        description: CV term display name (defaults to CV term name)
      - in: query
        name: is_current
        schema:
          type: string
        required: false
        description: is CV term current? (defaults to 1)
      - in: query
        name: data_type
        schema:
          type: string
        required: false
        description: data type (defaults to text)
    responses:
      200:
          description: CV term added
      400:
          description: Missing arguments
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    check_missing_parms(ipd, ['cv', 'definition', 'name'])
    if 'display_name' not in ipd:
        ipd['display_name'] = ipd['name']
    if 'is_current' not in ipd:
        ipd['is_current'] = 1
    if 'data_type' not in ipd:
        ipd['data_type'] = 'text'
    if not result['rest']['error']:
        try:
            bind = (ipd['cv'], ipd['name'], ipd['definition'],
                    ipd['display_name'], ipd['is_current'],
                    ipd['data_type'],)
            g.c.execute(WRITE['INSERT_CVTERM'], bind)
            result['rest']['row_count'] = g.c.rowcount
            result['rest']['inserted_id'] = g.c.lastrowid
            result['rest']['sql_statement'] = g.c.mogrify(WRITE['INSERT_CVTERM'], bind)
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
    return generate_response(result)


# *****************************************************************************
# * Bird endpoints                                                            *
# *****************************************************************************

@app.route('/bird/location/<string:bird_id>/<string:location_id>', methods=['OPTIONS', 'POST'])
def bird_location(bird_id, location_id):
    '''
    Move a bird to a new location
    Update a bird's location.
    ---
    tags:
      - Bird
    parameters:
      - in: path
        name: bird_id
        schema:
          type: string
        required: true
        description: bird ID
      - in: path
        name: location_id
        schema:
          type: string
        required: true
        description: location ID
    '''
    result = initialize_result()
    if not check_permission(result["rest"]["user"], ["admin"]):
        raise InvalidUsage("You don't have permission to change a bird's location")
    result["rest"]["row_count"] = 0
    sql = "UPDATE bird SET location_id =%s WHERE id=%s"
    try:
        bind = (location_id, bird_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    log_bird_event(result["rest"]["bird_id"], status="moved", user=result['rest']['user'],
                   location_id=location_id)
    g.db.commit()
    return generate_response(result)


@app.route('/bird/nest/<string:bird_id>/<string:nest_id>', methods=['OPTIONS', 'POST'])
def bird_nest(bird_id, nest_id):
    '''
    Move a bird to a new nest
    Update a bird's nest.
    ---
    tags:
      - Bird
    parameters:
      - in: path
        name: bird_id
        schema:
          type: string
        required: true
        description: bird ID
      - in: path
        name: nest_id
        schema:
          type: string
        required: true
        description: nest ID
    '''
    result = initialize_result()
    if not check_permission(result["rest"]["user"], ["admin"]):
        raise InvalidUsage("You don't have permission to change a bird's nest")
    result["rest"]["row_count"] = 0
    try:
        bind = (nest_id)
        g.c.execute("SELECT location_id FROM bird WHERE nest_id=%s LIMIT 1", bind)
        row = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    sql = "UPDATE bird SET nest_id =%s,location_id=%s WHERE id=%s"
    try:
        bind = (nest_id, row["location_id"], bird_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    log_bird_event(bird_id, status="moved", user=result['rest']['user'],
                   location_id=row["location_id"], nest_id=nest_id)
    g.db.commit()
    return generate_response(result)


@app.route('/bird/alive/<string:bird_id>', methods=['OPTIONS', 'POST'])
def alive_bird(bird_id):
    '''
    Mark a bird as alive
    Update a bird's alive flag and death date.
    ---
    tags:
      - Bird
    parameters:
      - in: path
        name: bird_id
        schema:
          type: string
        required: true
        description: bird ID
    '''
    result = initialize_result()
    if not check_permission(result["rest"]["user"], ["admin"]):
        raise InvalidUsage("You don't have permission to report a bird as alive")
    result["rest"]["row_count"] = 0
    sql = "UPDATE bird SET alive=1,death_date=NULL WHERE id=%s"
    try:
        bind = (bird_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    g.db.commit()
    return generate_response(result)


@app.route('/bird/claim/<string:bird_id>', methods=['OPTIONS', 'POST'])
def claim_bird(bird_id):
    '''
    Claim a bird
    Set a bird's user_id to the current user's ID.
    ---
    tags:
      - Bird
    parameters:
      - in: path
        name: bird_id
        schema:
          type: string
        required: true
        description: bird ID
    '''
    result = initialize_result()
    if not check_permission(result["rest"]["user"], ["admin", "edit"]):
        raise InvalidUsage("You don't have permission to claim a bird")
    result["rest"]["row_count"] = 0
    sql = "UPDATE bird SET user_id=(SELECT id FROM user WHERE name=%s) WHERE id=%s"
    try:
        bind = (result["rest"]["user"], bird_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    log_bird_event(bird_id, status="claimed", user=result['rest']['user'], location_id=None)
    g.db.commit()
    return generate_response(result)


@app.route('/bird/dead/<string:bird_id>', methods=['OPTIONS', 'POST'])
def dead_bird(bird_id):
    '''
    Mark a bird as dead
    Update a bird's alive flag, death date, and user_id.
    ---
    tags:
      - Bird
    parameters:
      - in: path
        name: bird_id
        schema:
          type: string
        required: true
        description: bird ID
    '''
    result = initialize_result()
    if not check_permission(result["rest"]["user"], ["admin", "edit"]):
        raise InvalidUsage("You don't have permission to report a bird as dead")
    result["rest"]["row_count"] = 0
    sql = "UPDATE bird SET alive=0,death_date=CURRENT_TIMESTAMP(),user_id=NULL WHERE id=%s"
    try:
        bind = (bird_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    log_bird_event(bird_id, status="died", user=result['rest']['user'], location_id=None,
                   terminal=1)
    g.db.commit()
    return generate_response(result)


@app.route('/bird/unclaim/<string:bird_id>', methods=['OPTIONS', 'POST'])
def unclaim_bird(bird_id):
    '''
    Unclaim a bird
    Set a bird's user_id to NULL.
    ---
    tags:
      - Bird
    parameters:
      - in: path
        name: bird_id
        schema:
          type: string
        required: true
        description: bird ID
    '''
    result = initialize_result()
    if not check_permission(result['rest']['user'], ['admin', 'edit']):
        raise InvalidUsage("You don't have permission to unclaim a bird")
    result["rest"]["row_count"] = 0
    sql = "UPDATE bird SET user_id=NULL WHERE id=%s"
    try:
        bind = (bird_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    log_bird_event(bird_id, status="unclaimed", user=result['rest']['user'], location_id=None)
    g.db.commit()
    return generate_response(result)


@app.route('/registerbird', methods=['OPTIONS', 'POST'])
def register_bird():
    '''
    Register a bird
    Register a new bird
    ---
    tags:
      - Bird
    parameters:
      - in: query
        name: nest_id
        schema:
          type: string
        required: true
        description: nest ID
      - in: query
        name: number1
        schema:
          type: string
        required: true
        description: band1 number
      - in: query
        name: number2
        schema:
          type: string
        required: true
        description: band2 number
      - in: query
        name: start_date
        schema:
          type: string
        required: true
        description: hatch early date
      - in: query
        name: stop_date
        schema:
          type: string
        required: true
        description: hatch late date
      - in: query
        name: sex
        schema:
          type: string
        required: true
        description: sex (M or F)
      - in: query
        name: claim
        schema:
          type: string
        required: true
        description: claim the new bird (0 or 1)
      - in: query
        name: notes
        schema:
          type: string
        required: false
        description: notes
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    if not check_permission(result['rest']['user'], ['admin', 'edit']):
        raise InvalidUsage("You don't have permission to register a bird")
    check_missing_parms(ipd, ["nest_id", "number1", "number2", "start_date",
                              "stop_date", "sex", "claim"])
    result['rest']['row_count'] = 0
    name, band, nest, loc_id = get_banding_and_location(ipd)
    # User
    user_id = None
    if ipd["claim"]:
        try:
            g.c.execute("SELECT id FROM user WHERE name=%s", (result['rest']['user'],))
            row = g.c.fetchone()
            user_id = row["id"]
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
    result['rest']['row_count'] = 0
    if not ipd["notes"]:
        ipd["notes"] = None
    sql = "INSERT INTO bird (species_id,name,band,nest_id,location_id,user_id,sex,notes," \
          + "alive,hatch_early,hatch_late) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s)"
    try:
        bind = (1, name, band, ipd["nest_id"], loc_id, user_id, ipd["sex"], ipd['notes'],
                ipd["start_date"], ipd["stop_date"])
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
        result["rest"]["bird_id"] = g.c.lastrowid
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    sql = "INSERT INTO bird_relationship (type,bird_id,sire_id,damsel_id,relationship_start) " \
          + "VALUES ('genetic',%s,%s,%s,%s)"
    try:
        bind = (result["rest"]["bird_id"], nest["sire_id"], nest["damsel_id"], ipd["start_date"])
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
        result["rest"]["relationship_id"] = g.c.lastrowid
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    log_bird_event(result["rest"]["bird_id"], user=result['rest']['user'], location_id=loc_id)
    if ipd["claim"]:
        log_bird_event(result["rest"]["bird_id"], status="claimed", user=result['rest']['user'],
                       location_id=loc_id)
    g.db.commit()
    return generate_response(result)


# *****************************************************************************
# * Clutch endpoints                                                          *
# *****************************************************************************

@app.route('/registerclutch', methods=['OPTIONS', 'POST'])
def register_clutch():
    '''
    Register a clutch
    Register a new clutch
    ---
    tags:
      - Clutch
    parameters:
      - in: query
        name: nest_id
        schema:
          type: string
        required: true
        description: nest ID
      - in: query
        name: start_date
        schema:
          type: string
        required: true
        description: hatch early date
      - in: query
        name: notes
        schema:
          type: string
        required: false
        description: notes
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    if not check_permission(result['rest']['user'], ['admin', 'edit']):
        raise InvalidUsage("You don't have permission to register a clutch")
    check_missing_parms(ipd, ["nest_id", "start_date"])
    nest = get_record(ipd['nest_id'], "nest")
    name = "_".join([ipd['start_date'].replace("-", ""), nest['name']])
    result['rest']['row_count'] = 0
    result['rest']['row_count'] = 0
    sql = "INSERT INTO clutch (name, nest_id, notes, clutch_start) VALUES (%s,%s,%s,%s)"
    try:
        bind = (name, ipd["nest_id"], ipd['notes'], ipd["start_date"])
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
        result["rest"]["clutch_id"] = g.c.lastrowid
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    g.db.commit()
    return generate_response(result)


@app.route('/clutch/nest/<string:clutch_id>/<string:nest_id>', methods=['OPTIONS', 'POST'])
def clutch_nest(clutch_id, nest_id):
    '''
    Move a clutch to a new nest
    Update a clutch's nest.
    ---
    tags:
      - Clutch
    parameters:
      - in: path
        name: clutch_id
        schema:
          type: string
        required: true
        description: clutch ID
      - in: path
        name: nest_id
        schema:
          type: string
        required: true
        description: nest ID
    '''
    result = initialize_result()
    if not check_permission(result["rest"]["user"], ["admin"]):
        raise InvalidUsage("You don't have permission to change a clutch's nest")
    result["rest"]["row_count"] = 0
    sql = "UPDATE clutch SET nest_id =%s WHERE id=%s"
    try:
        bind = (nest_id, clutch_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    try:
        g.c.execute("UPDATE nest SET fostering=1 WHERE id=%s", (nest_id))
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    g.db.commit()
    return generate_response(result)


# *****************************************************************************
# * Nest endpoints                                                            *
# *****************************************************************************

@app.route('/nest/location/<string:nest_id>/<string:location_id>', methods=['OPTIONS', 'POST'])
def nest_location(nest_id, location_id):
    '''
    Move all birds in a nest to a new location
    Update birds' location.
    ---
    tags:
      - Nest
    parameters:
      - in: path
        name: nest_id
        schema:
          type: string
        required: true
        description: nest ID
      - in: path
        name: location_id
        schema:
          type: string
        required: true
        description: location ID
    '''
    result = initialize_result()
    if not check_permission(result["rest"]["user"], ["admin"]):
        raise InvalidUsage("You don't have permission to change a bird's location")
    result["rest"]["row_count"] = 0
    sql = "UPDATE bird b1,(SELECT id FROM bird WHERE nest_id=%s) b2 " \
          + "SET location_id =%s WHERE b1.id=b2.id"
    try:
        bind = (nest_id, location_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    sql = "SELECT id FROM bird WHERE nest_id=%s"
    try:
        bind = (nest_id)
        g.c.execute(sql, bind)
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    for row in rows:
        log_bird_event(row["id"], status="moved", user=result['rest']['user'],
                       location_id=location_id)
    g.db.commit()
    return generate_response(result)


@app.route('/nest/nest/<string:nest_id>/<string:new_nest_id>', methods=['OPTIONS', 'POST'])
def nest_nest(nest_id, new_nest_id):
    '''
    Move all birds in a nest to a new nest
    Update birds' nest
    ---
    tags:
      - Nest
    parameters:
      - in: path
        name: nest_id
        schema:
          type: string
        required: true
        description: nest ID
      - in: path
        name: new_nest_id
        schema:
          type: string
        required: true
        description: new nest ID
    '''
    result = initialize_result()
    if not check_permission(result["rest"]["user"], ["admin"]):
        raise InvalidUsage("You don't have permission to change a bird's nest")
    result["rest"]["row_count"] = 0
    # Get new location
    try:
        bind = (new_nest_id)
        g.c.execute("SELECT location_id FROM bird WHERE nest_id=%s LIMIT 1", bind)
        row = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    location_id = row["location_id"]
    # Get all birds in current nest
    sql = "SELECT id FROM bird WHERE nest_id=%s"
    try:
        bind = (nest_id)
        g.c.execute(sql, bind)
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    # Update nest
    sql = "UPDATE bird b1,(SELECT id FROM bird WHERE nest_id=%s) b2 " \
          + "SET nest_id =%s WHERE b1.id=b2.id"
    try:
        bind = (nest_id, new_nest_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    for row in rows:
        log_bird_event(row["id"], status="moved", user=result['rest']['user'],
                       location_id=location_id, nest_id=new_nest_id)
    # Remove birds from old nest
    sql = "UPDATE nest SET sire_id=NULL,damsel_id=NULL,female1_id=NULL,female2_id=NULL," \
          + "female3_id=NULL,breeding=0,fostering=0,tutoring=0,active=0 where id=%s"
    try:
        bind = (nest_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    g.db.commit()
    return generate_response(result)


@app.route('/registernest', methods=['OPTIONS', 'POST'])
def register_nest():
    '''
    Register a nest
    Register a new nest
    ---
    tags:
      - Nest
    parameters:
      - in: query
        name: color1
        schema:
          type: string
        required: true
        description: upper band color
      - in: query
        name: color2
        schema:
          type: string
        required: true
        description: lower band color
      - in: query
        name: start_date
        schema:
          type: string
        required: true
        description: start date
      - in: query
        name: notes
        schema:
          type: string
        required: false
        description: notes
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    if not check_permission(result['rest']['user'], ['admin', 'edit']):
        raise InvalidUsage("You don't have permission to register a nest")
    check_missing_parms(ipd, ["start_date", "color1", "color2", "location"])
    result['rest']['row_count'] = 0
    name, band = get_banding(ipd)
    result['rest']['row_count'] = 0
    insert_type = "breeding" if ("sire_id" in ipd) else "fostering"
    if insert_type == "fostering":
        if not ipd["female2_id"]:
            ipd["female2_id"] = None
        if not ipd["female3_id"]:
            ipd["female3_id"] = None
        sql = "INSERT INTO nest (name,band,female1_id,female2_id,female3_id,fostering," \
              + "notes,create_date) VALUES (%s,%s,%s,%s,%s,1,%s,%s)"
        bind = (name, band, ipd["female1_id"], ipd["female2_id"], ipd["female3_id"],
                ipd['notes'], ipd["start_date"])
    else:
        sql = "INSERT INTO nest (name,band,sire_id,damsel_id,breeding,notes,create_date) " \
              + "VALUES (%s,%s,%s,%s,1,%s,%s)"
        bind = (name, band, ipd["sire_id"], ipd["damsel_id"], ipd['notes'], ipd["start_date"])
    try:
        print(sql % bind)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
        result["rest"]["nest_id"] = g.c.lastrowid
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    # Assign birds to new nest
    if insert_type == "breeding":
        birds_to_assign = [ipd["sire_id"], ipd["damsel_id"]]
    else:
        birds_to_assign = []
        for idx in range(1, 4):
            if ipd["female" + str(idx) + "_id"]:
                birds_to_assign.append(ipd["female" + str(idx) + "_id"])
    for bird_id in birds_to_assign:
        try:
            g.c.execute("UPDATE bird SET nest_id=%s,location_id=%s WHERE id=%s",
                        (result["rest"]["nest_id"], ipd["location"], bird_id))
            result["rest"]["row_count"] += g.c.rowcount
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
    g.db.commit()
    return generate_response(result)


# *****************************************************************************
# * Species endpoints                                                         *
# *****************************************************************************

@app.route('/species', methods=['GET'])
def get_species_info():
    '''
    Get dpecies information (with filtering)
    Return a list of species (rows from the cv table). The caller can filter on
     any of the columns in the cv table. Inequalities (!=) and some relational
     operations (&lt;= and &gt;=) are supported. Wildcards are supported
     (use "*"). Specific columns from the cv table can be returned with the
     _columns key. The returned list may be ordered by specifying a column with
     the _sort key. In both cases, multiple columns would be separated by a
     comma.
    ---
    tags:
      - Species
    responses:
      200:
          description: List of information for one or more CVs
      404:
          description: CVs not found
    '''
    result = initialize_result()
    execute_sql(result, 'SELECT * FROM species', 'data')
    return generate_response(result)


# *****************************************************************************
# * User endpoints                                                            *
# *****************************************************************************

@app.route('/addlocation', methods=['OPTIONS', 'POST'])
def add_location(): # pragma: no cover
    '''
    Add location
    ---
    tags:
      - Location
    parameters:
      - in: query
        name: display_name
        schema:
          type: string
        required: true
        description: Display name
      - in: query
        name: definition
        schema:
          type: string
        required: true
        description: Definition
    responses:
      200:
          description: User added
      400:
          description: Missing or incorrect arguments
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    check_missing_parms(ipd, ['display_name'])
    if not check_permission(result['rest']['user'], ['admin', 'edit']):
        raise InvalidUsage("You don't have permission to add a location")
    name = ipd['display_name'].lower().replace(" ", "_")
    try:
        bind = ("location", name, ipd['definition'], ipd['display_name'], 1, "text")
        g.c.execute(WRITE['INSERT_CVTERM'], bind)
    except pymysql.IntegrityError:
        raise InvalidUsage(f"Location {ipd['display_name']} is already in the database") \
              from pymysql.IntegrityError
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    result['rest']['row_count'] = g.c.rowcount
    result['rest']['inserted_id'] = g.c.lastrowid
    result['rest']['sql_statement'] = g.c.mogrify(WRITE['INSERT_CVTERM'], bind)
    print("Added location " + ipd['display_name'])
    g.db.commit()
    return generate_response(result)


# *****************************************************************************
# * User endpoints                                                            *
# *****************************************************************************

@app.route('/adduser', methods=['OPTIONS', 'POST'])
def add_user(): # pragma: no cover
    '''
    Add user
    ---
    tags:
      - User
    parameters:
      - in: query
        name: name
        schema:
          type: string
        required: true
        description: User name (gmail address)
      - in: query
        name: janelia_id
        schema:
          type: string
        required: true
        description: Janelia ID
      - in: query
        name: first
        schema:
          type: string
        required: true
        description: First name
      - in: query
        name: last
        schema:
          type: string
        required: true
        description: Last name
      - in: query
        name: email
        schema:
          type: string
        required: true
        description: Preferred email
      - in: query
        name: permissions
        schema:
          type: list
        required: false
        description: List of permissions
    responses:
      200:
          description: User added
      400:
          description: Missing or incorrect arguments
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    if "usertype" in ipd and ipd["usertype"] == "non_hhmi":
        checklist = ['name', 'first', 'last', 'email']
    else:
        checklist = ['name', 'janelia_id']
    check_missing_parms(ipd, checklist)
    if not check_permission(result['rest']['user'], 'admin'):
        raise InvalidUsage("You don't have permission to add a user")
    if "usertype" in ipd and ipd["usertype"] == "non_hhmi":
        work = {"first": ipd["first"], "last": ipd["last"], "email": ipd["email"],
                "organization": "UCSF"}
    else:
        try:
            data = call_responder("config", "config/workday/" + ipd["janelia_id"])
        except Exception as err:
            raise err
        if not data:
            raise InvalidUsage(f"User {ipd['name']} not found in Workday")
        work = data['config']
    try:
        bind = (ipd['name'], work['first'], work['last'],
                ipd['janelia_id'], work['email'], work['organization'])
        g.c.execute(WRITE['INSERT_USER'], bind)
    except pymysql.IntegrityError:
        raise InvalidUsage(f"User {ipd['name']} is already in the database") \
              from pymysql.IntegrityError
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    result['rest']['row_count'] = g.c.rowcount
    result['rest']['inserted_id'] = g.c.lastrowid
    result['rest']['sql_statement'] = g.c.mogrify(WRITE['INSERT_USER'], bind)
    if 'permissions' in ipd and type(ipd['permissions']).__name__ == 'list':
        add_user_permissions(result, ipd['name'], ipd['permissions'])
    print("Added user " + ipd['janelia_id'])
    g.db.commit()
    return generate_response(result)


@app.route('/user_permissions', methods=['OPTIONS', 'POST'])
def add_user_permission(): # pragma: no cover
    '''
    Add user permissions
    ---
    tags:
      - User
    parameters:
      - in: query
        name: name
        schema:
          type: string
        required: true
        description: User name (gmail address)
      - in: query
        name: permissions
        schema:
          type: list
        required: true
        description: List of permissions
    responses:
      200:
          description: User permission(s) added
      400:
          description: Missing or incorrect arguments
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    check_missing_parms(ipd, ['name', 'permissions'])
    if not check_permission(result['rest']['user'], ['admin']):
        raise InvalidUsage("You don't have permission to change user permissions")
    if type(ipd['permissions']).__name__ != 'list':
        raise InvalidUsage('Permissions must be specified as a list')
    result['rest']['row_count'] = 0
    add_user_permissions(result, ipd['name'], ipd['permissions'])
    g.db.commit()
    return generate_response(result)


@app.route('/user_permissions', methods=['OPTIONS', 'DELETE'])
def delete_user_permission(): # pragma: no cover
    '''
    Delete user permissions
    ---
    tags:
      - User
    parameters:
      - in: query
        name: name
        schema:
          type: string
        required: true
        description: User name (gmail address)
      - in: query
        name: permissions
        schema:
          type: list
        required: true
        description: List of permissions
    responses:
      200:
          description: User permission(s) deleted
      400:
          description: Missing or incorrect arguments
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    check_missing_parms(ipd, ['name', 'permissions'])
    if not check_permission(result['rest']['user'], 'admin'):
        raise InvalidUsage("You don't have permission to delete user permissions")
    if type(ipd['permissions']).__name__ != 'list':
        raise InvalidUsage('Permissions must be specified as a list')
    result['rest']['row_count'] = 0
    user_id = get_user_id(ipd['name'])
    for permission in ipd['permissions']:
        sql = "DELETE FROM user_permission WHERE user_id=%s AND permission_id=" \
              + "getCvTermId('permission','%s','')"
        try:
            g.c.execute(sql % (user_id, permission))
            result['rest']['row_count'] += g.c.rowcount
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
    g.db.commit()
    return generate_response(result)


# *****************************************************************************


if __name__ == '__main__':
    app.run(ssl_context="adhoc", debug=True)
