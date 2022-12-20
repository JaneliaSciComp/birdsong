import argparse
import os
import re
import shutil
import sys
import colorlog
import MySQLdb
import requests


# Configuration
CONFIG = {'config': {'url': os.environ.get('CONFIG_SERVER_URL')}}
COLOR = {}
DUPLICATES = ["bk96bk97", "bk98bk99", "pk30", "pu13y5", "pu51bk65", "r25w57"]
# Database
CONN = {}
CURSOR = {}
READ = {"BAND": "SELECT name,sex FROM bird WHERE band=%s",
       }

def terminate_program(msg=None):
    """ Log an optional error to output, close files, and exit
        Keyword arguments:
          err: error message
        Returns:
           None
    """
    if msg:
        LOGGER.critical(msg)
    sys.exit(-1 if msg else 0)


def call_responder(server, endpoint, payload=''):
    ''' Call a responder
        Keyword arguments:
          server: server
          endpoint: REST endpoint
          payload: payload for POST requests
        Returns:
          JSON response
    '''
    url = CONFIG[server]['url'] + endpoint
    try:
        if payload:
            headers = {"Content-Type": "application/json",
                       "Accept": 'application/json',
                       "host": socket.gethostname()}
            req = requests.post(url, headers=headers, json=payload)
        else:
            req = requests.get(url)
    except requests.exceptions.RequestException as err:
        terminate_program(err)
    if req.status_code == 200:
        return req.json()
    terminate_program(f"Status: {str(req.status_code)}")


def sql_error(err):
    """ Log a critical SQL error and exit
        Keyword arguments:
          err: error message
        Returns:
           None
    """
    try:
        msg = f"MySQL error [{err.args[0]}]: {err.args[1]}"
    except IndexError:
        msg = f"MySQL error: {err}"
    terminate_program(msg)


def db_connect(dbd):
    """ Connect to a database
        Keyword arguments:
          dbd: database dictionary
        Returns:
          connection
          cursor
    """
    LOGGER.info("Connecting to %s on %s", dbd['name'], dbd['host'])
    try:
        conn = MySQLdb.connect(host=dbd['host'], user=dbd['user'],
                               passwd=dbd['password'], db=dbd['name'])
    except MySQLdb.Error as err:
        sql_error(err)
    try:
        cursor = conn.cursor(MySQLdb.cursors.DictCursor)
        return conn, cursor
    except MySQLdb.Error as err:
        sql_error(err)


def initialize_program():
    """ Initialize the program
        Keyword arguments:
          None
        Returns:
          None
    """
    global CONFIG # pylint: disable=W0603
    data = call_responder('config', 'config/rest_services')
    CONFIG = data['config']
    data = call_responder('config', 'config/db_config')
    (CONN['bird'], CURSOR['bird']) = db_connect(data['config']['birdsong'][ARG.MANIFOLD])
    try:
        CURSOR['bird'].execute("SELECT display_name,cv_term FROM cv_term_vw WHERE cv='color'")
        rows = CURSOR['bird'].fetchall()
    except Exception as err:
        sql_error(err)
    for row in rows:
        COLOR[row['display_name']] = row['cv_term'] # Use full name
        COLOR[row['display_name']] = row['display_name'] # Use abbreviation
    COLOR['g'] = 'green'
    COLOR['o'] = 'orange'
    COLOR['r'] = 'red'
    COLOR['w'] = 'white'
    COLOR['wt'] = 'white'
    COLOR['y'] = 'yellow'
    COLOR['yw'] = 'yellow'
    #
    COLOR['g'] = 'gr'
    COLOR['o'] = 'or'
    COLOR['r'] = 'rd'
    COLOR['w'] = 'wh'
    COLOR['wt'] = 'wh'
    COLOR['yw'] = 'ye'
    COLOR['y'] = 'ye'


def convert_band(iband):
    """ Given an abbrefiated color band, convert the colors to the full name
        Keyword arguments:
          iband: input band
        Returns:
          Full-color band
    """
    band = sex = ""
    if "-" in iband:
        try:
            iband, sex = iband.split("-", 2)
        except ValueError:
            return None, None
    field = re.findall(r"([a-z]+|\d+)", iband)
    if len(field) != 4:
        return None, None
    if field[0] in COLOR:
        band = COLOR[field[0]]
    else:
        return None, None
        terminate_program(f"Unknown color abbreviation {field[0]}")
    band += field[1]
    if field[2] in COLOR:
        band += COLOR[field[2]]
    else:
        return None, None
        terminate_program(f"Unknown color abbreviation {field[2]}")
    band += field[3]
    return band, sex


def process_directories():
    for top in ("egret_screening_1", "egret_screening_2", "stork_screening"):
        dbase = "/".join([ARG.BASE, top])
        for bdir in os.listdir(dbase):
            if bdir in DUPLICATES:
                LOGGER.warning("Skip duplicated band %s", bdir)
                continue
            tband, sex = convert_band(bdir)
            if not tband:
                continue
            try:
                CURSOR['bird'].execute(READ['BAND'], (tband,))
                rows = CURSOR['bird'].fetchall()
            except Exception as err:
                sql_error(err)
            if not len(rows):
                LOGGER.warning("%s is not in database", tband)
                continue
            if len(rows) != 1:
                LOGGER.error("More than one bird for band %s", tband)
                continue
            if sex:
                if (sex == "male" and rows[0]['sex'] != "M") \
                   or (sex == "fem" and rows[0]['sex'] != "F") \
                   or (rows[0]['sex'] == "U"):
                   LOGGER.error("Sex mismatch for %s (%s %s)", bdir, sex, rows[0]['sex'])
                   continue
            bpath = "/".join([dbase, bdir])
            newpath = "/".join([ARG.BASE, "analysis", rows[0]['name']])
            print(f"Move {bpath} to {newpath}")
            if not ARG.WRITE:
                continue
            try:
                shutil.move(bpath, newpath)
            except Exception as err:
                terminate_program(err)

# *****************************************************************************

if __name__ == '__main__':
    PARSER = argparse.ArgumentParser(description="Load allelic states")
    PARSER.add_argument('--base', dest='BASE', action='store',
                        default="/Volumes/karpova/data/birdsong",
                        help='Base directory')
    PARSER.add_argument('--manifold', dest='MANIFOLD', action='store',
                        default='dev', choices=["dev", "prod"],
                        help='Manifold')
    PARSER.add_argument('--write', dest='WRITE', action='store_true',
                        default=False, help='Write to database')
    PARSER.add_argument('--verbose', dest='VERBOSE', action='store_true',
                        default=False, help='Flag, Chatty')
    PARSER.add_argument('--debug', dest='DEBUG', action='store_true',
                        default=False, help='Flag, Very chatty')
    ARG = PARSER.parse_args()
    LOGGER = colorlog.getLogger()
    ATTR = colorlog.colorlog.logging if "colorlog" in dir(colorlog) else colorlog
    if ARG.DEBUG:
        LOGGER.setLevel(ATTR.DEBUG)
    elif ARG.VERBOSE:
        LOGGER.setLevel(ATTR.INFO)
    else:
        LOGGER.setLevel(ATTR.WARNING)
    HANDLER = colorlog.StreamHandler()
    HANDLER.setFormatter(colorlog.ColoredFormatter())
    LOGGER.addHandler(HANDLER)

    initialize_program()
    process_directories()
