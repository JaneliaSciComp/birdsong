''' Process a phenotype/genotype file and persist data in the database
    The input file (or picked version of it) has multiple colums that identify ther bird,
    phenotype measurement, and genetic marker data. Each row is a set of measurements for
    one bird. Requiremed columns are:
      1) Column name stored in BIRD_COL (typically "IND_ID")
      2) SEX ("M" or "F")
      3) Phenotype name (stored in ARG.PHENOTYPE)
      4) One or more marker columns, immediately following the phenotype name
    Example:
      IND_ID  SEX     MEDIAN_TEMPO    2       3       4       5
      1       M       6.69460301396   C/G     C/C     ./.     C/C
'''

import argparse
import os
import re
import socket
import sys
import colorlog
import MySQLdb
import pandas as pd
import requests
from tqdm import tqdm

# pylint: disable=R1710, W0703

# Configuration
CONFIG = {'config': {'url': os.environ.get('CONFIG_SERVER_URL')}}
BAND = {}
BIRD = {}
COLOR = {}
# General
BIRD_COL = "IND_ID" # Column name for bird
BDAY_COL = "IND_BD" # Column name for bird birth date
SEX_COL = "SEX" # Column name for bird sex
NEST_COL = "FAM_ID" # Column name for nest
SIRE_COL = "FATHER_ID"
DAMSEL_COL = "MOTHER_ID"
COUNT = {"missing": 0, "phenotype": 0, "processed": 0, "read": 0, "score": 0,
         "session": 0, "sex": 0, "state": 0, "birds": 0}
# Database
CONN = {}
CURSOR = {}
READ = {"BIRD": "SELECT name,sex FROM bird_vw WHERE id=%s",
        "SPECIES": "SELECT id FROM species WHERE common_name='%s'",
        "TERMS": "SELECT id,cv,cv_term FROM cv_term_vw where cv IN ('phenotype','genotype')"
       }
WRITE = {"BIRD": "INSERT INTO bird (species_id,name,band,location_id,sex,alive) VALUES "
                 + "(%s,%s,%s,getCVTermId('location',%s,''),%s,0)",
         "SESSION": "INSERT INTO session (name,type_id,bird_id,user_id) VALUES "
                    + "(%s,%s,%s,%s)",
         "SCORE": "INSERT INTO score (session_id,type_id,value) VALUES(%s,%s,%s)",
         "STATE": "INSERT INTO state (session_id,marker,state) VALUES (%s,%s,%s)"
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
        CURSOR['bird'].execute("SELECT id,name,band FROM bird")
        rows = CURSOR['bird'].fetchall()
    except Exception as err:
        sql_error(err)
    for row in rows:
        BAND[row['band']] = True
        BIRD[row['name']] = row['id']
    try:
        CURSOR['bird'].execute("SELECT display_name,cv_term FROM cv_term_vw WHERE cv='color'")
        rows = CURSOR['bird'].fetchall()
    except Exception as err:
        sql_error(err)
    for row in rows:
        COLOR[row['display_name']] = row['cv_term']
    COLOR['g'] = 'green'


def get_terms():
    """ Get genotype and phenotype CV term IDs
        Keyword arguments:
          None
        Returns:
          Dictionary of CV term IDs
    """
    term = {}
    try:
        CURSOR['bird'].execute(READ["TERMS"])
        rows = CURSOR['bird'].fetchall()
    except Exception as err:
        sql_error(err)
    for row in rows:
        if row["cv"] not in term:
            term[row["cv"]] = {}
        term[row["cv"]][row["cv_term"]] = row["id"]
    return term


def convert_band(iband):
    """ Given an abbrefiated color band, convert the colors to the full name
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


def valid_bird(row):
    """ Determine if a bird is valid (must exist in db and sex must match)
        Keyword arguments:
          row: row from input file
        Returns:
          True or False
    """
    iband = row[BIRD_COL]
    band = convert_band(iband)
    if band not in BAND:
        COUNT["missing"] += 1
        LOGGER.error("Band %s is not in database", iband)
        return False
    field = row[BDAY_COL].split("/")
    fdate = "".join([field[2], field[0], field[1]])
    name = "_".join([fdate, band])
    if name not in BIRD:
        COUNT["missing"] += 1
        LOGGER.error("Bird %s is not in database", name)
        return False
    row[BIRD_COL] = bid = BIRD[name]
    try:
        LOGGER.debug(READ["BIRD"], bid)
        CURSOR['bird'].execute(READ["BIRD"] % (bid,))
        bird = CURSOR['bird'].fetchone()
    except Exception as err:
        sql_error(err)
    if not bird:
        COUNT["missing"] += 1
        LOGGER.error("Bird ID %s is unknown", bid)
        return False
    if row["SEX"] != bird["sex"]:
        COUNT["sex"] += 1
        LOGGER.warning("Sex mismatch for %s (%s)", bird['name'], bid)
        return False
    return True


def process_phenotype(row, term):
    """ Process a single phenotype for one bird. This will insert one session and one score.
        Keyword arguments:
          row: row from input file
          term: term dictionary
        Returns:
          None
    """
    bid = row[BIRD_COL]
    bind = (bid, term["phenotype"][ARG.PHENOTYPE.lower()], bid, 2)
    LOGGER.debug(WRITE["SESSION"], bind)
    try:
        CURSOR['bird'].execute(WRITE["SESSION"] % bind)
        session_id = CURSOR['bird'].lastrowid
        COUNT["session"] += 1
    except Exception as err:
        sql_error(err)
    bind = (session_id, term["phenotype"][ARG.PHENOTYPE.lower()], row[ARG.PHENOTYPE.upper()])
    good_val = False
    val = row[ARG.PHENOTYPE.upper()]
    try:
        float(val)
        good_val = True
    except ValueError:
        LOGGER.warning("Invalid %s (%s) for bird ID %s", ARG.PHENOTYPE.upper(), val, bid)
        COUNT["phenotype"] += 1
    if good_val:
        LOGGER.debug(WRITE["SCORE"], bind)
        try:
            CURSOR['bird'].execute(WRITE["SCORE"], bind)
            COUNT["score"] += 1
        except Exception as err:
            sql_error(err)


def process_genotype(row, term, name, first_marker):
    """ Process a single phenotype for one bird. This will insert one session and one state.
        Keyword arguments:
          row: row from input file
          term: term dictionary
          name: list of column names
          first_marker: number of first marker column
        Returns:
          None
    """
    bid = row[BIRD_COL]
    bind = (bid, term["genotype"]["allelic_state"], bid, 2)
    LOGGER.debug(WRITE["SESSION"], bind)
    try:
        CURSOR['bird'].execute(WRITE["SESSION"], bind)
        session_id = CURSOR['bird'].lastrowid
        COUNT["session"] += 1
    except Exception as err:
        sql_error(err)
    for col in range(first_marker, len(row)):
        bind = (session_id, name[col], row[name[col]])
        LOGGER.debug(WRITE["STATE"], bind)
        try:
            CURSOR['bird'].execute(WRITE["STATE"], bind)
            COUNT["state"] += 1
        except Exception as err:
            sql_error(err)


def perform_analysis(dfr):
    """ Analyze dataframe
        Keyword arguments:
          dfr: dataframe
        Returns:
          None
    """
    name = list(dfr.columns)
    #PLUG
    #if ARG.PHENOTYPE.upper() not in name:
    #    terminate_program(f"Phenotype {ARG.PHENOTYPE} is not in the data")
    #first_marker = name.index(ARG.PHENOTYPE.upper()) + 1
    first_marker = name.index("SEX") + 1 #PLUG
    LOGGER.info("Markers: %d", (len(name) - first_marker))
    term = get_terms()
    for _, row in tqdm(dfr.iterrows(), total=dfr.shape[0]):
        COUNT["read"] += 1
        if not valid_bird(row):
            continue
        COUNT["processed"] += 1
        #process_phenotype(row, term)
        process_genotype(row, term, name, first_marker)


def perform_load(dfr):
    """ Analyze dataframe
        Keyword arguments:
          dfr: dataframe
        Returns:
          None
    """
    bird = {}
    try:
        CURSOR['bird'].execute(READ["SPECIES"] % (ARG.SPECIES,))
        species = CURSOR['bird'].fetchone()
    except Exception as err:
        sql_error(err)
    # Sire/damsel check
    for _, row in tqdm(dfr.iterrows(), total=dfr.shape[0], desc="Bird check"):
        bird[row[BDAY_COL]] = 1
    parent_err = {}
    for _, row in tqdm(dfr.iterrows(), total=dfr.shape[0], desc="Sire/damsel check"):
        if row[SIRE_COL] not in bird:
            parent_err[row[SIRE_COL]] = 1
        if row[DAMSEL_COL] not in bird:
            parent_err[row[DAMSEL_COL]] = 1
    for _, row in tqdm(dfr.iterrows(), total=dfr.shape[0], desc="Birds"):
        COUNT["read"] += 1
        field = row[BDAY_COL].split("/")
        bday = "".join([field[2], field[0], field[1]])
        bname = "_".join([bday, row[BIRD_COL]])
        if bname in bird:
            continue
        if row[SIRE_COL] in parent_err or row[DAMSEL_COL] in parent_err:
            LOGGER.error("Unknown sire/damsel for %s", row[BIRD_COL])
            continue
        loc = row[NEST_COL].split("_")[0]
        if loc in ["inb", "inbrd", "0"]:
            continue
        sex = row[SEX_COL] if row[SEX_COL] in ["F", "M"] else ""
        bind = (species["id"], bname, row[BIRD_COL], loc, sex)
        LOGGER.debug(WRITE["BIRD"], species["id"], bname, row[BIRD_COL], loc, sex)
        try:
            CURSOR['bird'].execute(WRITE["BIRD"], bind)
            bird[bname] = CURSOR["bird"].lastrowid
            COUNT["birds"] += 1
        except Exception as err:
            sql_error(err)


def process_data_frame():
    """ Read CSV or pickle file in to a dataframe, then process it.
        If we read in a CSV file, save it as a pickle.
        Keyword arguments:
          None
        Returns:
          None
    """
    print(f"Processing {ARG.FILE} for phenotype {ARG.PHENOTYPE.lower()}")
    LOGGER.info("Reading %s", ARG.FILE)
    if ARG.FILE.endswith(".pk") or ARG.FILE.endswith(".pkl"):
        dfr = pd.read_pickle(ARG.FILE)
    else:
        dfr = pd.read_csv(ARG.FILE, header=0, delimiter="\t")
        newname = ARG.FILE.replace("." + ARG.FILE.split(".")[-1], ".pkl")
        if newname == ARG.FILE:
            newname += ".pkl"
        LOGGER.info("Saving dataframe to %s", newname)
        dfr.to_pickle(newname)
    LOGGER.info("Dimensions: %dx%d", dfr.shape[0], dfr.shape[1])
    LOGGER.info("Birds: %d", len(dfr[BIRD_COL].unique()))
    if ARG.MODE == "analysis":
        perform_analysis(dfr)
    else:
        perform_load(dfr)
    if ARG.WRITE:
        CONN['bird'].commit()
    print(f"Birds read:         {COUNT['read']}")
    print(f"Birds not in db:    {COUNT['missing']}")
    print(f"Sex mismatch:       {COUNT['sex']}")
    print(f"Birds processed:    {COUNT['processed']}")
    if ARG.MODE == "analysis":
        print(f"Sessions written:   {COUNT['session']}")
        print(f"Scores written:     {COUNT['score']}")
        print(f"Invalid phenotypes: {COUNT['phenotype']}")
        print(f"States written:     {COUNT['state']}")
    else:
        print(f"Birds written:      {COUNT['birds']}")


# *****************************************************************************

if __name__ == '__main__':
    PARSER = argparse.ArgumentParser(description="Load allelic states")
    PARSER.add_argument('--file', dest='FILE', action='store',
                        help='File', required=True)
    PARSER.add_argument('--mode', dest='MODE', action='store',
                        default='analysis', choices=["analysis", "bird"],
                        help='Mode [analysis]')
    PARSER.add_argument('--species', dest='SPECIES', action='store',
                        default='Bengalese finch', help='Species [Bengalese finch]')
    PARSER.add_argument('--phenotype', dest='PHENOTYPE', action='store',
                        default='median_tempo', help='Phenotype [median_tempo]')
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
