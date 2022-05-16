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
import pymysql.cursors
import pymysql.err
import requests
from oauthlib.oauth2 import WebApplicationClient

# pylint: disable=W0401, W0614
import birdsong_utilities
from birdsong_utilities import *

# pylint: disable=C0302, C0103, W0703

class CustomJSONEncoder(JSONEncoder):
    ''' Define a custom JSON encoder
    '''
    def default(self, obj1):   # pylint: disable=E0202, W0221
        try:
            if isinstance(obj1, datetime):
                return obj1.strftime("%a, %-d %b %Y %H:%M:%S")
            if isinstance(obj1, timedelta):
                seconds = obj1.total_seconds()
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                seconds = seconds % 60
                return f"{hours:02d}:{minutes:02d}:{seconds:.02f}"
            iterable = iter(obj1)
        except TypeError:
            pass
        else:
            return list(iterable)
        return JSONEncoder.default(self, obj1)


__version__ = "0.0.1"
app = Flask(__name__, template_folder="templates")
app.json_encoder = CustomJSONEncoder
app.config.from_pyfile("config.cfg")
# Override Flask's usual behavior of sorting keys (interferes with prioritization)
app.config["JSON_SORT_KEYS"] = False
CORS(app, supports_credentials=True)
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
        app.config["USERS"][authuser] = app.config["USERS"].get(authuser, 0) + 1
    elif request.method in ["DELETE", "POST"] or request.endpoint in app.config["REQUIRE_AUTH"]:
        raise InvalidUsage('You must authorize to use this endpoint', 401)
    if app.config["LAST_TRANSACTION"] and time() - app.config["LAST_TRANSACTION"] \
       >= app.config["RECONNECT_SECONDS"]:
        print("Seconds since last transaction: %d" % (time() - app.config["LAST_TRANSACTION"]))
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
    result["rest"]["elapsed_time"] = str(timedelta(seconds=(time() - START_TIME)))
    return jsonify(**result)


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
        events = '''
        <br><br>
        <h3>Events</h3>
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


def get_bird_properties(bird, user, permissions):
    ''' Get a bird's properties
        Keyword arguments:
          bird: bird record
          user: user
          permissions: user permissions
        Returns: HTML
    '''
    bprops = []
    parent = ""
    if bird["sex"]:
        try:
            g.c.execute(READ["ISPARENT"], tuple([bird["name"]]*2))
            rows = g.c.fetchall()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
        if rows:
            parent = " (%s)" % ("sire" if bird["sex"] == "M" else "damsel")
    bprops.append(["Name:", colorband(bird["name"], bird["name"] + parent)])
    bprops.append(["Band:", bird["band"]])
    if bird["clutch"]:
        bprops.append(["Clutch:", '<a href="/clutch/%s">%s</a>' % tuple([bird["clutch"]]*2)])
    else:
        bprops.append(["Clutch:", "None"])
    if bird["nest"]:
        bprops.append(["Nest:", bird["nest_location"] \
                      + ' <a href="/nest/%s">%s</a>' % tuple([bird["nest"]]*2)])
    else:
        bprops.append(["Nest:", "Outside vendor"])
    if bird["vendor"]:
        bprops.append(["Vendor:", bird["vendor"]])
    bprops.append(["Location:", bird['location']])
    bprops.append(["Claimed by:", apply_color(bird["username"] or "UNCLAIMED", "gold",
                                              (not bird["user"]))])
    birdsex = bird["sex"]
    if (not birdsex) and bird["alive"] and \
       (set(['admin', 'manager']).intersection(permissions) or user == bird["user"]):
        birdsex = generate_sex_pulldown(bird["id"])
    bprops.append(["Sex:", birdsex])
    if bird["sire"]:
        bprops.append(["Sire:", '<a href="/bird/%s">%s</a>' % tuple([bird["sire"]]*2)])
    else:
        bprops.append(["Sire:", "None"])
    if bird["damsel"]:
        bprops.append(["Damsel:", '<a href="/bird/%s">%s</a>' % tuple([bird["damsel"]]*2)])
    else:
        bprops.append(["Damsel:", "None"])
    early = str(bird["hatch_early"]).split(' ', maxsplit=1)[0]
    late = str(bird["hatch_late"]).split(' ', maxsplit=1)[0]
    bprops.append(["Hatch date:", " - ".join([early, late])])
    if bird["alive"]:
        bprops.append(["Current age:", bird["current_age"]])
    alive = apply_color("YES", "lime", bird["alive"], "red", "NO")
    if not bird["alive"]:
        bprops.append(["Death date:", bird["death_date"]])
    bprops.append(["Alive:", alive])
    birdnotes = bird["notes"]
    if (not birdnotes) and bird["alive"] and \
       set(['admin', 'edit', 'manager']).intersection(permissions) and user == bird["user"]:
        birdnotes = generate_notes_field(bird["id"])
    bprops.append(["Notes:", birdnotes])
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
        return bprops, get_bird_events(bird["name"])
    except Exception as err:
        raise err


def get_birds_in_clutch_or_nest(rec, dnd, ttype):
    ''' Get the birds in a nest
        Keyword arguments:
          rec: clutch or nest record
          dnd: birds to not display
          ttype: table type
        Returns:
          Birds in nest
    '''
    sql = "SELECT * FROM bird_vw WHERE " + ttype + "=%s ORDER BY 1"
    try:
        if app.config['DEBUG']:
            print(sql % (rec["name"]))
        g.c.execute(sql, (rec["name"],))
        irows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    rows = []
    for row in irows:
        if row["name"] in dnd:
            continue
        rows.append(row)
    if rows:
        header = ['Name', 'Band', 'Claimed by', 'Location', 'Sex', 'Notes',
                  'Current age', 'Alive']
        birds = "<h3>Additional birds in nest</h3>" if ttype == "nest" \
                else "<h3>Birds in clutch</h3>"
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
            bird = '<a href="/bird/%s">%s</a>' % tuple([row['name']]*2)
            if not row['alive']:
                row['current_age'] = '-'
            alive = apply_color("YES", "lime", row["alive"], "red", "NO")
            outcol = [rclass, bird, row['band'], row["username"], row['location'], row['sex'],
                      row['notes'], row['current_age'], alive]
            birds += template % tuple(outcol)
        birds += "</tbody></table>"
    else:
        birds = "There are no additional birds in this %s." % (ttype)
    return birds


def get_clutch_properties(clutch):
    ''' Get a clutch's properties
        Keyword arguments:
          clutch: cliutch record
          birds: birds in clutch
    '''
    cprops = []
    nest = '<a href="/nest/%s">%s</a>' % tuple([clutch['nest']]*2)
    cprops.append(["Name:", colorband(clutch["name"], clutch["name"])])
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
    nprops.append(["Name:", colorband(nest["name"], nest["name"])])
    nprops.append(["Band:", nest["band"]])
    nprops.append(["Location:", nest["location"]])
    if (nest["sire"] and nest["damsel"]):
        nprops.append(["Sire:", '<a href="/bird/%s">%s</a>' % tuple([nest["sire"]]*2)])
        nprops.append(["Damsel:", '<a href="/bird/%s">%s</a>' % tuple([nest["damsel"]]*2)])
        dnd = [nest["sire"], nest["damsel"]]
    else:
        dnd = []
        for idx in range(1, 4):
            if app.config['DEBUG']:
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
    # Clutch list
    try:
        g.c.execute("SELECT * FROM clutch_vw WHERE nest=%s ORDER BY 1", (nest["name"]))
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    if rows:
        header = ['Name', 'Notes', 'Clutch early', "Clutch late"]
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
            outcol = [nname, row['notes'], strip_time(row['clutch_early']),
                      strip_time(row["clutch_late"])]
            clutches += template % tuple(outcol)
        clutches += "</tbody></table>"
    else:
        clutches = "There are no clutches in this nest."
    return nprops, get_birds_in_clutch_or_nest(nest, dnd, "nest"), clutches


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
    pulldown = '<select id="bevent" class="form-control col-sm-11" onchange="fix_event();">' \
               + '<option value="">Select an event...</option>'
    for row in rows:
        pulldown += '<option value="%s">%s</option>' \
                    % (row["cv_term"], row["display_name"])
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
    sql = "INSERT INTO bird_event (%s) VALUES (%s)"  % (",".join(columns), ",".join(values))
    try:
        if app.config['DEBUG']:
            print(sql % tuple(bind))
        g.c.execute(sql, tuple(bind))
    except Exception as err:
        raise err


def register_single_bird(ipd, result):
    ''' Register one bird (no clutch or nest)
        Keyword arguments:
          ipd: request payload
          result: result dictionary
        Returns:
          Values added in result dict
    '''
    # User/claim
    user_id = None
    if ipd["claim"]:
        try:
            g.c.execute("SELECT id FROM user WHERE name=%s", (result['rest']['user'],))
            row = g.c.fetchone()
            user_id = row["id"]
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
    if ("vendor_id" not in ipd) or (not ipd["vendor_id"]):
        ipd["vendor_id"] = None
    result['rest']['row_count'] = 0
    # Notes
    if ("notes" not in ipd) or (not ipd["notes"]):
        ipd["notes"] = ''
    result["rest"]["bird_id"] = []
    result["rest"]["relationship_id"] = []
    if "nest_id" in ipd:
        # Get colors
        try:
            g.c.execute("SELECT * FROM nest WHERE id=" + ipd["nest_id"])
            nest = g.c.fetchone()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
        ipd["color1"], ipd["color2"] = get_colors_from_band(nest["band"])
        ipd["location_id"] = nest["location_id"]
    else:
        ipd["nest_id"] = None
    name = ipd["start_date"].replace("-", "") + "_" + ipd["color1"] + ipd["number1"] \
           + ipd["color2"] + ipd["number2"]
    band = get_band_from_name(name)
    try:
        bind = (1, name, band, ipd["nest_id"], None, ipd["location_id"], ipd["vendor_id"],
                user_id, ipd["notes"], ipd["start_date"], ipd["stop_date"], ipd["sex"])
        if app.config['DEBUG']:
            print(WRITE["INSERT_BIRD"] % bind)
        g.c.execute(WRITE["INSERT_BIRD"], bind)
        result["rest"]["row_count"] += g.c.rowcount
        bird_id = g.c.lastrowid
        result["rest"]["bird_id"].append(bird_id)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    if ipd["nest_id"]:
        try:
            create_relationship(ipd, result, bird_id, nest)
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
    try:
        if ipd["claim"]:
            log_bird_event(bird_id, status="claimed", user=result['rest']['user'],
                           location_id=ipd["location_id"])
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
    if ipd["claim"]:
        try:
            g.c.execute("SELECT id FROM user WHERE name=%s", (result['rest']['user'],))
            row = g.c.fetchone()
            user_id = row["id"]
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
    result['rest']['row_count'] = 0
    if ("notes" not in ipd) or (not ipd["notes"]):
        ipd["notes"] = ''
    result["rest"]["bird_id"] = []
    result["rest"]["relationship_id"] = []
    for bird in band:
        try:
            bind = (1, bird["name"], bird["band"], ipd["nest_id"], ipd["clutch_id"], loc_id, None,
                    user_id, ipd['notes'], ipd["start_date"], ipd["stop_date"], None)
            if app.config['DEBUG']:
                print(WRITE["INSERT_BIRD"] % bind)
            g.c.execute(WRITE["INSERT_BIRD"], bind)
            result["rest"]["row_count"] += g.c.rowcount
            bird_id = g.c.lastrowid
            result["rest"]["bird_id"].append(bird_id)
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
        create_relationship(ipd, result, bird_id, nest)
    try:
        for bird_id in result["rest"]["bird_id"]:
            log_bird_event(bird_id, user=result['rest']['user'], nest_id=ipd["nest_id"],
                           location_id=loc_id)
            if ipd["claim"]:
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
    if app.config["DEBUG"]:
        print("Getting Google discovery information from %s" % (app.config["GOOGLE_DISCOVERY_URL"]))
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
    for heading in ['Birds', 'Clutches', 'Nests', 'Searches', 'Locations', 'Users']:
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
        elif heading == 'Clutches' and set(['admin', 'edit', 'manager']).intersection(permissions):
            nav += '<li class="nav-item dropdown active">' \
                if heading == active else '<li class="nav-item">'
            nav += '<a class="nav-link dropdown-toggle" href="#" id="navbarDropdown" ' \
                   + 'role="button" data-toggle="dropdown" aria-haspopup="true" ' \
                   + 'aria-expanded="false">Clutches</a><div class="dropdown-menu" '\
                   + 'aria-labelledby="navbarDropdown">'
            nav += '<a class="dropdown-item" href="/clutchlist">Show</a>' \
                   + '<a class="dropdown-item" href="/newclutch">Add</a>'
            nav += '</div></li>'
        elif heading == 'Nests' and set(['admin', 'edit', 'manager']).intersection(permissions):
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
            if heading in ["Clutches", "Searches"]:
                link = ('/' + heading[:-2] + 'list').lower()
            else:
                link = ('/' + heading[:-1] + 'list').lower()
            nav += '<a class="nav-link" href="%s">%s</a>' % (link, heading)
            nav += '</li>'
    nav += '</ul></div></nav>'
    return nav


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
    if app.config["DEBUG"]:
        print("Getting request URI from %s" % (authorization_endpoint))
    # Use library to construct the request for Google login and provide
    # scopes that let you retrieve user's profile from Google
    request_uri = CLIENT.prepare_request_uri(
        authorization_endpoint,
        redirect_uri=request.base_url + "/callback",
        scope=["openid", "email", "profile"]
    )
    if app.config["DEBUG"]:
        print("Request URI is %s" % (request_uri))
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
    if app.config["DEBUG"]:
        print("Getting token URL from %s" % (token_endpoint))
    # Get tokens using the client ID and secret
    token_url, headers, body = CLIENT.prepare_token_request(
        token_endpoint,
        authorization_response=request.url,
        redirect_url=request.base_url,
        code=code
    )
    if app.config["DEBUG"]:
        print("Getting token from %s" % (token_url))
    token_response = requests.post(
        token_url,
        headers=headers,
        data=body,
        auth=(app.config['GOOGLE_CLIENT_ID'], app.config['GOOGLE_CLIENT_SECRET']),
    )
    if app.config["DEBUG"]:
        print("Got a %s token" % (token_response.json()["token_type"]))
    # Parse the token
    CLIENT.parse_request_body_response(json.dumps(token_response.json()))
    # Get the user's profile information
    userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
    uri, headers, body = CLIENT.add_token(userinfo_endpoint)
    if app.config["DEBUG"]:
        print("Getting user information from %s" % (uri))
    userinfo_response = requests.get(uri, headers=headers, data=body)
    my_token = token_response.json().get("id_token")
    # Verify the user's email
    if not userinfo_response.json().get("email_verified"):
        return "User email not available or not verified by Google.", 400
    if app.config["DEBUG"]:
        print("Logged in as %s" % (userinfo_response.json()["email"]))
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
    uprops.append(['Permissions:', '<br>'.join(rec['permissions'].split(',')) \
                  if rec['permissions'] else ""])
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
    controls = '<br>'
    if set(['admin']).intersection(permissions):
        controls += '''
        <button type="button" class="btn btn-danger btn-sm" onclick='delete_user();'>Delete user</button>
        '''
    return render_template('user.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'], user=uname,
                           navbar=generate_navbar('Users', permissions),
                           uprops=uprops, ptable=ptable, controls=controls)


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
        return send_file('/tmp/' + fname, download_name=fname)
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
        sql = bird_summary_query(ipd, user)
        if app.config["DEBUG"]:
            print(sql)
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
        bird = get_record(bname, "bird")
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
            try:
                nestpull = generate_nest_pulldown(["fostering", "tutoring"], nest['id'])
                if "No nest" not in nestpull:
                    controls += "Move bird to new nest" + nestpull
                controls += generate_movement_pulldown(bird['id'], "bird", bird['location'])
                controls += generate_bird_event(bird['id'])
            except Exception as err:
                return render_template("error.html", urlroot=request.url_root,
                                       title="SQL error", message=sql_error(err))
        elif not bird["user"]:
            controls += '''
            <button type="button" class="btn btn-success btn-sm" onclick='update_bird(%s,"claim");'>Claim bird</button>
            '''
            controls = controls % (bird['id'])
    if not(bird["alive"]) and set(['admin', 'manager']).intersection(permissions):
        controls += '''
        <button type="button" class="btn btn-info btn-sm" onclick='update_bird(%s,"alive");'>Mark bird as alive</button>
        '''
        controls = controls % (bird['id'])
    try:
        bprops, events = get_bird_properties(bird, user, permissions)
    except Exception as err:
        return render_template("error.html", urlroot=request.url_root,
                               title="SQL error", message=sql_error(err))
    return render_template('bird.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Birds', permissions),
                           bird=bname, bprops=bprops, events=events, controls=controls)


@app.route('/birds/location/<string:location>', methods=['GET'])
def birds_in_location(location):
    '''
    Search the database
    Search by key text.
    ---
    tags:
      - Search
    parameters:
      - in: path
        name: location
        schema:
          type: string
        required: true
        description: location
    responses:
      200:
          description: Database entries
      500:
          description: Error
    '''
    user, face, permissions = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    if not validate_user(user):
        return render_template("error.html", urlroot=request.url_root,
                               title="Unknown user", message="User %s is not registered" % user)
    result = initialize_result()
    ipd = receive_payload(result)
    ipd["stype"] = "sbl"
    ipd["location"] = location
    result["data"] = ""
    print(ipd)
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
                               title="Unknown user", message="User %s is not registered" % user)
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
                               title="Unknown user", message="User %s is not registered" % user)
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
    # OPTIONAL: move clutch to new nest
    #    controls += "<br>Move clutch to new nest " \
    #                + generate_nest_pulldown(["breeding", "fostering"], clutch["id"])
    auth = 1 if set(['admin', 'manager']).intersection(permissions) else 0
    cprops, birds = get_clutch_properties(clutch)
    birds += '<input type="hidden" id="clutch_id" value="%s">' % (clutch["id"])
    return render_template('clutch.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Clutches', permissions),
                           clutch=cname, cprops=cprops, birds=birds, controls=controls, auth=auth)


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
    if not set(['admin', 'edit', 'manager']).intersection(permissions):
        return render_template("error.html", urlroot=request.url_root,
                               title='Not permitted',
                               message="You don't have permission to register a new clutch")
    return render_template('newclutch.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Clutches', permissions),
                           start=date.today().strftime("%Y-%m-%d"),
                           stop=date.today().strftime("%Y-%m-%d"),
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
    return render_template('nest.html', urlroot=request.url_root, face=face,
                           dataset=app.config['DATASET'],
                           navbar=generate_navbar('Nests', permissions),
                           nest=nname, nest_id=nest['id'], nprops=nprops, birds=birds,
                           clutches=clutches, controls=controls, auth=auth)


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
    fheader = ['Location', 'Description', 'Number of birds']
    header = ['Location', 'Description', 'Number of birds']
    if rows:
        if set(['admin', 'manager']).intersection(permissions):
            header.append("Delete")
            template = '<tr class="open">' + ''.join("<td>%s</td>")*2 \
                       + ''.join('<td style="text-align: center">%s</td>'*2) + '</tr>'
        else:
            template = '<tr class="open">' + ''.join("<td>%s</td>")*(len(header)-1) \
                       + '<td style="text-align: center">%s</td></tr>'
        lochead = "<tr>" + "".join([f"<th>{itm}</th>" for itm in header]) + "</tr>"
        fileoutput = ''
        ftemplate = "\t".join(["%s"]*len(fheader)) + "\n"
        for row in rows:
            fileoutput += ftemplate % (row['display_name'], row['definition'], row['cnt'])
            if row["cnt"]:
                row["cnt"] = '<a href="/birds/location/%s">%s</a>' \
                             % (row['display_name'], row['cnt'])
            delcol = ""
            if row['cnt'] == 0:
                delcol = '<a href="#" onclick="delete_location(' + str(row['id']) \
                         + ');"><i class="fa-solid fa-trash-can fa-lg" style="color:red"></i></a>'
            if set(['admin', 'manager']).intersection(permissions):
                locrows += template % (row['display_name'], row['definition'], row['cnt'], delcol)
            else:
                locrows += template % (row['display_name'], row['definition'], row['cnt'])
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


@app.route('/searchlist')
def show_search_form():
    ''' Make an assignment for a project
    '''
    user, face, _ = get_user_profile()
    if not user:
        return redirect(app.config['AUTH_URL'] + "?redirect=" + request.url_root)
    try:
        return render_template('search.html', urlroot=request.url_root, face=face,
                               dataset=app.config['DATASET'], navbar=generate_navbar('Search'),
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
    return generate_response(result)


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
    Return rows from  a specified view/table. The caller can filter on any of the
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
            bind = (bird_id)
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
            bind = (bird_id)
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
    '''
    result = initialize_result()
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
    if not check_permission(result["rest"]["user"], ["admin", "edit", 'manager']):
        raise InvalidUsage("You don't have permission to claim a bird")
    result["rest"]["row_count"] = 0
    sql = "UPDATE bird SET user_id=(SELECT id FROM user WHERE name=%s) WHERE id=%s"
    try:
        bind = (result["rest"]["user"], bird_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
        log_bird_event(bird_id, status="claimed", user=result['rest']['user'], location_id=None)
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
    if not check_permission(result["rest"]["user"], ["admin", "edit", 'manager']):
        raise InvalidUsage("You don't have permission to report a bird as dead")
    result["rest"]["row_count"] = 0
    sql = "UPDATE bird SET alive=0,death_date=CURRENT_TIMESTAMP(),user_id=NULL WHERE id=%s"
    try:
        bind = (bird_id)
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
        bind = (bird_id)
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
        print(ipd)
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
        bind = (nest_id)
        g.c.execute(sql, bind)
        rows = g.c.fetchall()
        for row in rows:
            log_bird_event(row["id"], status="moved", user=result['rest']['user'],
                           location_id=location_id)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
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
        for row in rows:
            log_bird_event(row["id"], status="moved", user=result['rest']['user'],
                           location_id=location_id, nest_id=new_nest_id)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
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


if __name__ == '__main__':
    #app.run(ssl_context="adhoc", debug=app.config["DEBUG"])
    app.run(debug=True)
