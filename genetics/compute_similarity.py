import argparse
import os
import re
import sys
import colorlog
import MySQLdb
import pandas as pd
import requests
from tqdm import tqdm

# Configuration
CONFIG = {'config': {'url': os.environ.get('CONFIG_SERVER_URL')}}
# General
BIRD_COL = "IND_ID" # Column name for bird
BDAY_COL = "IND_BD" # Column name for bird birth date
SEX_COL = "SEX" # Column name for bird sex
NEST_COL = "FAM_ID" # Column name for nest
SIRE_COL = "FATHER_ID"
DAMSEL_COL = "MOTHER_ID"
FRAME = {}
COLOR = {}
COUNT = {"missing": 0, "phenotype": 0, "processed": 0, "read": 0, "score": 0,
         "session": 0, "sex": 0, "state": 0, "birds": 0}
# Database
CONN = {}
CURSOR = {}


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
        CURSOR['bird'].execute("SELECT id,name,band FROM bird")
        rows = CURSOR['bird'].fetchall()
    except Exception as err:
        sql_error(err)
    try:
        CURSOR['bird'].execute("SELECT display_name,cv_term FROM cv_term_vw WHERE cv='color'")
        rows = CURSOR['bird'].fetchall()
    except Exception as err:
        sql_error(err)
    for row in rows:
        COLOR[row['display_name']] = row['cv_term']
    COLOR['g'] = 'green'
    COLOR['yw'] = 'yellow'


def compute_distance(row1, row2):
    score = 0.0
    name = FRAME['NAME']
    first_marker = FRAME['FIRST_MARKER']
    for col in range(first_marker, row1.shape[1]):
        val1 = row1[name[col]].iloc[0]
        val2 = row2[name[col]].iloc[0]
        if (val1 == val2) and (val1 != "./."):
            score += 1
        else:
            v1l = val1.split("/")
            v2l = val2.split("/")
            if v1l[0] in v2l or v1l[1] in v2l:
                score += 0.5
    return score


def convert_band(iband):
    """ Given an abbreviated color band, convert the colors to the full name
        Keyword arguments:
          iband: input band
        Returns:
          Full-color band
    """
    band = ""
    field = re.findall(r"([a-z]+|\d+)", iband)
    if len(field) != 4:
        return None
    if field[0] in COLOR:
        band = COLOR[field[0]]
    else:
        terminate_program(f"Unknown color abbreviation {field[0]}")
    band += field[1]
    if field[2] in COLOR:
        band += COLOR[field[2]]
    else:
        terminate_program(f"Unknown color abbreviation {field[2]}")
    band += field[3]
    return band


def get_full_name(row, bird):
    bday = row[BDAY_COL].iloc[0]
    field = bday.split("/")
    bday = "".join([field[2], field[0], field[1]])
    fband = convert_band(bird)
    if not fband:
        return None
    full = "_".join([bday, fband])
    return full


def process_data_frame():
    """ Read pickle file in to a dataframe, then process it.
        Keyword arguments:
          None
        Returns:
          None
    """
    allow = ('20120212_red2purple22', '20120912_pink25green17',  '20120912_pink30green69',  '20120912_pink69green86', 
             '20120913_pink73green83', '20120917_pink16green20', '20140929_red68purple63',  '20141122_red21green44',
             '20150817_red97purple74', '20151017_red49purple81', '20151017_red50purple82',  '20181104_red7purple89',
             '20181104_red8purple90', '20191206_red91purple65',  '20191206_red92purple66',  '20191206_red94purple68', 
             '20191206_red95purple69')
    allow = ('20191206_red91purple65', '20191206_red92purple66', '20191206_red94purple68', '20191206_red95purple69')
    print(f"Processing {ARG.FILE}")
    LOGGER.info("Reading %s", ARG.FILE)
    dfr = pd.read_pickle(ARG.FILE)
    LOGGER.info("Dimensions: %dx%d", dfr.shape[0], dfr.shape[1])
    LOGGER.info("Birds: %d", len(dfr[BIRD_COL].unique()))
    FRAME['NAME'] = list(dfr.columns)
    FRAME['FIRST_MARKER'] = FRAME['NAME'].index("SEX") + 1
    birdlist = dfr[BIRD_COL].tolist()
    processed = {}
    for bird1 in birdlist:
        row1 = dfr.loc[dfr[BIRD_COL] == bird1]
        full1 = get_full_name(row1, bird1)
        if not full1 or (full1 not in allow):
            continue
        #LOGGER.info("Dimensions: %dx%d", row1.shape[0], row1.shape[1])
        #LOGGER.info("Birds: %d", len(row1[BIRD_COL].unique()))
        for bird2 in birdlist:
            row2 = dfr.loc[dfr[BIRD_COL] == bird2]
            if bird1 == bird2 or bird2 in processed:
                continue
            full2 = get_full_name(row2, bird2)
            if not full2 or (full2 not in allow):
                continue
            score = compute_distance(row1, row2)
            print(f"{full1} x {full2} = {score}")
        processed[bird1] = True



    # *****************************************************************************

if __name__ == '__main__':
    PARSER = argparse.ArgumentParser(description="Load allelic states")
    PARSER.add_argument('--file', dest='FILE', action='store',
                        help='File', required=True)
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
    process_data_frame()
    sys.exit(0)
