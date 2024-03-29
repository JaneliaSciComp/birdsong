''' compute_similarity.py
    Compute similarity for birds
'''

import argparse
import json
import signal
import sys
import colorlog
import inquirer
import MySQLdb
import pandas as pd
from tqdm import tqdm

# pylint: disable=W0703, W0613

# General
BIRD_COL = "IND_ID" # Column name for bird
SEX_COL = "SEX" # Column name for bird sex
FRAME = {}
PROCESSED = {}
RELATIONSHIP = {}
SESSION = {}
WILL_LOAD = []
COUNT = {"skipped": 0, "potential": 0,"comparisons": 0, "removed": 0, "present": 0,
         "allele_match_all": 0, "allele_match_seq": 0}
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
    """ Join elements in a list to create a key.
        Keyword arguments:
          arr: list of birn names
        Returns:
          None
    """
    return "_".join([str(elem) for elem in arr])


def initialize_program():
    """ Initialize the program
        Keyword arguments:
          None
        Returns:
          None
    """
    with open("../birdsong_config.json", encoding="ascii") as jfile_obj:
        data = json.load(jfile_obj)
    (CONN['bird'], CURSOR['bird']) = db_connect(data['database']['birdsong'][ARG.MANIFOLD])
    # Get relationships
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
    LOGGER.info("Prior comparisons found: %d", len(PROCESSED))
    choices = ["allele_match_all", "allele_match_seq", ARG.PHENOTYPE]
    quest = [inquirer.Checkbox('checklist',
                               message='Select comparisons to upload',
                               choices=choices, default=choices)]
    for cvt in inquirer.prompt(quest)['checklist']:
        WILL_LOAD.append(cvt)
    COUNT[ARG.PHENOTYPE] = 0


def compute_percent_match(row1, row2):
    """ Compute match percentages for all and sequenced alleles.
        Keyword arguments:
          row1: bird1 row
          row2: bird2 row
        Returns:
           % match for all alleles, % match for sequenced alleles
    """
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
            if (v1l[0] != "." and v1l[0] in v2l) or (v1l[1] != "." and v1l[1] in v2l):
                score += 0.5
        if val1 != "./." and val2 != "./.":
            seqcount += 1
            if val1 == val2:
                seqscore += 1
    return score / len(markers) * 100.0, seqscore / seqcount * 100.0


def get_session_id(bird):
    """ Return a session ID for a bird
        Keyword arguments:
          bird: bird name
        Returns:
           session ID
    """
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
    """ Compare two birds
        Keyword arguments:
          row1: bird1 row
          row2: bird2 row
          id1: bird1 ID
          session1: session ID for bird1
          full1:
          phen1: phenotype measurenent for bird1
          results: results list
        Returns:
           None
    """
    full2 = row2["IND_NAME"].iloc[0]
    id2 = row2[BIRD_COL].iloc[0]
    session2 = get_session_id(full2)
    phen2 = row2[ARG.PHENOTYPE.upper()].iloc[0] or "-"
    if full2 < full1:
        id1, id2 = id2, id1
        session1, session2 = session2, session1
        full1, full2 = full2, full1
        phen1, phen2 = phen2, phen1
    COUNT["potential"] += 1
    if make_comparison_key([id1, session1, id2, session2]) in PROCESSED:
        COUNT["present"] += 1
        return
    COUNT["comparisons"] += 1
    comp = {}
    if "allele_match_all" in WILL_LOAD or "allele_match_seq" in WILL_LOAD:
        comp["allele_match_all"], comp["allele_match_seq"] = compute_percent_match(row1, row2)
        relate = ""
        if full1 in RELATIONSHIP and full2 in RELATIONSHIP[full1]:
            relate = f"\t{RELATIONSHIP[full1][full2]}"
        results.append(f"{full1}\t{full2}\t{phen1}\t{phen2}\t{comp['allele_match_all']:.2f}%\t" \
                       + f"{comp['allele_match_seq']:.2f}%{relate}")
        # Save genotypes
        for cvt in (WILL_LOAD):
            if not cvt.startswith("allele"):
                continue
            try:
                CURSOR['bird'].execute(WRITE["COMPARE"] % (id1,session1,cvt,
                                                           id2,session2,comp[cvt]))
            except Exception as err:
                LOGGER.error("Could not insert %s for %s<->%s", cvt, id1, id2)
                sql_error(err)
            COUNT[cvt] += 1
    if ARG.PHENOTYPE in WILL_LOAD:
        # Save phenotype
        if phen1 and phen2 and phen1 not in (".", "-") and phen2 not in (".", "-"):
            try:
                CURSOR['bird'].execute(WRITE["COMPARE"] % (id1,session1,ARG.PHENOTYPE,
                                                           id2,session2,
                                                           float(phen1) - float(phen2)))
            except Exception as err:
                LOGGER.error("Could not insert %s for %s<->%s", ARG.PHENOTYPE, id1, id2)
                sql_error(err)
            COUNT[ARG.PHENOTYPE] += 1
    if ARG.WRITE:
        CONN['bird'].commit()


def show_stats():
    """ Show statistics
        Keyword arguments:
          None
        Returns:
          None
    """
    print(f"Comparisons skipped:         {COUNT['skipped']}")
    print(f"Potential comparisons:       {COUNT['potential']}")
    print(f"Comparisons already present: {COUNT['present']}")
    print(f"Comparisons removed:         {COUNT['removed']}")
    print(f"Comparisons made:            {COUNT['comparisons']}")
    print(f"allele_match_all:            {COUNT['allele_match_all']}")
    print(f"allele_match_seq:            {COUNT['allele_match_seq']}")
    print(f"{ARG.PHENOTYPE}:                {COUNT[ARG.PHENOTYPE]}")


def sigterm_handler(sig, frame):
    """ Handle SIGTERM by displaying stats and exiting.
        Keyword arguments:
          sig: signal
          frame: frame
        Returns:
          None
    """
    LOGGER.error("Caught SIGTERM")
    show_stats()
    sys.exit(0)


def process_data_frame():
    """ Read pickle file in to a dataframe, then process it.
        Keyword arguments:
          None
        Returns:
          None
    """
    print(f"Processing {ARG.FILE}")
    LOGGER.info("Reading %s", ARG.FILE)
    dfr = pd.read_pickle(ARG.FILE)
    dfr.sort_values(by="IND_NAME", inplace=True)
    LOGGER.info("Dimensions: %dx%d", dfr.shape[0], dfr.shape[1])
    LOGGER.info("Birds: %d", len(dfr[BIRD_COL].unique()))
    FRAME['NAME'] = list(dfr.columns)
    FRAME['FIRST_MARKER'] = FRAME['NAME'].index(SEX_COL) + 2
    birdlist = dfr[BIRD_COL].tolist()
    birdlist2 = birdlist[:]
    if ARG.SINGLE:
        max_results = len(birdlist) - 1
    else:
        max_results = int((len(birdlist) - 1) * (len(birdlist)) / 2)
        max_results -= len(PROCESSED)
    LOGGER.info("Estimated comparisons: %d", max_results)
    results = ["Bird1\tBird2\tPhenotype1\tPhenotype2\tAll markers\tSequenced markers\tRelationship"]
    for bird1 in tqdm(birdlist, desc="Primary", position=0):
        row1 = dfr.loc[dfr[BIRD_COL] == bird1]
        full1 = row1["IND_NAME"].iloc[0]
        if ARG.SINGLE and (ARG.SINGLE != full1):
            continue
        if ARG.START and (ARG.START > full1):
            continue
        birdlist2.remove(bird1)
        if not full1:
            COUNT["removed"] += 1
            continue
        id1 = row1[BIRD_COL].iloc[0]
        phen1 = row1[ARG.PHENOTYPE.upper()].iloc[0]
        session1 = get_session_id(full1)
        for bird2 in tqdm(birdlist2, desc=full1, position=1, leave=False):
            row2 = dfr.loc[dfr[BIRD_COL] == bird2]
            full2 = row2["IND_NAME"].iloc[0]
            if not full2:
                COUNT["removed"] += 1
                continue
            if ARG.SINGLE and (not ARG.FULL) and (full2 < full1):
                COUNT["skipped"] += 1
                continue
            compare_birds(row1, row2, id1, session1, full1, phen1, results)
    print(f"{len(results)-1}/{max_results} results")
    if len(results) > 1:
        with open("analysis_results.tsv", "w", encoding="ascii") as output:
            output.write("\n".join(results) + "\n")
    show_stats()


# *****************************************************************************

if __name__ == '__main__':
    PARSER = argparse.ArgumentParser(description="Load allelic states")
    PARSER.add_argument('--file', dest='FILE', action='store',
                        help='File', required=True)
    PARSER.add_argument('--phenotype', dest='PHENOTYPE', action='store',
                        default="median_tempo", help='Phenotype [median_tempo]')
    PARSER.add_argument('--single', dest='SINGLE', action='store',
                        help='Single bird to process')
    PARSER.add_argument('--full', dest='FULL', action='store_true',
                        default=False, help='Compare all birds is using --single')
    PARSER.add_argument('--start', dest='START', action='store',
                        help='Starting bird')
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
    signal.signal(signal.SIGTERM, sigterm_handler)
    process_data_frame()
    sys.exit(0)
