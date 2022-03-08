''' birdsong_utilities.py
    Birdsong manager utilities
'''

import random
import re
import string
from urllib.parse import parse_qs
from flask import g
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


def generate_sql(request, result, sql, query=False):
    ''' Generate a SQL statement and tuple of associated bind variables.
        Keyword arguments:
          request: API request
          result: result dictionary
          sql: base SQL statement
          query: uses "id" column if true
    '''
    bind = ()
    # pylint: disable=W0603
    idcolumn = 0
    query_string = 'id='+str(query) if query else request.query_string
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
                varr = val[0].split(',')
                if 'id' in varr:
                    idcolumn = 1
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
    return sql, bind, idcolumn


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
          name: bird name
          band: bird band
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
    band = "".join([nest['band'][0:2], ipd["number1"], nest['band'][-2:], ipd["number2"]])
    color1 = color[nest['band'][0:2]]
    color2 = color[nest['band'][-2:]]
    name = "".join([ipd["start_date"].replace("-", ""), "_", color1, ipd["number1"],
                    color2, ipd["number2"]])
    # Location
    try:
        g.c.execute("SELECT location_id FROM bird WHERE id=%s", (nest["sire_id"],))
        row = g.c.fetchone()
        loc_id = row["location_id"]
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    return name, band, nest, loc_id


def get_key_type_id(key_type):
    ''' Determine the ID for a key type
        Keyword arguments:
          key_type: key type
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


def get_workday(janelia_id):
    ''' Given a Janelia ID, return the Workday record
        Keyword arguments:
          janelia_id: Janelia ID
        Returns:
          Workday record
    '''
    data = call_responder('config', 'config/workday/' + janelia_id)
    if not data:
        raise InvalidUsage('User %s not found in Workday' % (janelia_id))
    work = data['config']
    return work


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
    '''
    stmt = "SELECT * FROM user_vw WHERE name=%s OR janelia_id=%s"
    try:
        g.c.execute(stmt, (user, user))
        usr = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500)
    return bool(usr)
