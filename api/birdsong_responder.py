''' birdsong_responder.py
    UI and REST API for the birdsong database
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
import numpy as np
import pymysql.cursors
import pymysql.err
import requests
from oauthlib.oauth2 import WebApplicationClient  # pylint: disable=E0401
from werkzeug.middleware.proxy_fix import ProxyFix


# pylint: disable=W0401, W0614
import birdsong_utilities
from birdsong_utilities import *

# pylint: disable=C0302, C0103, W0703, R0903

class CustomJSONEncoder(JSONEncoder):
    ''' Define a custom JSON encoder
    '''
    def default(self, o):   # pylint: disable=E0202, W0221
        try:
            if isinstance(o, datetime):
                return o.strftime("%a, %-d %b %Y %H:%M:%S")
            if isinstance(o, timedelta):
                seconds = o.total_seconds()
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                seconds = seconds % 60
                return f"{hours:02d}:{minutes:02d}:{seconds:.02f}"
            iterable = iter(o)
        except TypeError:
            pass
        else:
            return list(iterable)
        return JSONEncoder.default(self, o)

class WsgiFlaskPrefixFix(ProxyFix):
    def __init__(self, flaskapp):
        super().__init__(flaskapp.wsgi_app, x_host=1, x_port=1, x_prefix=1)
        self.flaskapp = flaskapp

    def __call__(self, environ, start_response):
        prefix = environ.get('HTTP_X_SCRIPT_NAME') or environ.get('HTTP_X_FORWARDED_PREFIX')
        if prefix:
            self.flaskapp.config['APPLICATION_ROOT'] = environ['SCRIPT_NAME'] = prefix
            environ['PATH_INFO'] = environ['PATH_INFO'][len(prefix):]
        return super().__call__(environ, start_response)


__version__ = "0.1.0"
app = Flask(__name__, template_folder="templates")
app.json_encoder = CustomJSONEncoder
app.config.from_pyfile("config.cfg")
# Override Flask's usual behavior of sorting keys (interferes with prioritization)
app.config["JSON_SORT_KEYS"] = False
CORS(app, supports_credentials=True)
application = WsgiFlaskPrefixFix(app) #declared wsgi callable

def define_views():
    ''' Populate app.config['VIEWS']
    '''
    rows = CURSOR.fetchall()
    for row in rows:
        table = list(row.values())[0]
        if table.endswith("_vw"):
            app.config["VIEWS"].append(table)

try:
    CONN = pymysql.connect(host=app.config["MYSQL_DATABASE_HOST"],
                           user=app.config["MYSQL_DATABASE_USER"],
                           password=app.config["MYSQL_DATABASE_PASSWORD"],
                           db=app.config["MYSQL_DATABASE_DB"],
                           cursorclass=pymysql.cursors.DictCursor)
    CURSOR = CONN.cursor()
    CURSOR.execute("SHOW TABLES")
    define_views()
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
IDCOLUMN = False
START_TIME = ''


# *****************************************************************************
# * Flask                                                                     *
# *****************************************************************************

@app.before_request
def before_request():
    ''' Set transaction start time and increment counters.
        If needed, initilize global variables.
    '''
    # pylint: disable=W0603, E0237
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

@app.errorhandler(InvalidUsage)
def handle_invalid_usage(error):
    ''' Error handler
        Keyword arguments:
          error: error object
    '''
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response


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
            try:
                if not get_user_id(authuser):
                    raise InvalidUsage(f"User {authuser} is not known to the Birdsong system")
            except Exception as err:
                raise InvalidUsage(sql_error(err), 500) from err
            app.config["AUTHORIZED"][token] = authuser
        result["rest"]["user"] = authuser
        if authuser not in app.config["USERS"]:
            urec = get_user_by_name(authuser)
            app.config["USERS"][authuser] = f"{urec['last']}, {urec['first']}"
        if app.config["USERS"][authuser] in app.config["API_USERS"]:
            app.config["API_USERS"][app.config["USERS"][authuser]] += 1
        else:
            app.config["API_USERS"][app.config["USERS"][authuser]] = 1
    elif request.method in ["DELETE", "POST"] or request.endpoint in app.config["REQUIRE_AUTH"]:
        raise InvalidUsage('You must authorize to use this endpoint', 401)
    if app.config["LAST_TRANSACTION"] and time() - app.config["LAST_TRANSACTION"] \
       >= app.config["RECONNECT_SECONDS"]:
        print(f"Seconds since last transaction: {time() - app.config['LAST_TRANSACTION']}")
        g.db.ping()
    app.config["LAST_TRANSACTION"] = time()
    return result


def generate_response(result):
    ''' Generate a response to a request
        Keyword arguments:
          result: result dictionary
        Returns:
          JSON response
    '''
    result["rest"]["elapsed_time"] = str(timedelta(seconds=time() - START_TIME))
    return jsonify(**result)


def get_bird_tutors(bird):
    ''' Get a bird's tutors
        Keyword arguments:
          bird: bird name
        Returns: Current tutor, tutor records
    '''
    try:
        g.c.execute("SELECT type,IFNULL(bird_tutor,computer_tutor) AS tutor"
                    + ",create_date FROM bird_tutor_vw WHERE bird=%s ORDER BY create_date", (bird,))
        rows = g.c.fetchall()
    except Exception as err:
        raise err
    current = None
    html = ""
    if rows:
        header = ['Tutor', 'Date']
        html = f"<br><br><h3>Tutors ({len(rows)})</h3>"
        html += '''
        <table id="tutors" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        html += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr>' + ''.join("<td>%s</td>")*(len(header)) + '</tr>'
        for row in rows:
            tutor = row["tutor"]
            if row["type"] == "bird":
                tutor = f"<a href='/bird/{tutor}'>{tutor}</a>"
            outcol = [tutor, row["create_date"]]
            html += template % tuple(outcol)
            if not current:
                current = tutor
        html += "</tbody></table>"
    return current, html


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
        raise err
    events = ""
    if rows:
        header = ['Date', 'Status', 'Nest', 'Location', 'User', 'Notes', 'Terminal']
        events = f"<br><br><h3>Events ({len(rows)})</h3>"
        events += '''
        <table id="events" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        events += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr>' + ''.join("<td>%s</td>")*(len(header)-1) \
                   + '<td style="text-align: center">%s</td></tr>'
        for row in rows:
            for col in ("location", "nest", "notes", "username"):
                if not row[col]:
                    row[col] = ""
            terminal = apply_color("YES", "red", row["terminal"], "lime", "NO")
            outcol = [row["event_date"], row["status"], row["nest"], row["location"],
                      row["username"], row["notes"], terminal]
            events += template % tuple(outcol)
        events += "</tbody></table>"
    return events


def get_bird_sessions(bird):
    ''' Get a bird's experimental; sessions
        Keyword arguments:
          bird: bird record
        Returns: HTML
    '''
    bname = bird["name"]
    sessions = ""
    try:
        g.c.execute("SELECT cv,type FROM session_vw WHERE bird=%s ORDER BY 1,2", bname)
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    if not rows:
        return ""
    sessions = """
    <h3>Experimental sessions</h3>
    <table id='sessions' class="property">
    <tbody>
    """
    try:
        g.c.execute("SELECT * FROM score_vw WHERE bird=%s ORDER BY cv,type", bname)
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    if not rows:
        return ""
    head = False
    for row in rows:
        if not head:
            sessions += f"<tr><td><h5>{row['cv']}</h5></td></tr>"
            head = True
        sessions += f"<tr><td>&nbsp;&nbsp;{row['type']}:</td><td>{row['value']}</td></tr>"
    # Genotype
    sessions += """
    <tbody>
    </table>
    """
    try:
        g.c.execute("SELECT state,COUNT(1) AS count FROM state_vw WHERE "
                    + "bird=%s GROUP BY 1 ORDER BY 2 DESC", bname)
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    sessions += "<table id='state' class='state'><thead><tr>"
    for row in rows:
        sessions += f"<th>{row['state']}</th>"
    sessions += "</tr><tbody><tr>"
    for row in rows:
        sessions += f"<td>{row['count']}</td>"
    sessions += "</tr></tbody></table>"
    # Comparisons
    try:
        g.c.execute("SELECT COUNT(1) AS cnt FROM bird_comparison_vw WHERE "
                    + "bird1=%s", bname)
        row = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    if row and row["cnt"]:
        sessions += '<br><button type="button" ' \
                    + 'class="btn btn-outline-info and-all-other-classes">' \
                    + f"<a href='/comparison/{bname}' " \
                    + "style='color:inherit'>View comparisons</a></button>"
    return sessions


def get_bird_nest_info(bname):
    ''' Given a bird name, return bird and nest records
        Keyword arguments:
          bname: bird name
        Returns: bird and nest records
    '''
    try:
        bird = get_record(bname, "bird")
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    if not bird:
        return None, None
    try:
        g.c.execute("SELECT * FROM bird WHERE name=%s", (bname,))
        nest = g.c.fetchone()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    return bird, nest


def populate_bird_locations(bprops, bird):
    ''' Populate bird location data (including clutch and nest)
        Keyword arguments:
          bprops: bird property list
          bird: bird record
        Returns: additionalinformation in bprops list
    '''
    if bird["clutch"]:
        bprops.append(["Clutch:", f"<a href='/clutch/{bird['clutch']}'>{bird['clutch']}</a>"])
    else:
        bprops.append(["Clutch:", "None"])
    if bird["nest"]:
        bprops.append(["Nest:", bird["nest_location"] \
                      + f" <a href='/nest/{bird['nest']}'>{bird['nest']}</a>"])
    else:
        bprops.append(["Nest:", "Outside vendor"])
    if bird["vendor"]:
        bprops.append(["Vendor:", bird["vendor"]])
    bprops.append(["Location:", bird['location']])
    if bird["birth_nest"]:
        bprops.append(["Birth nest:", bird["birth_nest_location"] \
                       + f" <a href='/nest/{bird['nest']}'>{bird['nest']}</a>"])
    bprops.append(["Claimed by:", apply_color(bird["username"] or "UNCLAIMED", "gold",
                                              (not bird["user"]))])


def populate_bird_properties(bprops, bird, user, permissions, current):
    ''' Populate bird properties (minus the bird_property table)
        Keyword arguments:
          bprops: bird property list
          bird: bird record
          user: user
          permissions: user permissions
          current: current tutor
        Returns: additionalinformation in bprops list
    '''
    populate_bird_locations(bprops, bird)
    birdsex = bird["sex"]
    if (birdsex == "U" or not birdsex) and bird["alive"] and \
       (set(['admin', 'manager']).intersection(permissions) or user == bird["user"]):
        birdsex = generate_sex_pulldown(bird["id"])
    bprops.append(["Sex:", birdsex])
    if bird["sire"]:
        bprops.append(["Sire:", f"<a href='/bird/{bird['sire']}'>{bird['sire']}</a>"])
    else:
        bprops.append(["Sire:", "None"])
    if bird["damsel"]:
        bprops.append(["Damsel:", f"<a href='/bird/{bird['damsel']}'>{bird['damsel']}</a>"])
    else:
        bprops.append(["Damsel:", "None"])
    early = str(bird["hatch_early"]).split(' ', maxsplit=1)[0]
    late = str(bird["hatch_late"]).split(' ', maxsplit=1)[0]
    bprops.append(["Hatch date:", " - ".join([early, late])])
    alive = apply_color("YES", "lime", bird["alive"], "red", "NO")
    alive += f" (Current age: {bird['current_age']})" if bird["alive"] \
             else f" (Death date: {bird['death_date']})"
    bprops.append(["Alive:", alive])
    if current:
        bprops.append(["Tutor:", current])
    birdnotes = bird["notes"]
    if (not birdnotes) and bird["alive"] and \
       set(['admin', 'edit', 'manager']).intersection(permissions) and user == bird["user"]:
        birdnotes = generate_notes_field(bird["id"])
    bprops.append(["Notes:", birdnotes])


def get_bird_properties(bird, user, permissions):
    ''' Get a bird's properties
        Keyword arguments:
          bird: bird record
          user: user
          permissions: user permissions
        Returns: additionalinformation in bprops list
    '''
    bprops = []
    parent = ""
    if bird["sex"]:
        try:
            g.c.execute(READ["ISPARENT"], (bird["name"],))
            rows = g.c.fetchall()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
        if rows:
            parent = f" ({'sire' if bird['sex'] == 'M' else 'damsel'})"
    bprops.append(["Band:", bird["band"]])
    current, tutor_html = get_bird_tutors(bird["name"])
    populate_bird_properties(bprops, bird, user, permissions, current)
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
    try:
        return bprops, tutor_html, get_bird_events(bird["name"])
    except Exception as err:
        raise err


def set_claim_notes(ipd, result):
    ''' Set claim and notes info for a bird
        Keyword arguments:
          ipd: request payload
          result: result dictionary
        Returns:
          Values added to ipd and result dicts
    '''
    if ("vendor_id" not in ipd) or (not ipd["vendor_id"]):
        ipd["vendor_id"] = None
    result['rest']['row_count'] = 0
    # Notes
    if ("notes" not in ipd) or (not ipd["notes"]):
        ipd["notes"] = ''
    result["rest"]["bird_id"] = []
    result["rest"]["relationship_id"] = []


def get_birds_in_clutch_or_nest(rec, dnd, ttype):
    ''' Get the birds in a nest
        Keyword arguments:
          rec: clutch or nest record
          dnd: birds to not display
          ttype: table type
        Returns:
          Birds in nest
    '''
    try:
        g.c.execute("SELECT * FROM bird_vw WHERE " + ttype + "=%s ORDER BY 1", (rec["name"],))
        irows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    rows = []
    alive = 0
    for row in irows:
        if row["name"] in dnd:
            continue
        if row["alive"]:
            alive += 1
        rows.append(row)
    if rows:
        header = ['Name', 'Band', 'Claimed by', 'Location', 'Sex', 'Notes',
                  'Current age', 'Alive']
        birds = f"<h3><div id='tabletitle'>Additional birds from nest ({alive})</div></h3>" \
                if ttype == "nest" else f"<h3>Birds from clutch ({len(rows)})</h3>"
        if ttype == "nest":
            birds += generate_dead_or_alive(True) + "<br>"
        birds += '''
        <table id="birds" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        birds += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr class="%s">' + ''.join("<td>%s</td>")*len(header) + "</tr>"
        for row in rows:
            for col in ("notes", "sex", "username"):
                if not row[col]:
                    row[col] = ""
            rclass = 'alive' if row['alive'] else 'dead'
            bird = f"<a href='/bird/{row['name']}'>{row['name']}</a>"
            bird = colorband(row["name"], bird)
            if not row['alive']:
                row['current_age'] = '-'
            alive = apply_color("YES", "lime", row["alive"], "red", "NO")
            outcol = [rclass, bird, row['band'], row["username"], row['location'], row['sex'],
                      row['notes'], row['current_age'], alive]
            birds += template % tuple(outcol)
        birds += "</tbody></table>"
    else:
        birds = f"There are no additional birds in this {ttype}."
    return birds


def get_clutch_properties(clutch):
    ''' Get a clutch's properties
        Keyword arguments:
          clutch: cliutch record
          birds: birds in clutch
    '''
    cprops = []
    nest = f"<a href='/nest/{clutch['nest']}'>{clutch['nest']}</a>"
    cprops.append(["Nest:", nest])
    cprops.append(["Clutch early:", strip_time(clutch["clutch_early"])])
    cprops.append(["Clutch late:", strip_time(clutch["clutch_late"])])
    cprops.append(["Notes:", clutch["notes"]])
    # Bird list
    birds = get_birds_in_clutch_or_nest(clutch, [], "clutch")
    return cprops, birds


def get_nest_properties(nest):
    ''' Get a nest's properties
        Keyword arguments:
          nest: nest record
        Returns:
          Properties, birds, and clutches
    '''
    nprops = []
    nprops.append(["Band:", nest["band"]])
    nprops.append(["Location:", nest["location"]])
    if (nest["sire"] and nest["damsel"]):
        nprops.append(["Sire:", f"<a href='/bird/{nest['sire']}'>{nest['sire']}</a>"])
        nprops.append(["Damsel:", f"<a href='/bird/{nest['damsel']}'>{nest['damsel']}</a>"])
        dnd = [nest["sire"], nest["damsel"]]
    else:
        dnd = []
        for idx in range(1, 4):
            if app.config['DEBUG']:
                print(nest["female" + str(idx)])
            fnest = nest["female" + str(idx)]
            if fnest:
                nprops.append(["Female " + str(idx), f"<a href='/bird/{fnest}'>{fnest}</a>"])
                dnd.append(fnest)
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
    return nprops, get_birds_in_clutch_or_nest(nest, dnd, "nest"), \
           get_clutches_in_nest(nest["name"])


def get_nest_events(nest):
    ''' Get a nest's events
        Keyword arguments:
          nest: nest name
        Returns: Events records
    '''
    try:
        g.c.execute("SELECT * FROM nest_event_vw WHERE name=%s ORDER BY event_date", (nest,))
        rows = g.c.fetchall()
    except Exception as err:
        raise err
    events = ""
    if rows:
        header = ['Date', 'Status', 'User', 'Notes']
        events = f"<br><br><h3>Events ({len(rows)})</h3>"
        events += '''
        <table id="events" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        events += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr>' + ''.join("<td>%s</td>")*(len(header)-1) \
                   + '<td style="text-align: center">%s</td></tr>'
        for row in rows:
            for col in ("notes", "username"):
                if not row[col]:
                    row[col] = ""
            outcol = [row["event_date"], row["status"],
                      row["username"], row["notes"]]
            events += template % tuple(outcol)
        events += "</tbody></table>"
    return events


def add_user_permissions(result, user, permissions):
    ''' Add permissions for an existing user
        Keyword arguments:
          result: result dictionary
          user: user
          permissions: list of permissions
    '''
    try:
        user_id = get_user_id(user)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    for permission in permissions:
        try:
            bind = (user_id, permission,)
            g.c.execute(WRITE["INSERT_UPERM"] % bind)
            result["rest"]["row_count"] += g.c.rowcount
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err


def generate_bird_event(bid):
    ''' Generate a bird event input box
        Keyword arguments:
          bid: bird ID
        Returns:
          HTML menu
    '''
    rows = get_cv_terms('bird_status')
    pulldown = '<select id="bevent" class="form-control col-sm-5" onchange="fix_event();">' \
               + '<option value="">Select an event...</option>'
    for row in rows:
        pulldown += f"<option value='{row['cv_term']}'>{row['display_name']}</option>"
    pulldown += "</select>"
    controls = '''
               <div class="eventadd" style="padding: 0 0 10px 15px"><h4>Add an event</h4>
               <div class="flexrow">
                 <div class="flexcol">
                   %s
                   <label>Terminal</label>
                   <input type="checkbox" id="terminal">
                 </div>
                 <div class="flexcol">
                   Notes:<input type="text" class="form-control col-sm-11"  id="enotes">
                 </div>
                 <div class="flexcol">
                   <div style="float:left"><div style='float: left'>Event date:</div><div style='float: left;margin-left: 10px;'><input id="edate" width=200></div></div>
                   <script>
                   $('#edate').datepicker({ uiLibrary: 'bootstrap4', format: 'yyyy-mm-dd', value: '%s' });
                   </script>
                 </div>
                 <div class="flexcol" style="margin-left: 20px">
                   <button type="button" class="btn btn-info btn-sm" onclick='add_event(%s);'>Add event</button>
                 </div>
               </div>
               </div>
               '''
    controls = controls % (pulldown, date.today().strftime("%Y-%m-%d"), bid)
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
    try:
        bind = [bird_id, status, get_user_id(user)]
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
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
        values.append("%s")
        bind.append("1")
    if "notes" in kwarg and kwarg["notes"]:
        columns.append("notes")
        values.append("%s")
        bind.append(kwarg["notes"])
    if ("date" in kwarg and kwarg["date"]) and (kwarg["date"] != date.today().strftime("%Y-%m-%d")):
        columns.append("event_date")
        values.append("%s")
        bind.append(kwarg["date"])
    sql = "INSERT INTO bird_event (" + ",".join(columns) + ") VALUES (" + ",".join(values) + ")"
    try:
        if app.config['DEBUG']:
            print(sql % tuple(bind))
        g.c.execute(sql, tuple(bind))
    except Exception as err:
        raise err


def claim_single_bird(bird_id, user, location_id=None):
    ''' Register one bird (no clutch or nest)
        Keyword arguments:
          bid_id: bird ID
          user: user name
          location_id: location ID
        Returns:
          None
    '''
    sql = "UPDATE bird SET user_id=(SELECT id FROM user WHERE name=%s) WHERE id=%s"
    try:
        bind = (user, bird_id)
        g.c.execute(sql, bind)
        log_bird_event(bird_id, status="claimed", user=user, location_id=location_id)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err


def register_single_bird(ipd, result):
    ''' Register one bird (no clutch or nest)
        Keyword arguments:
          ipd: request payload
          result: result dictionary
        Returns:
          Values added in result dict
    '''
    user_id = None
    set_claim_notes(ipd, result)
    birthnest = None
    if "nest_id" in ipd:
        # Get colors
        try:
            g.c.execute("SELECT * FROM nest WHERE id=" + ipd["nest_id"])
            nest = g.c.fetchone()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
        bhash = parse_nest_band(nest["band"])
        ipd["color1"] = bhash['color']['upper']
        ipd["color2"] = bhash['color']['lower']
        ipd["location_id"] = nest["location_id"]
        nrow = get_nest_from_id(ipd["nest_id"])
        if nrow['location'].startswith("N"):
            birthnest = ipd["nest_id"]
    else:
        ipd["nest_id"] = None
    name = ipd["start_date"].replace("-", "") + "_" + ipd["color1"] + ipd["number1"] \
           + ipd["color2"] + ipd["number2"]
    band = parse_bird_name(name)
    band = band['band']
    if 'sex' not in ipd or not ipd['sex']:
        ipd['sex'] = "U"
    if 'notes' not in ipd or not ipd['notes']:
        ipd['notes'] = None
    try:
        bind = (1, name, band, ipd["nest_id"], birthnest, None, ipd["location_id"],
                ipd["vendor_id"], user_id, ipd["notes"], ipd["start_date"],
                ipd["stop_date"], ipd["sex"])
        if app.config['DEBUG']:
            print(WRITE["INSERT_BIRD"] % bind)
        g.c.execute(WRITE["INSERT_BIRD"], bind)
        result["rest"]["row_count"] += g.c.rowcount
        bird_id = g.c.lastrowid
        result["rest"]["bird_id"].append(bird_id)
    except Exception as err:
        raise InvalidUsage("INSERT_BIRD " + sql_error(err), 500) from err
    if ipd["nest_id"]:
        try:
            create_relationship(result, bird_id, nest)
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
    if ipd["claim"]:
        try:
            claim_single_bird(bird_id, result['rest']['user'], ipd["location_id"])
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err


def register_birds(ipd, result):
    ''' Register one or more birds
        Keyword arguments:
          ipd: request payload
          result: result dictionary
        Returns:
          Values added in result dict
    '''
    band, nest, loc_id = get_banding_and_location(ipd)
    # User
    user_id = None
    set_claim_notes(ipd, result)
    birthnest = ipd["nest_id"]
    nrow = get_nest_from_id(ipd["nest_id"])
    if nrow['location'].startswith("N"):
        birthnest = ipd["nest_id"]
    for bird in band:
        try:
            bind = (1, bird["name"], bird["band"], ipd["nest_id"], birthnest,
                    ipd["clutch_id"], loc_id, None, user_id, ipd['notes'],
                    ipd["start_date"], ipd["stop_date"], None)
            if app.config['DEBUG']:
                print(WRITE["INSERT_BIRD"] % bind)
            g.c.execute(WRITE["INSERT_BIRD"], bind)
            result["rest"]["row_count"] += g.c.rowcount
            bird_id = g.c.lastrowid
            result["rest"]["bird_id"].append(bird_id)
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
        create_relationship(result, bird_id, nest)
    try:
        for bird_id in result["rest"]["bird_id"]:
            log_bird_event(bird_id, user=result['rest']['user'], nest_id=ipd["nest_id"],
                           location_id=loc_id)
            if "claim" in ipd and ipd["claim"]:
                log_bird_event(bird_id, status="claimed", user=result['rest']['user'],
                               location_id=loc_id)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err


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
    face = f"<img class='user_image' src='{resp['picture']}' alt='{user}'>"
    permissions = check_permission(user)    
    if user not in app.config["USERS"]:
        urec = get_user_by_name(user)
        app.config["USERS"][user] = f"{urec['last']}, {urec['first']}"
    if app.config["USERS"][user] in app.config["UI_USERS"]:
        app.config["UI_USERS"][app.config["USERS"][user]] += 1
    else:
        app.config["UI_USERS"][app.config["USERS"][user]] = 1
    return user, face, permissions


def get_google_provider_cfg():
    ''' Get the Google discovery configuration
        Keyword arguments:
          None
        Returns:
          Google discovery configuration
    '''
    if app.config["DEBUG"]:
        print(f"Getting Google discovery information from {app.config['GOOGLE_DISCOVERY_URL']}")
    return requests.get(app.config["GOOGLE_DISCOVERY_URL"], timeout=10).json()


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
    headings = ['Birds', 'Clutches', 'Nests', 'Reports', 'Searches', 'Locations',
                'Comparisons', 'Users']
    if "admin" in permissions:
        headings.append("Admin")
    for heading in headings:
        basic = '<li class="nav-item active">' if heading == active else '<li class="nav-item">'
        menuhead = '<a class="nav-link dropdown-toggle" href="#" id="navbarDropdown" ' \
                   + 'role="button" data-toggle="dropdown" aria-haspopup="true" ' \
                   + f"aria-expanded=\"false\">{heading}</a><div class=\"dropdown-menu\" "\
                   + 'aria-labelledby="navbarDropdown">'
        if heading == 'Birds':
            nav += '<li class="nav-item dropdown active">' \
                if heading == active else '<li class="nav-item dropdown">'
            nav += menuhead
            nav += '<a class="dropdown-item" href="/birdlist">Show</a>'
            if set(['admin', 'edit', 'manager']).intersection(permissions):
                nav += '<a class="dropdown-item" href="/newbird">Add</a>'
            nav += '</div></li>'
        elif heading == 'Clutches':
            nav += '<li class="nav-item dropdown active">' \
                if heading == active else '<li class="nav-item dropdown">'
            nav += menuhead
            nav += '<a class="dropdown-item" href="/clutchlist">Show</a>'
            if set(['admin', 'edit', 'manager']).intersection(permissions):
                nav += '<a class="dropdown-item" href="/newclutch">Add</a>'
            nav += '</div></li>'
        elif heading == 'Nests':
            nav += '<li class="nav-item dropdown active">' \
                if heading == active else '<li class="nav-item dropdown">'
            nav += menuhead
            nav += '<a class="dropdown-item" href="/nestlist">Show</a>'
            if set(['admin', 'edit', 'manager']).intersection(permissions):
                nav += '<a class="dropdown-item" href="/newnest">Add</a>'
            nav += '</div></li>'
        elif heading == 'Reports' and set(['admin', 'manager']).intersection(permissions):
            nav += '<li class="nav-item dropdown active">' \
                if heading == active else '<li class="nav-item dropdown">'
            nav += menuhead
            nav += '<a class="dropdown-item" href="/report/bird_user">Birds by user</a>' \
                   + '<a class="dropdown-item" href="/report/bird_alive">Living/dead birds</a>'
            nav += '</div></li>'
        elif heading == 'Comparisons':
            nav += '<li class="nav-item dropdown active">' \
                if heading == active else '<li class="nav-item dropdown">'
            nav += menuhead
            nav += '<a class="dropdown-item" href="/comparisons">Show</a>'
            nav += '</div></li>'
        elif heading == 'Users':
            nav += '<li class="nav-item dropdown active">' \
                if heading == active else '<li class="nav-item dropdown">'
            nav += menuhead
            nav += '<a class="dropdown-item" href="/userlist">Show</a>'
            nav += '</div></li>'
        elif heading == 'Admin':
            nav += '<li class="nav-item dropdown active">' \
                if heading == active else '<li class="nav-item dropdown">'
            nav += menuhead
            nav += '<a class="dropdown-item" href="/fulldbstats">DB statistics</a>'
            nav += '</div></li>'
        else:
            nav += basic
            if heading in ["Clutches", "Searches"]:
                link = ('/' + heading[:-2] + 'list').lower()
            else:
                link = ('/' + heading[:-1] + 'list').lower()
            nav += f"<a class='nav-link' href='{link}'>{heading}</a></li>"
    nav += '</ul></div></nav>'
    return nav


# *****************************************************************************
# * Web content                                                               *
# *****************************************************************************

@app.route("/login")
def login():
    ''' Initial login
    '''
    print("/login")
    # Find out the Google login URL
    google_provider_cfg = get_google_provider_cfg()
    authorization_endpoint = google_provider_cfg["authorization_endpoint"]
    if app.config["DEBUG"]:
        print(f"Getting request URI from {authorization_endpoint}")
    # Use library to construct the request for Google login and provide
    # scopes that let you retrieve user's profile from Google
    redirect_uri = request.base_url + "/callback"
    if app.config["DEBUG"]:
        print(f"redirect_uri is {redirect_uri}")
    request_uri = CLIENT.prepare_request_uri(
        authorization_endpoint,
        redirect_uri=redirect_uri,
        scope=["openid", "email", "profile"]
    )
    if app.config["DEBUG"]:
        print(f"Request URI is {request_uri}")
    return redirect(request_uri)


@app.route("/login/callback")
def login_callback():
    ''' Login callback
    '''
    # Get authorization code Google sent back to you
    code = request.args.get("code")
    # Find out what URL to hit to get tokens that allow you to ask for
    # things on behalf of a user
    if app.config["DEBUG"]:
        print("In /login/callback, call get_google_provider_cfg()")
    google_provider_cfg = get_google_provider_cfg()
    token_endpoint = google_provider_cfg["token_endpoint"]
    if app.config["DEBUG"]:
        print(f"Getting token URL from {token_endpoint}, redirect_url={request.url}")
    # Get tokens using the client ID and secret
    token_url, headers, body = CLIENT.prepare_token_request(
        token_endpoint,
        authorization_response=request.url,
        redirect_url=request.base_url,
        code=code
    )
    if app.config["DEBUG"]:
        print(f"Getting token from {token_url}")
    token_response = requests.post(
        token_url,
        headers=headers,
        data=body, timeout=10,
        auth=(app.config['GOOGLE_CLIENT_ID'], app.config['GOOGLE_CLIENT_SECRET']),
    )
    if app.config["DEBUG"]:
        print(f"Got a {token_response.json()['token_type']}")
    # Parse the token
    CLIENT.parse_request_body_response(json.dumps(token_response.json()))
    # Get the user's profile information
    userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
    uri, headers, body = CLIENT.add_token(userinfo_endpoint)
    if app.config["DEBUG"]:
        print(f"Getting user information from {uri}")
    userinfo_response = requests.get(uri, headers=headers, data=body, timeout=10)
    my_token = token_response.json().get("id_token")
    try:
        rec = get_user_by_name(userinfo_response.json()["email"])
    except Exception:
        pass
    if not rec or not rec['active']:
        return "User is no longer active.", 400
    # Verify the user's email
    if not userinfo_response.json().get("email_verified"):
        return "User email not available or not verified by Google.", 400
    if app.config["DEBUG"]:
        print(f"Logged in as {userinfo_response.json()['email']}")
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
                               title="Unknown user", message=f"User {user} is not registered")
    try:
        rec = get_user_by_name(user)
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    if not rec:
        return render_template("error.html", urlroot=request.url_root,
                               title='User error', message=f"Could not find user {user}")
    uprops = []
    name = []
    for nkey in ['first', 'last']:
        if nkey in rec:
            name.append(rec[nkey])
    uprops.append(['Name:', ' '.join(name)])
    uprops.append(['Janelia ID:', rec['janelia_id']])
    uprops.append(['Organization:', rec['organization']])
    uprops.append(['Permissions:', '<br>'.join(rec['permissions'].split(',')) \
                  if rec['permissions'] else ""])
    token = request.cookies.get(app.config['TOKEN'])
    return render_template('profile.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], user=user,
                           navbar=generate_navbar('Users', permissions), uprops=uprops, token=token)


def add_user_form(permissions):
    ''' Generate add user form HTML
        Keyword arguments:
          permissions: permissions
        Returns:
          HTML
    '''
    adduser = ""
    if set(["admin"]).intersection(permissions):
        adduser = '''
        <br>
        <h3>Add a user</h3>
        <div class="form-group">
          <div class="col-md-5">
            <label for="Input1">Gmail address</label>
            <input type="text" class="form-control" id="user_name" aria-describedby="usernameHelp" placeholder="Enter Google email address" onchange="enable_add();">
            <small id="usernameHelp" class="form-text text-muted">This will be the username.</small>
          </div>
        </div>
        <div id="myRadioGroup">
        HHMI user <input type="radio" name="hhmi_radio" checked="checked" value="hhmi" onclick="change_usertype('hhmi');" />
        &nbsp;&nbsp;&nbsp;
        Non-HHMI <input type="radio" name="hhmi_radio" value="non_hhmi" onclick="change_usertype('non_hhmi');"/>
        <div id="hhmi" class="hhmidesc">
        <div class="form-group">
          <div class="col-md-4">
            <label for="Input2">Janelia ID</label>
            <input type="text" class="form-control" id="janelia_id" aria-describedby="jidHelp" placeholder="Enter Janelia ID">
            <small id="jidHelp" class="form-text text-muted">Enter the Janelia user ID.</small>
          </div>
        </div>
        </div>
        <div id="non_hhmi" class="hhmidesc" style="display: none;">
        <div class="form-group">
          <div class="col-md-4">
            <label for="Input3">First name</label>
            <input type="text" class="form-control" id="first_name" aria-describedby="jidHelp" placeholder="Enter first name">
            <small id="jidHelp" class="form-text text-muted">Enter the user's first name.</small>
          </div>
        </div>
        <div class="form-group">
          <div class="col-md-4">
            <label for="Input3">Last name</label>
            <input type="text" class="form-control" id="last_name" aria-describedby="jidHelp" placeholder="Enter last name">
            <small id="jidHelp" class="form-text text-muted">Enter the user's last name.</small>
          </div>
        </div>
        <div class="form-group">
          <div class="col-md-4">
            <label for="Input3">Preferred email</label>
            <input type="text" class="form-control" id="email" aria-describedby="jidHelp" placeholder="Enter preferred email">
            <small id="jidHelp" class="form-text text-muted">Enter the user's preferred email address.</small>
          </div>
        </div>
        </div>
        <button type="submit" id="sb" class="btn btn-primary btn-sm" onclick="add_user();" href="#" disabled="disabled">Add user</button>
        '''
    return adduser


@app.route('/userlist')
def user_list():
    ''' Show list of users
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message=f"User {user} is not registered")
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
        link = f"<a href='/user/{row['name']}'>{row['name']}</a>"
        if not row['permissions']:
            row['permissions'] = '-'
        else:
            showarr = []
            for perm in row['permissions'].split(','):
                if perm in app.config['PROTOCOLS']:
                    this_perm = f"<span style='color:cyan'>{app.config['PROTOCOLS'][perm]}</span>"
                elif perm in app.config['GROUPS']:
                    this_perm = f"<span style='color:gold'>{perm}</span>"
                else:
                    this_perm = f"<span style='color:orange'>{perm}</span>"
                showarr.append(this_perm)
            row['permissions'] = ', '.join(showarr)
        given_name = ', '.join([row['last'], row['first']])
        if not row['active']:
            given_name = f"<s>{given_name}</s>"
        urows += template % (rclass, given_name, link,
                             row['janelia_id'], row['email'], row['organization'],
                             row['permissions'])
    return render_template('userlist.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], user=user,
                           navbar=generate_navbar('Users', permissions),
                           organizations=organizations, userrows=urows,
                           adduser=add_user_form(permissions))


@app.route('/user/<string:uname>')
def user_config(uname):
    ''' Show user profile
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message=f"User {user} is not registered")
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
                               title='Not found', message=f"User {uname} was not found")
    uprops = []
    uprops.append(['Name:', ' '.join([rec['first'], rec['last']])])
    uprops.append(['Janelia ID:', rec['janelia_id']])
    uprops.append(['Email:', rec['email']])
    uprops.append(['Organization:', rec['organization']])
    ptable = build_permissions_table(user, rec)
    controls = '<br>'
    if set(['admin']).intersection(permissions):
        controls += '''
        <button type="button" class="btn btn-danger btn-sm" onclick='delete_user();'>Delete user</button>
        '''
    return render_template('user.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], user=uname,
                           navbar=generate_navbar('Users', permissions),
                           uprops=uprops, ptable=ptable, controls=controls)


@app.route('/fulldbstats')
def fulldbstats():
    ''' Show database statistics
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message=f"User {user} is not registered")
    if "admin" not in permissions:
        return redirect("/profile")
    try:
        g.c.execute("SELECT engine FROM information_schema.engines WHERE transactions='YES'")
        engine = g.c.fetchone()
        msg = f"Engine: {engine['engine']}<br>"
        g.c.execute("SHOW TABLE STATUS LIKE 'bird'")
        free = g.c.fetchone()
        g.c.execute("SELECT SUM(data_length + index_length) AS size FROM " \
                    + "information_schema.tables WHERE table_schema='birdsong'")
        size = g.c.fetchone()
        dbspace = free["Data_free"] + size["size"]
        msg += f"Used space: {humansize(float(size['size']))} ({size['size']/dbspace*100:.2f}%)<br>" \
              + f"Free space: {humansize(float(free['Data_free']))} " \
              + f"({free['Data_free']/dbspace*100:.2f}%)"
        g.c.execute("SELECT TABLE_NAME,TABLE_ROWS,DATA_LENGTH FROM INFORMATION_SCHEMA.TABLES " \
                    + "WHERE TABLE_SCHEMA='birdsong' AND TABLE_TYPE='BASE TABLE'")
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    template = '<tr><td>%s</td>' + ''.join("<td style='text-align: center'>%s</td>")*2 + "</tr>"
    trows = ""
    for row in rows:
        trows += template % (row['TABLE_NAME'], f"{row['TABLE_ROWS']:,}",
                             humansize(row['DATA_LENGTH']))
    return render_template('dbstats.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], user=user,
                           navbar=generate_navbar('Admin', permissions),
                           size=msg, tablerows=trows)


@app.route('/logout')
def logout():
    ''' Log out
    '''
    if not request.cookies.get(app.config['TOKEN']):
        return render_template("error.html", urlroot=request.url_root,
                               title='You are not logged in',
                               message="You can't log out unless you're logged in")
    response = make_response(render_template('logout.html', urlroot=request.url_root))
    response.set_cookie(app.config['TOKEN'], '', domain='.janelia.org', expires=0)
    #response.set_cookie(app.config['TOKEN'], '', expires=0)
    return response


@app.route('/download/<string:fname>')
def download(fname):
    ''' Downloadable content
    '''
    try:
        return send_file('/tmp/' + fname, download_name=fname)  # pylint: disable=E1123
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title='Download error', message=err)


@app.route('/')
@app.route('/birdlist', methods=['GET', 'POST'])
def show_birds(): # pylint: disable=R0914,R0912,R0915, R0911
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
    sql = bird_summary_query(ipd, user)
    if not sql:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message="Invalid input data")
    if app.config["DEBUG"]:
        print(sql)
    try:
        g.c.execute(sql)
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    controls = generate_which_pulldown()
    birds = generate_birdlist_table(rows, (ipd["which"] != "mine"))
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
def show_bird(bname): # pylint: disable=R0911
    ''' Show information for a bird
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message=f"User {user} is not registered")
    try:
        bird, _ = get_bird_nest_info(bname)
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    if not bird:
        return render_template("error.html", urlroot=request.url_root,
                               title='Not found', message=f"Bird {bname} was not found")
    controls = '<br>'
    # Dialogs for live birds
    if bird["alive"] and set(['admin', 'edit', 'manager']).intersection(permissions):
        # Claim a live bird
        if not bird["user"]:
            controls += '''
            <button type="button" class="btn btn-success btn-sm" onclick='update_bird(%s,"claim");'>Claim bird</button><br>
            '''
            controls = controls % (bird['id'])
        # Create dialogs for nest, location, and event (owner only)
        if set(['admin', 'manager']).intersection(permissions) or bird["user"] == user:
            try:
                # PLUG
                #nestpull = generate_nest_pulldown(["breeding", "fostering", "tutoring"],
                #                                  from_nest=nest['id'])
                #nestpull = generate_nest_pulldown(["fostering", "tutoring"], from_nest=nest['id'])
                #if "No nest" not in nestpull:
                #    controls += "Move bird to new nest" + nestpull
                controls += generate_movement_pulldown(bird['id'], "bird", bird['location'])
                controls += "Select a new tutor" + generate_tutor_pulldown(bird['id'])
                controls += generate_bird_event(bird['id'])
            except Exception as err:
                return render_template("error.html", urlroot=request.url_root,
                                       title="SQL error", message=sql_error(err))
    # Allow admins and managers to resurrect a bird
    if not(bird["alive"]) and set(['admin', 'manager']).intersection(permissions):
        controls += '''
        <button type="button" class="btn btn-info btn-sm" onclick='update_bird(%s,"alive");'>Mark bird as alive</button>
        '''
        controls = controls % (bird['id'])
    # Get experimental sessions
    try:
        bprops, tutors, events = get_bird_properties(bird, user, permissions)
        sessions = get_bird_sessions(bird)
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    return render_template('bird.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Birds', permissions),
                           bird=colorband(bname, bname, "Bird", True), bprops=bprops,
                           sessions=sessions, tutors=tutors, events=events, controls=controls)


@app.route('/birds/location/<string:location>', methods=['GET'])
def birds_in_location(location):
    ''' Show information for birds in a specific location
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message=f"User {user} is not registered")
    result = initialize_result()
    ipd = receive_payload(result)
    ipd["stype"] = "sbl"
    ipd['key_type'] = "bird"
    ipd["location"] = location
    result["data"] = ""
    sql, bind = get_search_sql(ipd)
    if app.config['DEBUG']:
        print(sql % bind)
    try:
        g.c.execute(sql, bind)
        rows = g.c.fetchall()
        result['rest']['sql_statement'] = g.c.mogrify(sql, bind)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    return render_template('birdloc.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Birds', permissions),
                           location=location, birdloc=generate_birdlist_table(rows))


@app.route('/newbird')
@app.route('/newbirdnest')
def add_bird():
    ''' Register a new bird (requires existing nest)
    '''
    template = request.path.replace("/", "") + ".html"
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message=f"User {user} is not registered")
    if not set(['admin', 'manager']).intersection(permissions):
        return render_template("error.html", urlroot=request.url_root,
                               title='Not permitted',
                               message="You don't have permission to register a new bird")
    color1 = color2 = ''
    if request.path == "/newbird":
        color1 = generate_color_pulldown("color1")
        color2 = generate_color_pulldown("color2")
    return render_template(template, urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Birds', permissions),
                           nestselect=generate_nest_pulldown(["breeding"]),
                           location=generate_location_pulldown("location_id", False),
                           vendor=generate_vendor_pulldown("vendor_id"),
                           color1=color1, color2=color2)


@app.route('/clutchlist', methods=['GET', 'POST'])
def show_clutches(): # pylint: disable=R0914,R0912,R0915
    ''' Clutches
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message=f"User {user} is not registered")
    result = initialize_result()
    ipd = receive_payload(result)
    try:
        g.c.execute(clutch_summary_query(ipd))
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    clutches = generate_clutchlist_table(rows)
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
    try:
        clutch = get_record(cname, "clutch")
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    if not clutch:
        return render_template("error.html", urlroot=request.url_root,
                               title="Not found", message=f"Clutch {cname} was not found")
    controls = ""
    # PLUG OPTIONAL: move clutch to new nest
    #    controls += "<br>Move clutch to new nest " \
    #                + generate_nest_pulldown(["breeding", "fostering"], clutch["id"])
    auth = 1 if set(['admin', 'manager']).intersection(permissions) else 0
    cprops, birds = get_clutch_properties(clutch)
    birds += f"<input type='hidden' id='clutch_id' value='{clutch['id']}'>"
    return render_template('clutch.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Clutches', permissions),
                           clutch=colorband(cname, cname, "Clutch", True), cprops=cprops,
                           birds=birds, controls=controls, auth=auth)


@app.route('/newclutch')
@app.route('/newclutch/<string:nest_id>', methods=['GET'])
def new_clutch(nest_id=None):
    ''' Register a new clutch
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message=f"User {user} is not registered")
    if not set(['admin', 'edit', 'manager']).intersection(permissions):
        return render_template("error.html", urlroot=request.url_root,
                               title='Not permitted',
                               message="You don't have permission to register a new clutch")
    return render_template('newclutch.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Clutches', permissions),
                           start=date.today().strftime("%Y-%m-%d"),
                           stop=date.today().strftime("%Y-%m-%d"),
                           nestselect=generate_nest_pulldown(["breeding", "fostering"],
                                                             default_nest=nest_id))


@app.route('/nestlist', methods=['GET', 'POST'])
def show_nests(): # pylint: disable=R0914,R0912,R0915
    ''' Nest
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message=f"User {user} is not registered")
    result = initialize_result()
    ipd = receive_payload(result)
    try:
        g.c.execute(nest_summary_query(ipd))
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    nests = generate_nestlist_table(rows)
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
    try:
        nest = get_record(nname, "nest")
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    if not nest:
        return render_template("error.html", urlroot=request.url_root,
                               title="Not found", message=f"Nest {nname} was not found")
    controls = '<br>'
    if set(['admin', 'manager']).intersection(permissions):
        try:
            controls += generate_movement_pulldown(nest['id'], "nest", nest["location"])
        except Exception as err:
            return render_template("error.html", urlroot=request.url_root,
                                   title="SQL error", message=sql_error(err))
    nprops, birds, clutches = get_nest_properties(nest)
    auth = 1 if set(['admin', 'manager']).intersection(permissions) else 0
    controls = "" #PLUG Nests don't have locations, birds do
    return render_template('nest.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Nests', permissions),
                           nest=colorband(nname, nname, "Nest", True), nest_id=nest['id'],
                           nprops=nprops, birds=birds, clutches=clutches,
                           events=get_nest_events(nest["name"]),
                           controls=controls, auth=auth)


@app.route('/nests/location/<string:location>', methods=['GET'])
def nests_in_location(location):
    ''' Show information for nests in a specific location
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message=f"User {user} is not registered")
    result = initialize_result()
    ipd = receive_payload(result)
    ipd["stype"] = "sbl"
    ipd['key_type'] = "nest"
    ipd["location"] = location
    result["data"] = ""
    sql, bind = "SELECT * FROM nest_vw WHERE location=%s", (location,)
    if app.config['DEBUG']:
        print(sql % bind)
    try:
        g.c.execute(sql, bind)
        rows = g.c.fetchall()
        result['rest']['sql_statement'] = g.c.mogrify(sql, bind)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    return render_template('nestloc.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Nests', permissions),
                           location=location, nestloc=generate_nestlist_table(rows))


@app.route('/newnest')
def new_nest():
    ''' Register a new nest
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message=f"User {user} is not registered")
    if not set(['admin', 'manager']).intersection(permissions):
        return render_template("error.html", urlroot=request.url_root,
                               title='Not permitted',
                               message="You don't have permission to register a new nest")
    try:
        return render_template('newnest.html', urlroot=request.url_root, face=face,
                               dataset=app.config['DATASET'],
                               navbar=generate_navbar('Nests', permissions),
                               start=date.today().strftime("%Y-%m-%d"),
                               color1select=generate_color_pulldown("color1"),
                               color2select=generate_color_pulldown("color2"),
                               locationselect=generate_movement_pulldown(0),
                               sire1select=generate_bird_pulldown("M", "sire"),
                               damsel1select=generate_bird_pulldown("F", "damsel"),
                               female1select=generate_bird_pulldown("F", "female1"),
                               female2select=generate_bird_pulldown("F", "female2"),
                               female3select=generate_bird_pulldown("F", "female3"))
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))


@app.route('/report/<string:report>', methods=['GET'])
def get_report(report="bird_user"):
    ''' Show a report
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message=f"User {user} is not registered")
    title = {"bird_user": "Birds by user",
             "bird_alive": "Living/dead birds"
    }
    sql = {"bird_user": "SELECT username AS val,COUNT(1) AS num FROM bird_vw WHERE "
                        + "username IS NOT NULL GROUP BY 1 ORDER BY 1",
           "bird_alive": "SELECT IFNULL(NULLIF('Alive', alive), 'Dead') AS val,COUNT(1) AS num "
                         + "FROM bird_vw GROUP BY 1 ORDER BY 1"
          }
    try:
        g.c.execute(sql[report])
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    html = '''
        <table id="report" class="tablesorter standard">
        <thead>
        <tr><th>
    '''
    if report == 'bird_user':
        header = ['User name']
    elif report == 'bird_alive':
        header = ['State']
    header.append('Count')
    html += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
    template = '<tr>' + ''.join("<td>%s</td>")*(len(header)) + '</tr>'
    for row in rows:
        bind = (row['val'], row['num'])
        html += template % bind
    html += "</tbody></table>"
    response = make_response(render_template('general.html', urlroot=request.url_root,
                                             face=face, dataset=app.config['DATASET'],
                                             navbar=generate_navbar('Reports', permissions),
                                             title=title[report], html=html))
    return response


@app.route('/searchlist')
def show_search_form():
    ''' Show the search form
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    try:
        return render_template('search.html', urlroot=request.url_root, face=face,
                               dataset=app.config['DATASET'],
                               navbar=generate_navbar('Search', permissions),
                               upperselect=generate_color_pulldown("uppercolor", True),
                               lowerselect=generate_color_pulldown("lowercolor", True),
                               claim=generate_claim_pulldown("claim", True),
                               location=generate_location_pulldown("location", True))
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))


@app.route('/run_search', methods=['OPTIONS', 'POST'])
def run_search():
    '''
    Search the database
    Search by key text.
    ---
    tags:
      - Search
    parameters:
      - in: query
        name: stype
        schema:
          type: string
        required: true
        description: search type
      - in: query
        name: key_type
        schema:
          type: string
        required: true
        description: key type (display term)
      - in: query
        name: key_text
        schema:
          type: string
        required: false
        description: key text
      - in: query
        name: uppercolor
        schema:
          type: string
        required: false
        description: upper band color
      - in: query
        name: lowercolor
        schema:
          type: string
        required: false
        description: lower band color
    responses:
      200:
          description: Database entries
      500:
          description: Error
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    check_missing_parms(ipd, ['key_type'])
    result["data"] = ""
    if ipd['stype'] == 'sbc' and (not ipd['uppercolor']) and (not ipd['lowercolor']):
        result['data'] = "Missing upper and/or lower band color"
        return generate_response(result)
    if ipd['stype'] == 'sbn' and (not ipd['uppernum']) and (not ipd['lowernum']):
        result['data'] = "Missing upper and/or lower band number"
        return generate_response(result)
    if ipd['stype'] == 'sbu' and not ipd['claim']:
        result['data'] = "Missing claimant"
        return generate_response(result)
    sql, bind = get_search_sql(ipd)
    if app.config['DEBUG']:
        print(sql % bind)
    try:
        g.c.execute(sql, bind)
        rows = g.c.fetchall()
        result['rest']['sql_statement'] = g.c.mogrify(sql, bind)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    if ipd['key_type'] == 'bird':
        result['data'] += "<h2>Birds</h2>" + generate_birdlist_table(rows)
    elif ipd['key_type'] == 'clutch':
        result['data'] += "<h2>Clutches</h2>" + generate_clutchlist_table(rows)
    elif ipd['key_type'] == 'nest':
        result['data'] += "<h2>Nests</h2>" + generate_nestlist_table(rows)
    result['data'] += "<script>tableInitialize();</script>"
    return generate_response(result)


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
    fheader = ['Location', 'Description', 'Number of birds', 'Number of nests']
    header = ['Location', 'Description', 'Number of birds', 'Number of nests']
    if rows:
        if set(['admin', 'manager']).intersection(permissions):
            header.append("Delete")
            template = '<tr class="open">' + ''.join("<td>%s</td>")*2 \
                       + ''.join('<td style="text-align: center">%s</td>'*3) + '</tr>'
        else:
            template = '<tr class="open">' + ''.join("<td>%s</td>")*(len(header)-1) \
                       + '<td style="text-align: center">%s</td></tr>'
        lochead = "<tr>" + "".join([f"<th>{itm}</th>" for itm in header]) + "</tr>"
        fileoutput = ''
        ftemplate = "\t".join(["%s"]*len(fheader)) + "\n"
        for row in rows:
            fileoutput += ftemplate % (row['display_name'], row['definition'],
                                       row['cnt'], row['ncnt'])
            if row["cnt"]:
                row["cnt"] = f"<a href='/birds/location/{row['display_name']}'{row['cnt']}</a>"
            if row["ncnt"]:
                row["ncnt"] = f"<a href='/nests/location/{row['display_name']}'>{row['ncnt']}</a>"
            delcol = ""
            if row['cnt'] == 0 and row['ncnt'] == 0:
                delcol = '<a href="#" onclick="delete_location(' + str(row['id']) \
                         + ');"><i class="fa-solid fa-trash-can fa-lg" style="color:red"></i></a>'
            if set(['admin', 'manager']).intersection(permissions):
                locrows += template % (row['display_name'], row['definition'],
                                       row['cnt'], row['ncnt'], delcol)
            else:
                locrows += template % (row['display_name'], row['definition'], row['cnt'],
                                       row['ncnt'])
        downloadable = create_downloadable('locations', fheader, ftemplate, fileoutput)
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
            <input type="text" class="form-control" id="definition" aria-describedby="itemHelp" placeholder="Enter description (optional)">
            <small id="itemHelp" class="form-text text-muted">Enter the description.</small>
          </div>
        </div>
        <button type="submit" id="sb" class="btn btn-primary btn-sm" onclick="add_location();" href="#">Add location</button>
        '''
    response = make_response(render_template('locationlist.html', urlroot=request.url_root,
                                             face=face, dataset=app.config['DATASET'],
                                             navbar=generate_navbar('Locations', permissions),
                                             locations=locations, locationhead=lochead,
                                             locationrows=locrows, addlocation=addloc))
    return response


@app.route('/comparisons', methods=['GET'])
def show_comparisons(): # pylint: disable=R0914,R0912,R0915
    ''' Comparisons
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message=f"User {user} is not registered")
    try:
        g.c.execute("SELECT COUNT(DISTINCT bird1_id) AS tot FROM bird_comparison")
        total = g.c.fetchone()
        birdcount = total["tot"]
        total = int((total["tot"] / 2) * (total["tot"] + 1))
        g.c.execute("SELECT * FROM bird_comparison_summary_mv")
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    header = ['Comparison', 'Relationship', '# comparisons', 'Mean difference']
    template = '<tr>' + ''.join("<th style='text-align: center'>%s</th>")*(len(header)) \
               + '</tr>'
    comprows = "<thead>" + (template % tuple(header)) + "</thead><tbody>"
    template = template.replace("th", "td")
    comp = {}
    for row in rows:
        if row['comparison'] not in comp:
            comp[row['comparison']] = 0
        comp[row['comparison']] += row['cnt']
        comprows += template % (row['comparison'], row['relationship'], row['cnt'],
                                f"{row['mean']:.3f}")
    comprows += "</tbody>"
    bcnt = {}
    try:
        g.c.execute("SELECT * FROM bird_count_summary_mv")
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    for row in rows:
        bcnt[row["comparison"]] = row["cnt"]
    checkrows = "<thead><tr><th>Comparison</th><th>Birds</th><th>Count</th></tr><tbody>"
    for term in sorted(comp):
        color = "lime" if comp[term] == total else "goldenrod"
        checkrows += f"<tr><td>{term}</td><td>{bcnt[term]}</td>" \
                     + f"<td style='color:{color} !important'>" \
                     + f"{comp[term]}</td></tr>"
    checkrows += "</tbody>"
    response = make_response(render_template('comparison.html', urlroot=request.url_root,
                                             face=face, dataset=app.config['DATASET'],
                                             title=f"Comparison summary for {birdcount} birds",
                                             navbar=generate_navbar('Comparisons', permissions),
                                             comprows=comprows, total=total, checkrows=checkrows))
    return response


@app.route('/comparison/<string:bird>')
def show_comparison(bird):
    ''' Show comparisons for a bird
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message=f"User {user} is not registered")
    try:
        g.c.execute(READ['COMPARISON'], (bird, bird))
        rows = g.c.fetchall()
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    header = ['Bird', 'Relationship', 'Comparison', 'Value']
    template = '<tr>' + ''.join("<th style='text-align: center'>%s</th>")*(len(header)) \
               + '</tr>'
    comprows = "<thead>" + (template % tuple(header)) + "</thead><tbody>"
    template = template.replace("th", "td")
    for row in rows:
        cbird = row["bird1"] if row["bird2"] == bird else row["bird2"]
        cbird = f"<a href='/bird/{cbird}'>{cbird}</a>"
        comprows += template % (cbird, row['relationship'], row['comparison'],
                                f"{row['value']}")
    comprows += "</tbody>"
    response = make_response(render_template('comparison.html', urlroot=request.url_root,
                                             face=face, dataset=app.config['DATASET'],
                                             navbar=generate_navbar('Comparisons', permissions),
                                             title=f"Comparisons for {bird}",
                                             comprows=comprows))
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
        g.db.ping()
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
                           "api_user_counts": app.config['API_USERS'],
                           "ui_user_counts": app.config['UI_USERS'],
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
          + "TABLE_SCHEMA=%s AND TABLE_NAME NOT LIKE '%%vw'"
    g.c.execute(sql, app.config["MYSQL_DATABASE_DB"])
    rows = g.c.fetchall()
    result['rest']['row_count'] = len(rows)
    result['rest']['sql_statement'] = g.c.mogrify(sql)
    result['data'] = {}
    for r in rows:
        result['data'][r['TABLE_NAME']] = r['TABLE_ROWS']
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
    execute_sql(result, 'SELECT * FROM information_schema.processlist', app.config["DEBUG"])
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
        bind = hostname
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
# * Table/view endpoints                                                      *
# *****************************************************************************

@app.route('/tables', methods=['GET'])
def get_tables():
    '''
    Get a list of tables
    Get a list of tables
    ---
    tags:
      - Table
    responses:
      200:
          description: list of tables
    '''
    result = initialize_result()
    execute_sql(result, "SHOW TABLES", app.config["DEBUG"])
    return generate_response(result)


@app.route('/columns/<string:table>', methods=['GET'])
def get_view_columns(table=""):
    '''
    Get columns from a view or table
    Show the columns in a view/table, which may be used to filter results for
    other endpoints.
    ---
    tags:
      - Table
    parameters:
      - in: path
        name: table
        schema:
          type: string
        required: true
        description: table or view name
    responses:
      200:
          description: Columns in specified view
    '''
    result = initialize_result()
    view = table + "_vw"
    if view in app.config["VIEWS"]:
        table = view
    if table == "processlist":
        table = "information_schema.processlist"
    result["columns"] = []
    try:
        g.c.execute("SHOW COLUMNS FROM " + table)
        rows = g.c.fetchall()
        if rows:
            result["columns"] = rows
            result['rest']['row_count'] = len(rows)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    return generate_response(result)


@app.route('/view/<string:table>', methods=['GET'])
def get_view_rows(table=""):
    '''
    Get view/table rows (with filtering)
    Return rows from a specified view/table. The caller can filter on any of the
    columns in the view/table. Inequalities (!=) and some relational operations
    (&lt;= and &gt;=) are supported. Wildcards are supported (use "*").
    Specific columns from the view/table can be returned with the _columns key.
    The returned list may be ordered by specifying a column with the _sort key.
    In both cases, multiple columns would be separated by a comma.
    ---
    tags:
      - Table
    parameters:
      - in: path
        name: table
        schema:
          type: string
        required: true
        description: table or view name
    responses:
      200:
          description: rows from specified view
      404:
          description: Rows not found
    '''
    result = initialize_result()
    table = re.sub("[?;].*", "", table)
    view = table + "_vw"
    if view in app.config["VIEWS"]:
        table = view
    execute_sql(result, f"SELECT * FROM {table}", app.config["DEBUG"])
    return generate_response(result)


@app.route('/view/group/<string:table>', methods=['GET'])
def get_view_group_rows(table=""):
    '''
    Get grouped by view/table rows (with filtering)
    Return rows from a specified view/table. The caller can filter on any of the
    columns in the view/table. Inequalities (!=) and some relational operations
    (&lt;= and &gt;=) are supported. Wildcards are supported (use "*").
    Specific columns from the view/table can be returned with the _columns key.
    The returned list may be ordered by specifying a column with the _sort key.
    In both cases, multiple columns would be separated by a comma.
    ---
    tags:
      - Table
    parameters:
      - in: path
        name: table
        schema:
          type: string
        required: true
        description: table or view name
    responses:
      200:
          description: rows from specified view
      404:
          description: Rows not found
    '''
    result = initialize_result()
    table = re.sub("[?;].*", "", table)
    view = table + "_vw"
    if view in app.config["VIEWS"]:
        table = view
    whatl = []
    if request.query_string:
        query_string = request.query_string
        if not isinstance(query_string, str):
            query_string = query_string.decode('utf-8')
        ipd = parse_qs(query_string)
    for key, val in ipd.items():
        if key == '_columns':
            whatl.append(val[0])
    print(whatl)
    if not whatl:
        result["rest"]["error"] = "No columns were specified"
        return generate_response(result)
    ccount = len(",".join(whatl).split(","))
    group = ','.join([str(itm) for itm in list(range(1, ccount+1))])
    what = ",".join(whatl) + ",COUNT(1) AS count"
    execute_sql(result, f"SELECT {what} FROM {table}", app.config["DEBUG"],
                "data", group)
    return generate_response(result)


# *****************************************************************************
# * CV/CV term endpoints                                                      *
# *****************************************************************************

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


@app.route('/cvterm', methods=['OPTIONS', 'DELETE'])
def delete_cv_term(): # pragma: no cover
    '''
    Delete CV term
    ---
    tags:
      - CV
    parameters:
      - in: query
        name: id
        schema:
          type: string
        required: true
        description: cv  term ID
    responses:
      200:
          description: CV term deleted
      400:
          description: Missing or incorrect arguments
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    check_missing_parms(ipd, ['id'])
    if not check_permission(result["rest"]["user"], ["admin", "manager"]):
        raise InvalidUsage("You don't have permission to delete CV terms")
    sql = "DELETE FROM cv_term WHERE id=%s"
    try:
        g.c.execute(sql % (ipd['id']))
        result['rest']['row_count'] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    g.db.commit()
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
    if not check_permission(result["rest"]["user"], ["admin", "manager"]):
        raise InvalidUsage("You don't have permission to change a bird's location")
    result["rest"]["row_count"] = 0
    sql = "UPDATE bird SET location_id =%s WHERE id=%s"
    try:
        bind = (location_id, bird_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
        log_bird_event(bird_id, status="moved", user=result['rest']['user'],
                       location_id=location_id)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
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
    if not check_permission(result["rest"]["user"], ["admin", "manager"]):
        raise InvalidUsage("You don't have permission to change a bird's nest")
    result["rest"]["row_count"] = 0
    try:
        bind = tuple(nest_id)
        g.c.execute("SELECT location_id FROM bird WHERE nest_id=%s LIMIT 1", bind)
        row = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    sql = "UPDATE bird SET nest_id =%s,location_id=%s WHERE id=%s"
    try:
        bind = (nest_id, row["location_id"], bird_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
        log_bird_event(bird_id, status="moved", user=result['rest']['user'],
                       location_id=row["location_id"], nest_id=nest_id)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    g.db.commit()
    return generate_response(result)


@app.route('/bird/event/<string:bird_id>', methods=['OPTIONS', 'POST'])
def bird_event(bird_id):
    '''
    Add a bird event
    Add a bird event.
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
      - in: query
        name: notes
        schema:
          type: string
        required: true
        description: notes
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    if not check_permission(result["rest"]["user"], ["admin", "edit", "manager"]):
        raise InvalidUsage("You don't have permission to add a bird event")
    check_missing_parms(ipd, ["event", "date", "terminal"])
    result["rest"]["row_count"] = 0
    try:
        log_bird_event(bird_id, status=ipd["event"], user=result['rest']['user'],
                       notes=ipd["notes"], terminal=ipd["terminal"], date=ipd["date"])
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    if ipd["terminal"]:
        sql = "UPDATE bird SET alive=0,death_date=CURRENT_TIMESTAMP(),user_id=NULL WHERE id=%s"
        try:
            bind = tuple(bird_id)
            g.c.execute(sql, bind)
            result["rest"]["row_count"] += g.c.rowcount
            if ipd["event"] != "died":
                log_bird_event(bird_id, status="died", user=result['rest']['user'],
                               location_id=None, terminal=1)
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
    if ipd["event"] == "unclaimed":
        sql = "UPDATE bird SET user_id=NULL WHERE id=%s"
        try:
            bind = tuple(bird_id)
            g.c.execute(sql, bind)
            result["rest"]["row_count"] += g.c.rowcount
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
    g.db.commit()
    return generate_response(result)


@app.route('/bird/notes/<string:bird_id>', methods=['OPTIONS', 'POST'])
def bird_notes(bird_id):
    '''
    Update a bird's notes
    Update a bird's notes.
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
      - in: query
        name: notes
        schema:
          type: string
        required: true
        description: notes
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    if not check_permission(result["rest"]["user"], ["admin", "edit", "manager"]):
        raise InvalidUsage("You don't have permission to change a bird's notes")
    check_missing_parms(ipd, ["notes"])
    result["rest"]["row_count"] = 0
    sql = "UPDATE bird SET notes=%s WHERE id=%s"
    try:
        bind = (ipd["notes"], bird_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    g.db.commit()
    return generate_response(result)


@app.route('/bird/sex/<string:bird_id>/<string:sex>', methods=['OPTIONS', 'POST'])
def bird_sex(bird_id, sex):
    '''
    Update a bird's sex
    Update a bird's sex.
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
        name: sex
        schema:
          type: string
        required: true
        description: sex
      - in: query
        name: tutor
        schema:
          type: integer
        required: true
        description: assign tutor
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    if not check_permission(result["rest"]["user"], ["admin", "edit", "manager"]):
        raise InvalidUsage("You don't have permission to change a bird's sex")
    result["rest"]["row_count"] = 0
    sql = "UPDATE bird SET sex=%s WHERE id=%s"
    try:
        bind = (sex, bird_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    if ipd["tutor"] and sex == "M":
        try:
            add_sex_trigger(bird_id)
        except Exception as err:
            raise InvalidUsage("Could not insert tutor", 500) from err
    g.db.commit()
    return generate_response(result)


@app.route('/bird/tutor/<string:bird_id>/<string:tutor_type>/<string:tutor_id>',
           methods=['OPTIONS', 'POST'])
def bird_tutor(bird_id, tutor_type, tutor_id):
    '''
    Assign a tutor to a bird
    Assign a bird or computer tutor to a bird. Allowable for bird owner or admin/manager.
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
        name: tutor_type
        schema:
          type: string
        required: true
        description: tutor type ("bird" or "computer")
      - in: path
        name: tutor_id
        schema:
          type: string
        required: true
        description: tutor ID
    '''
    result = initialize_result()
    permissions = check_permission(result["rest"]["user"])
    bird = get_record(bird_id, "bird")
    if not (set(['admin', 'manager']).intersection(permissions) \
            or bird["user"] == result["rest"]["user"]):
        raise InvalidUsage("You don't have permission to assign a bird's tutor")
    if not bird:
        raise InvalidUsage(f"{bird_id} is not a valid bird ID")
    if bird["sex"] != "M":
        raise InvalidUsage(f"Bird {bird_id} is not a male")
    if not bird["alive"]:
        raise InvalidUsage(f"Bird {bird_id} is dead")
    assign_tutor(result, bird_id, tutor_type, tutor_id)
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
    if not check_permission(result["rest"]["user"], ["admin", "manager"]):
        raise InvalidUsage("You don't have permission to report a bird as alive")
    result["rest"]["row_count"] = 0
    sql = "UPDATE bird SET alive=1,death_date=NULL WHERE id=%s"
    try:
        bind = tuple(bird_id)
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
    if not check_permission(result["rest"]["user"], ["admin", "edit", 'manager']):
        raise InvalidUsage("You don't have permission to claim a bird")
    result["rest"]["row_count"] = 0
    try:
        claim_single_bird(bird_id, user=result['rest']['user'])
        result["rest"]["row_count"] = 0
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
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
    if not check_permission(result["rest"]["user"], ["admin", "edit", "manager"]):
        raise InvalidUsage("You don't have permission to report a bird as dead")
    result["rest"]["row_count"] = 0
    sql = "UPDATE bird SET alive=0,death_date=CURRENT_TIMESTAMP(),user_id=NULL WHERE id=%s"
    try:
        bind = tuple(bird_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
        log_bird_event(bird_id, status="died", user=result['rest']['user'], location_id=None,
                       terminal=1)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
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
    if not check_permission(result['rest']['user'], ['admin', 'edit', 'manager']):
        raise InvalidUsage("You don't have permission to unclaim a bird")
    result["rest"]["row_count"] = 0
    sql = "UPDATE bird SET user_id=NULL WHERE id=%s"
    try:
        bind = tuple(bird_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
        log_bird_event(bird_id, status="unclaimed", user=result['rest']['user'], location_id=None)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    g.db.commit()
    return generate_response(result)


@app.route('/registerbird', methods=['OPTIONS', 'POST'])
def register_bird():
    '''
    Register new birds
    Register new birds.
    ---
    tags:
      - Bird
    parameters:
      - in: query
        name: clutch_id
        schema:
          type: array
        required: true
        description: clutch ID
      - in: query
        name: bands
        schema:
          type: array
        required: true
        description: array of arrays containing bands
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    check_dates(ipd)
    if not check_permission(result['rest']['user'], ['admin', 'edit', 'manager']):
        raise InvalidUsage("You don't have permission to register a bird")
    if "clutch_id" in ipd:
        check_missing_parms(ipd, ["bands"])
        try:
            g.c.execute("SELECT * FROM clutch WHERE id=%s", (ipd["clutch_id"]))
            row = g.c.fetchone()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
        ipd["nest_id"] = row["nest_id"]
        ipd["start_date"] = str(row['clutch_early']).split(' ', maxsplit=1)[0]
        ipd["stop_date"] = str(row['clutch_late']).split(' ', maxsplit=1)[0]
        register_birds(ipd, result)
    elif "nest_id" in ipd:
        check_missing_parms(ipd, ["start_date", "stop_date", "sex", "number1", "number2"])
        register_single_bird(ipd, result)
    else:
        check_missing_parms(ipd, ["start_date", "stop_date", "location_id", "vendor_id",
                                  "color1", "number1", "color2", "number2"])
        register_single_bird(ipd, result)
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
    if not check_permission(result['rest']['user'], ['admin', 'edit', 'manager']):
        raise InvalidUsage("You don't have permission to register a clutch")
    check_missing_parms(ipd, ["nest_id", "start_date", "stop_date"])
    check_dates(ipd)
    try:
        nest = get_record(ipd['nest_id'], "nest")
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    name = "_".join([ipd['start_date'].replace("-", ""), nest['name']])
    result['rest']['row_count'] = 0
    sql = "INSERT INTO clutch (name, nest_id, notes, clutch_early,clutch_late) VALUES " \
          + "(%s,%s,%s,%s,%s)"
    try:
        bind = (name, ipd["nest_id"], ipd['notes'], ipd["start_date"], ipd["stop_date"])
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
        result["rest"]["clutch_id"] = g.c.lastrowid
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    if "bands" in ipd and ipd["bands"]:
        del ipd["notes"]
        ipd["clutch_id"] = result["rest"]["clutch_id"]
        register_birds(ipd, result)
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
    sql = "UPDATE nest SET location_id=%s WHERE id=%s"
    try:
        bind = (location_id, nest_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
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
        bind = tuple(nest_id)
        g.c.execute(sql, bind)
        rows = g.c.fetchall()
        for row in rows:
            log_bird_event(row["id"], status="moved", user=result['rest']['user'],
                           location_id=location_id)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    g.db.commit()
    return generate_response(result)

@app.route('/nest/tutor/<string:nest_id>',
           methods=['OPTIONS', 'POST'])
def nest_tutor(nest_id):
    '''
    Assign the nest sire as tutor for males in a nest.
    Assign the nest sire as tutor for all males without a ruror in the nest.
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
    '''
    result = initialize_result()
    permissions = check_permission(result["rest"]["user"])
    if not set(['admin', 'manager']).intersection(permissions):
        raise InvalidUsage("You don't have permission to assign a bird's tutor")
    nest = get_record(nest_id, "nest")
    if not nest:
        raise InvalidUsage(f"Nest {nest_id} is not a valid nest ID")
    if not nest["sire"]:
        raise InvalidUsage(f"Nest {nest_id} does not have a sire")
    sire = get_record(nest["sire"], "bird")
    sql = "SELECT id FROM bird WHERE nest_id=%s and sex='M' AND alive=1 AND id NOT IN " \
          + "(SELECT bird_id FROM bird_tutor) ORDER BY 1"
    try:
        bind = tuple(nest_id)
        g.c.execute(sql, bind)
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    for row in rows:
        if row["id"] != sire["id"]:
            assign_tutor(result, row["id"], "bird", str(sire["id"]))
    g.db.commit()
    return generate_response(result)


#PLUG This is currently unused
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
        bind = tuple(new_nest_id)
        g.c.execute("SELECT location_id FROM bird WHERE nest_id=%s LIMIT 1", bind)
        row = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    location_id = row["location_id"]
    # Get all birds in current nest
    sql = "SELECT id FROM bird WHERE nest_id=%s"
    try:
        bind = tuple(nest_id)
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
        for row in rows:
            log_bird_event(row["id"], status="moved", user=result['rest']['user'],
                           location_id=location_id, nest_id=new_nest_id)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    # Remove birds from old nest
    sql = "UPDATE nest SET sire_id=NULL,damsel_id=NULL,female1_id=NULL,female2_id=NULL," \
          + "female3_id=NULL,breeding=0,fostering=0,tutoring=0,active=0 where id=%s"
    try:
        bind = tuple(nest_id)
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
    check_missing_parms(ipd, ["start_date", "color1", "color2", "location_id"])
    check_dates(ipd)
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
              + "location_id,notes,create_date) VALUES (%s,%s,%s,%s,%s,1,%s,%s,%s)"
        bind = (name, band, ipd["female1_id"], ipd["female2_id"], ipd["female3_id"],
                ipd["location_id"], ipd['notes'], ipd["start_date"])
    else:
        sql = "INSERT INTO nest (name,band,sire_id,damsel_id,breeding,location_id,notes," \
              + "create_date) VALUES (%s,%s,%s,%s,1,%s,%s,%s)"
        bind = (name, band, ipd["sire_id"], ipd["damsel_id"], ipd["location_id"], ipd['notes'],
                ipd["start_date"])
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
                        (result["rest"]["nest_id"], ipd["location_id"], bird_id))
            result["rest"]["row_count"] += g.c.rowcount
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
    g.db.commit()
    return generate_response(result)


# *****************************************************************************
# * Location endpoints                                                        *
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
    g.db.commit()
    return generate_response(result)


@app.route('/user', methods=['OPTIONS', 'DELETE'])
def delete_user(): # pragma: no cover
    '''
    Delete user
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
    responses:
      200:
          description: User deleted
      400:
          description: Missing or incorrect arguments
    '''
    result = initialize_result()
    ipd = receive_payload(result)
    check_missing_parms(ipd, ['name'])
    if not check_permission(result['rest']['user'], 'admin'):
        raise InvalidUsage("You don't have permission to delete a user")
    result['rest']['row_count'] = 0
    try:
        user_id = get_user_id(ipd['name'])
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    sql = 'DELETE FROM user_permission WHERE user_id=%s'
    try:
        g.c.execute(sql % (user_id))
        result['rest']['row_count'] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    sql = 'DELETE FROM user WHERE id=%s'
    try:
        g.c.execute(sql % (user_id))
        result['rest']['row_count'] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
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
    try:
        user_id = get_user_id(ipd['name'])
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
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
# * Analysis endpoints                                                        *
# *****************************************************************************

@app.route('/marker/<string:marker>', methods=['GET'])
def get_marker(marker=""):
    '''
    Get marker information
    Return information on a genetic marker.
    ---
    tags:
      - Allelic state
    parameters:
      - in: path
        name: marker
        schema:
          type: string
        required: true
        description: marker
    '''
    result = initialize_result()
    execute_sql(result, f"SELECT * FROM phenotype_state_mv WHERE marker={marker}",
                app.config["DEBUG"], "temp")
    result["data"] = []
    for row in result["temp"]:
        lst = [float(num) for num in row["svalues"].split(",")]
        vari = np.var(lst)
        stdev = np.std(lst)
        result["data"].append({"type": row["type"],
                               "state": row["state"],
                               "count": row["count"],
                               "stdev": stdev,
                               "variance": vari
                              })
    del result["temp"]
    return generate_response(result)


@app.route('/allelic_state/<string:bird>', methods=['GET'])
def get_allelic_state(bird=""):
    '''
    Get allelic state information for a bird
    Return information on a bird's allelic state.
    ---
    tags:
      - Allelic state
    parameters:
      - in: path
        name: bird
        schema:
          type: string
        required: true
        description: bird name
    '''
    result = initialize_result()
    execute_sql(result, f"SELECT marker,state FROM state_vw WHERE bird='{bird}' ORDER BY marker",
                app.config["DEBUG"], "temp")
    result["data"] = {}
    for row in result["temp"]:
        result["data"][row['marker']] = row['state']
    del result["temp"]
    return generate_response(result)


@app.route('/colortest', methods=['GET'])
def get_cc():
    '''
    Get marker information
    Return information on a genetic marker.
    ---
    tags:
      - Allelic state
    parameters:
      - in: path
        name: marker
        schema:
          type: string
        required: true
        description: marker
    '''
    result = initialize_result()
    result["data"] = {}
    result["data"]["original"] = "20210506_red32blue45"
    result["data"]["short"] = convert_banding(result["data"]["original"])
    result["data"]["long"] = convert_banding(result["data"]["short"])
    result["data"]["parsed"] = parse_bird_name(result["data"]["long"])
    #result["data"]["colors"] = get_colors_from_band(result["data"]["band"])
    return generate_response(result)



# *****************************************************************************


if __name__ == '__main__':
    if app.config["RUN_MODE"] == 'dev':
        app.run(ssl_context="adhoc", debug=app.config["DEBUG"])
    else:
        application.run(debug=app.config["DEBUG"])
