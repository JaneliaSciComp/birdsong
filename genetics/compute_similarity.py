import argparse
import os
import socket
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
PROCESSED = {}
RELATIONSHIP = {}
SESSION = {}
COUNT = {"comparisons": 0, "potential": 0, "removed": 0, "present": 0}
# Database
CONN = {}
CURSOR = {}
READ = {"SESSION": "SELECT id FROM session_vw WHERE cv='Genotype' AND "
                   + "type='Allelic state' AND bird=%s ORDER BY create_date DESC LIMIT 1"
       }
WRITE = {"COMPARE": "INSERT IGNORE INTO bird_comparison (bird1_id,bird1_session_id,"
                    + "comparison_id,bird2_id,bird2_session_id,value) "
                    + "VALUES (%s,%s,getCvTermId('bird_comparison','%s',''),"
                    + "%s,%s,%s)"
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
            req = requests.post(url, headers=headers, json=payload, timeout=10)
        else:
            req = requests.get(url, timeout=10)
    except requests.exceptions.RequestException as err:
        terminate_program(err)
    if req.status_code != 200:
        terminate_program(f"Status: {str(req.status_code)}")
    return req.json()


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
    except MySQLdb.Error as err:
        sql_error(err)
    return conn, cursor


def make_comparison_key(arr):
    return "_".join([str(elem) for elem in arr])

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
    try:
        CURSOR['bird'].execute("SELECT subject,type,object FROM bird_relationship_vw")
        rows = CURSOR['bird'].fetchall()
    except Exception as err:
        sql_error(err)
    for row in rows:
        if row["subject"] not in RELATIONSHIP:
            RELATIONSHIP[row["subject"]] = {}
        RELATIONSHIP[row["subject"]][row["object"]] = row["type"]
    # Get previously processed comparisons
    try:
        CURSOR['bird'].execute("SELECT * FROM bird_comparison")
        rows = CURSOR['bird'].fetchall()
    except Exception as err:
        sql_error(err)
    for row in rows:
        key = make_comparison_key([row["bird1_id"], row["bird1_session_id"],
                                   row["bird2_id"], row["bird2_session_id"]])
        PROCESSED[key] = True


def compute_distance(row1, row2):
    score = seqscore = 0.0
    seqcount = 0
    name = FRAME['NAME']
    first_marker = FRAME['FIRST_MARKER']
    markers = range(first_marker, row1.shape[1])
    for col in markers:
        val1 = row1[name[col]].iloc[0]
        val2 = row2[name[col]].iloc[0]
        if (val1 == val2) and (val1 != "./."):
            score += 1
        else:
            v1l = val1.split("/")
            v2l = val2.split("/")
            if v1l[0] in v2l or v1l[1] in v2l:
                score += 0.5
        if val1 != "./." and val2 != "./.":
            seqcount += 1
            if val1 == val2:
                seqscore += 1
    return score / len(markers) * 100.0, seqscore / seqcount * 100.0


def get_session(bird):
    if bird in SESSION:
        return SESSION[bird]
    try:
        CURSOR['bird'].execute(READ["SESSION"], [bird])
        sid = CURSOR['bird'].fetchone()
    except Exception as err:
        sql_error(err)
    if not sid:
        terminate_program(f"No allelic state session for {bird}")
    SESSION[bird] = sid["id"]
    return SESSION[bird]


def compare_birds(row1, row2, id1, session1, full1, phen1, results):
    full2 = row2["IND_NAME"].iloc[0]
    id2 = row2[BIRD_COL].iloc[0]
    session2 = get_session(full2)
    phen2 = row2["MEDIAN_TEMPO"].iloc[0] or "-"
    if full2 < full1:
        return
        id1, full1, session1, phen1 = id2, full2, session2, phen2
    COUNT["potential"] += 1
    if make_comparison_key([id1, session1, id2, session2]) in PROCESSED:
        COUNT["present"] += 1
        return
    COUNT["comparisons"] += 1
    allm, seqm = compute_distance(row1, row2)
    relate = ""
    if full1 in RELATIONSHIP and full2 in RELATIONSHIP[full1]:
        relate = f"\t{RELATIONSHIP[full1][full2]}"
    results.append(f"{full1}\t{full2}\t{phen1}\t{phen2}\t{allm:.2f}%\t{seqm:.2f}%{relate}")
    try:
        CURSOR['bird'].execute(WRITE["COMPARE"] % (id1,session1,"allele_match_all",
                                                   id2,session2,allm))
    except Exception as err:
        LOGGER.error("Could not insert allele_match_all for %s<->%s", id1, id2)
        LOGGER.error("Could not insert %s for %s<->%s", 'this', id1, id2)
        sql_error(err)
    try:
        CURSOR['bird'].execute(WRITE["COMPARE"] % (id1,session1,"allele_match_seq",
                                                   id2,session2,seqm))
    except Exception as err:
        LOGGER.error("Could not insert allele_match_seq for %s<->%s", id1, id2)
        LOGGER.error("Could not insert %s for %s<->%s", 'this', id1, id2)
        sql_error(err)
    CONN['bird'].commit()


def process_data_frame():
    """ Read pickle file in to a dataframe, then process it.
        Keyword arguments:
          None
        Returns:
          None
    """
    allow = ['20140922_purple35white17', '20150422_black97black14',
             '20180108_blue5white83', '20180108_blue10white86',
             '20180108_blue7white84', '20180410_blue9white89',
             '20180410_blue8white88', '20180410_blue10white90',
             '20180410_blue7white87', '20180730_blue7white26',
             '20180730_blue8white27', '20180730_blue11white30',
             '20180730_blue10white29', '20180730_blue9white28',
             '20181201_blue83white85', '20181201_blue81white2',
             '20181201_blue82white76', '20190224_blue21white37',
             '20190224_blue27white40', '20190224_blue25white38',
             '20190606_blue9white69', '20190606_blue8white68',
             '20190606_blue10white70', '20190606_blue7white67',
             '20120913_pink73green83', '20120917_pink16green20',
             '20140929_red68purple63',  '20141122_red21green44',
             '20191115_orange75orange57', '20191115_orange77orange59',
             '20161229_purple95black62',
             '20191009_red7green100', '20191009_red1green2',
             '20191009_red4green58', '20191009_red6green98',
             '20191009_red3green54', '20120725_red30green6',
             '20161227_orange74black35', '20080823_black1black3', '20120328_black27black66']
    print(f"Processing {ARG.FILE}")
    allow = []
    LOGGER.info("Reading %s", ARG.FILE)
    dfr = pd.read_pickle(ARG.FILE)
    dfr.sort_values(by="IND_NAME", inplace=True)
    LOGGER.info("Dimensions: %dx%d", dfr.shape[0], dfr.shape[1])
    LOGGER.info("Birds: %d", len(dfr[BIRD_COL].unique()))
    FRAME['NAME'] = list(dfr.columns)
    FRAME['FIRST_MARKER'] = FRAME['NAME'].index(SEX_COL) + 2
    birdlist = dfr[BIRD_COL].tolist()
    birdlist2 = birdlist[:]
    if allow:
        LOGGER.info("Sample birds: %s", len(allow))
        max_results = int((len(allow) - 1) * (len(allow)) / 2)
    else:
        max_results = int((len(birdlist) - 1) * (len(birdlist)) / 2)
    LOGGER.info("Running %d comparisons", max_results)
    results = ["Bird1\tBird2\tPhenotype1\tPhenotype2\tAll markers\tSequenced markers\tRelationship"]
    for bird1 in tqdm(birdlist, desc="Primary", position=0):
        row1 = dfr.loc[dfr[BIRD_COL] == bird1]
        full1 = row1["IND_NAME"].iloc[0]
        if ARG.SINGLE and (ARG.SINGLE != full1):
            continue
        birdlist2.remove(bird1)
        if not full1 or (allow and (full1 not in allow)):
            COUNT["removed"] += 1
            continue
        id1 = row1[BIRD_COL].iloc[0]
        phen1 = row1["MEDIAN_TEMPO"].iloc[0]
        session1 = get_session(full1)
        for bird2 in tqdm(birdlist2, desc="Secondary", position=1, leave=False):
            row2 = dfr.loc[dfr[BIRD_COL] == bird2]
            full2 = row2["IND_NAME"].iloc[0]
            if (not full2) or (allow and (full2 not in allow)):
                if full2 in allow:
                    birdlist2.remove(bird2)
                continue
            compare_birds(row1, row2, id1, session1, full1, phen1, results)
    print(f"{len(results)-1}/{max_results} results")
    if len(results) > 1:
        with open("analysis_results.tsv", "w", encoding="ascii") as output:
            output.write("\n".join(results) + "\n")
    print(COUNT)


    # *****************************************************************************

if __name__ == '__main__':
    PARSER = argparse.ArgumentParser(description="Load allelic states")
    PARSER.add_argument('--file', dest='FILE', action='store',
                        help='File', required=True)
    PARSER.add_argument('--single', dest='SINGLE', action='store',
                        help='Single bird to process',)
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
