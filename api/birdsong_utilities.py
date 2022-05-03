''' birdsong_utilities.py
    Birdsong manager utilities
'''

from datetime import datetime
import random
import re
import string
from urllib.parse import parse_qs
from flask import g, request
import requests

CONFIG = {'config': {"url": "http://config.int.janelia.org/"}}
BEARER = ""
KEY_TYPE_IDS = {}

# *****************************************************************************
# * Classes                                                                   *
# *****************************************************************************
class InvalidUsage(Exception):
    ''' Return an error response
    '''
    status_code = 400

    def __init__(self, message, status_code=None, payload=None):
        Exception.__init__(self)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        ''' Build error response
        '''
        retval = dict(self.payload or ())
        retval['rest'] = {'error': self.message}
        return retval


# *****************************************************************************
# * Functions                                                                 *
# *****************************************************************************
def add_key_value_pair(key, val, separator, sql, bind):
    ''' Add a key/value pair to the WHERE clause of a SQL statement
        Keyword arguments:
          key: column
          value: value
          separator: logical separator (AND, OR)
          sql: SQL statement
          bind: bind tuple
    '''
    eprefix = ''
    if not isinstance(key, str):
        key = key.decode('utf-8')
    if re.search(r'[!><]$', key):
        match = re.search(r'[!><]$', key)
        eprefix = match.group(0)
        key = re.sub(r'[!><]$', '', key)
    if not isinstance(val[0], str):
        val[0] = val[0].decode('utf-8')
    if '*' in val[0]:
        val[0] = val[0].replace('*', '%')
        if eprefix == '!':
            eprefix = ' NOT'
        else:
            eprefix = ''
        sql += separator + ' ' + key + eprefix + ' LIKE %s'
    else:
        sql += separator + ' ' + key + eprefix + '=%s'
    bind = bind + (val,)
    return sql, bind


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


def call_responder(server, endpoint):
    ''' Call a responder
        Keyword arguments:
          server: server
          endpoint: REST endpoint
    '''
    if server not in CONFIG:
        raise Exception("Configuration key %s is not defined" % (server))
    url = CONFIG[server]['url'] + endpoint
    try:
        req = requests.get(url)
    except requests.exceptions.RequestException as err:
        print(err)
        raise err
    if req.status_code == 200:
        return req.json()
    print("Could not get response from %s: %s" % (url, req.text))
    #raise InvalidUsage("Could not get response from %s: %s" % (url, req.text))
    raise InvalidUsage(req.text, req.status_code)


def check_dates(ipd):
    ''' Ensure that start/stop dates are in sequence
        Keyword arguments:
          ipd: request payload
        Returns:
          None (or raised error for dates out of sequence)
    '''
    if "start_date" in ipd and "stop_date" in ipd:
        if ipd["start_date"] and ipd["stop_date"]:
            if ipd["stop_date"] < ipd["start_date"]:
                raise InvalidUsage("Stop date must be >= start date")


def check_permission(user, permission=None):
    ''' Validate that a user has a specified permission
        Keyword arguments:
          user: user name
          permission: single permission or list of permissions
        Returns::
          List of permissions if no permission is specified, otherwise True/False
    '''
    if not permission:
        stmt = "SELECT * FROM user_permission_vw WHERE name=%s"
        try:
            g.c.execute(stmt, (user))
            rows = g.c.fetchall()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
        perm = [row['permission'] for row in rows]
        return perm
    if type(permission).__name__ == 'str':
        permission = [permission]
    stmt = "SELECT * FROM user_permission_vw WHERE name=%s AND permission=%s"
    for per in permission:
        bind = (user, per)
        try:
            g.c.execute(stmt, bind)
            row = g.c.fetchone()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
        if row:
            return True
    return False


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


def generate_birdlist_table(rows, showall=True):
    ''' Given rows from bird_vw, return an HTML table
        Keyword arguments:
          rows: rows from database search
          showall: show all birds
        Returns:
          HTML table
    '''
    if rows:
        header = ['Name', 'Band', 'Nest', 'Location', 'Sex', 'Notes',
                  'Current age', 'Alive']
        if showall:
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
            if showall:
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
            if showall:
                outcol.insert(4, row["username"])
            birds += template % tuple(outcol)
        birds += "</tbody></table>"
        downloadable = create_downloadable('birds', header, ftemplate, fileoutput)
        birds = '<a class="btn btn-outline-info btn-sm" href="/download/%s" ' \
                % (downloadable) + 'role="button">Download table</a>' + birds
    else:
        birds = "No birds were found"
    return birds


def generate_clutchlist_table(rows):
    ''' Given rows from clutch_vw, return an HTML table
        Keyword arguments:
          rows: rows from database search
        Returns:
          HTML table
    '''
    if rows:
        header = ['Name', 'Nest', 'Clutch early', 'Clutch late', 'Bird count', 'Notes']
        clutches = '''
        <table id="clutches" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        clutches += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr class="open">' + ''.join("<td>%s</td>")*len(header) + "</tr>"
        fileoutput = ''
        ftemplate = "\t".join(["%s"]*len(header)) + "\n"
        for row in rows:
            cnt = get_clutch_or_nest_count(row["id"])
            fileoutput += ftemplate % (row['name'], row['nest'],
                                       strip_time(row['clutch_early']),
                                       strip_time(row['clutch_late']), cnt, row['notes'])
            nest = '<a href="/nest/%s">%s</a>' % tuple([row['nest']]*2)
            clutch = '<a href="/clutch/%s">%s</a>' % tuple([row['name']]*2)
            clutches += template % (clutch, nest, strip_time(row['clutch_early']),
                                    strip_time(row['clutch_late']), cnt, row['notes'])
        clutches += "</tbody></table>"
        downloadable = create_downloadable('clutches', header, ftemplate, fileoutput)
        clutches = f'<a class="btn btn-outline-info btn-sm" href="/download/{downloadable}" ' \
                   + 'role="button">Download table</a>' + clutches
    else:
        clutches = "No clutches were found"
    return clutches


def generate_nestlist_table(rows):
    ''' Given rows from nest_vw, return an HTML table
        Keyword arguments:
          rows: rows from database search
        Returns:
          HTML table
    '''
    if rows:
        header = ['Name', 'Band', 'Sire', 'Damsel', 'Bird count', 'Location', 'Notes']
        nests = '''
        <table id="nests" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        nests += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr class="open">' + ''.join("<td>%s</td>")*len(header) + "</tr>"
        fileoutput = ''
        ftemplate = "\t".join(["%s"]*len(header)) + "\n"
        for row in rows:
            cnt = get_clutch_or_nest_count(row["id"])
            fileoutput += ftemplate % (row['name'], row['band'], row['sire'],
                                       row['damsel'], cnt, row['location'], row['notes'])
            nest = '<a href="/nest/%s">%s</a>' % tuple([row['name']]*2)
            sire = '<a href="/bird/%s">%s</a>' % tuple([row['sire']]*2)
            damsel = '<a href="/bird/%s">%s</a>' % tuple([row['damsel']]*2)
            nests += template % (nest, row['band'], sire, damsel,
                                 cnt, row['location'], row['notes'])
        nests += "</tbody></table>"
        downloadable = create_downloadable('nests', header, ftemplate, fileoutput)
        nests = f'<a class="btn btn-outline-info btn-sm" href="/download/{downloadable}" ' \
                 + 'role="button">Download table</a>' + nests
    else:
        nests = "No nests were found"
    return nests


def execute_sql(result, sql, debug, container="data"):
    ''' Build and execute a SQL statement.
        Keyword arguments:
          result: result dictionary
          sql: base SQL statement
          debug:: debug flag
          container: name of dictionary in result disctionary to return rows
        Returns:
          True if successful
    '''
    sql, bind = generate_sql(result, sql)
    if debug: # pragma: no cover
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


def generate_sql(result, sql):
    ''' Generate a SQL statement and tuple of associated bind variables.
        Keyword arguments:
          result: result dictionary
          sql: base SQL statement
    '''
    bind = ()
    query_string = request.query_string
    order = ''
    if query_string:
        if not isinstance(query_string, str):
            query_string = query_string.decode('utf-8')
        ipd = parse_qs(query_string)
        separator = ' AND' if ' WHERE ' in sql else ' WHERE'
        for key, val in ipd.items():
            if key == '_sort':
                order = ' ORDER BY ' + val[0]
            elif key == '_columns':
                sql = sql.replace('*', val[0])
            elif key == '_distinct':
                if 'DISTINCT' not in sql:
                    sql = sql.replace('SELECT', 'SELECT DISTINCT')
            else:
                sql, bind = add_key_value_pair(key, val, separator, sql, bind)
                separator = ' AND'
    sql += order
    if bind:
        result['rest']['sql_statement'] = sql % bind
    else:
        result['rest']['sql_statement'] = sql
    return sql, bind


def get_banding(ipd):
    ''' Get banding and nest information
        Keyword arguments:
          ipd: request payload
        Returns:
          name: nest name
          band: nest band
    '''
    # Colors
    try:
        g.c.execute("SELECT display_name,cv_term FROM cv_term_vw WHERE cv='color'")
        rows = g.c.fetchall()
        color = {}
        for row in rows:
            color[row['cv_term']] = row['display_name']
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    name = "".join([ipd["start_date"].replace("-", ""), "_", ipd["color1"], ipd["color2"]])
    band = color[ipd["color1"]] + color[ipd["color2"]]
    return name, band


def get_banding_and_location(ipd):
    ''' Get banding, nest, and location information
        Keyword arguments:
          ipd: request payload
        Returns:
          band: list of bird names and band names
          nest: nest record
          loc_id: location ID
    '''
    # Colors
    try:
        g.c.execute("SELECT display_name,cv_term FROM cv_term_vw WHERE cv='color'")
        rows = g.c.fetchall()
        color = {}
        for row in rows:
            color[row['display_name']] = row['cv_term']
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    # Nest
    try:
        g.c.execute("SELECT * FROM nest WHERE id=%s", (ipd['nest_id'],))
        nest = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    # Location
    try:
        g.c.execute("SELECT location_id FROM bird WHERE id=%s", (nest["sire_id"],))
        row = g.c.fetchone()
        loc_id = row["location_id"]
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    # Bands
    band = []
    for barr in ipd['bands']:
        nband = "".join([nest['band'][0:2], barr[0], nest['band'][-2:], barr[1]])
        color1 = color[nest["band"][0:2]]
        color2 = color[nest["band"][-2:]]
        name = "".join([ipd["start_date"].replace("-", ""), "_", color1, barr[0],
                        color2, barr[1]])
        band.append({"name": name, "band": nband})
    return band, nest, loc_id


def get_clutch_or_nest_count(cnid, which="clutch"):
    ''' Return the number of birds in a clutch or nest
        Keyword arguments:
          cnid: clutch or nest ID
          ehich: "clutch" or "nest"
        Returns:
           Bird count
    '''
    try:
        sql = "SELECT COUNT(1) AS cnt FROM bird WHERE %s_id=%s" % (which, cnid)
        g.c.execute(sql)
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    return rows[0]["cnt"]


def get_key_type_id(key_type):
    ''' Determine the ID for a key type
        Keyword arguments:
          key_type: key type
        Returns:
          key type ID
    '''
    if key_type not in KEY_TYPE_IDS:
        try:
            g.c.execute("SELECT id,cv_term FROM cv_term_vw WHERE cv='key'")
            cv_terms = g.c.fetchall()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500)
        for term in cv_terms:
            KEY_TYPE_IDS[term['cv_term']] = term['id']
    return KEY_TYPE_IDS[key_type]


def get_user_by_name(uname):
    ''' Given a user name, return the user record
        Keyword arguments:
          uname: user name
        Returns:
          user record
    '''
    try:
        g.c.execute("SELECT * FROM user_vw WHERE name='%s'" % uname)
        row = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    return row


def random_string(strlen=8):
    ''' Generate a random string of letters and digits
        Keyword arguments:
          strlen: length of generated string
    '''
    components = string.ascii_letters + string.digits
    return ''.join(random.choice(components) for i in range(strlen))


def sql_error(err):
    ''' Given a MySQL error, return the error message
        Keyword arguments:
          err: MySQL error
    '''
    error_msg = ''
    try:
        error_msg = "MySQL error [%d]: %s" % (err.args[0], err.args[1])
    except IndexError:
        error_msg = "Error: %s" % err
    if error_msg:
        print(error_msg)
    return error_msg


def strip_time(ddt):
    ''' Return the date portion of a datetime
        Keyword arguments:
          ddt: datetime
        Returns:
          String date
    '''
    return ddt.strftime("%Y-%m-%d")


def update_property(pid, table, name, value):
    ''' Insert/update a property
        Keyword arguments:
          id: parent ID
          result: result dictionary
          table: parent table
          name: CV term
          value: value
    '''
    stmt = "INSERT INTO %s_property (%s_id,type_id,value) VALUES " \
           + "(!s,getCvTermId(!s,!s,NULL),!s) ON DUPLICATE KEY UPDATE value=!s"
    stmt = stmt % (table, table)
    stmt = stmt.replace('!s', '%s')
    bind = (pid, table, name, value, value)
    try:
        g.c.execute(stmt, bind)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)


def validate_user(user):
    ''' Validate a user
        Keyword arguments:
          user: user name or Janelia ID
        Returns:
          True or False
    '''
    stmt = "SELECT * FROM user_vw WHERE name=%s OR janelia_id=%s"
    try:
        g.c.execute(stmt, (user, user))
        usr = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    return bool(usr)
