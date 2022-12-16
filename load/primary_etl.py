''' Primary ETL program to handle transferring data from SQLite database to MySQL
    Current limitations:
    - Birds must have either no parents or one sire and one damsel
    - Birds must have a hatch date
    - Birds musy have upper and lower bands
    - Birds that are a parent in a relationship must have a sex of "M" or "F"
'''

import argparse
from datetime import datetime
import os
import re
import socket
import sqlite3
from string import digits
import sys
import time
import colorlog
import requests
from tqdm import tqdm
import MySQLdb

# pylint: disable=W0703, W1202

# Configuration
CONFIG = {'config': {'url': os.environ.get('CONFIG_SERVER_URL')}}
BSTATUS = {}
NSTATUS = {}
COLOR = {}
LOCATION = {}
NESTLOC = {}
BIRD_ID = {}
DO_NOT_INSERT = {}
MARK_AS_DEAD = {}
# General
COUNT = {"birds": 0, "birds_duplicate": 0, "birds_invalid": 0, "birds_parent": 0,
         "birds_ref": 0, "birds_write": 0, "nests": 0, "nests_no_parents": 0,
         "nests_one_parent": 0, "nests_write": 0}
TIMER = {}
ELAPSED = []
# Database
CONN = {}
CURSOR = {}
READ = {"BIRD": "SELECT * FROM bird WHERE name=%s",
        "SIRED": "SELECT subject_id,object_id,create_date FROM bird_relationship WHERE "
                 + "type_id=getCvTermId('bird_relationship','sired_by',NULL)",
        "BORNE": "SELECT subject_id,object_id,create_date FROM bird_relationship WHERE "
                 + "type_id=getCvTermId('bird_relationship','borne_by',NULL)",
        "SIBLINGS": "SELECT subject_id FROM bird_relationship WHERE "
                    + "type_id=getCvTermId('bird_relationship','sired_by',NULL) "
                    + "AND object_id=%s",
       }
WRITE = {"ALIVE": "UPDATE bird SET alive=1 WHERE id=%s",
         "BIRD": "INSERT INTO bird (species_id,name,band,location_id,"
                 + "sex,notes,hatch_early,hatch_late) VALUES "
                 + "(1,%s,%s,getCvTermId('location',%s,NULL),%s,%s,%s,%s)",
         "BNEST": "UPDATE bird SET nest_id=%s WHERE id=%s",
         "BBNEST": "UPDATE bird SET birth_nest_id=%s WHERE id=%s",
         "CLAIM": "UPDATE bird SET user_id=%s,alive=1 WHERE id=%s",
         "DEAD": "UPDATE bird SET user_id=NULL,alive=0,death_date=%s WHERE id=%s",
         "BEVENT": "INSERT INTO bird_event (bird_id,location_id,status_id,user_id,"
                   + "terminal,event_date) VALUES (%s,getCvTermId('location',%s,NULL),"
                   + "getCvTermId('bird_status',%s,NULL),%s,%s,%s)",
         "NEST": "INSERT INTO nest (name,band,sire_id,damsel_id,location_id,breeding,"
                 + "create_date) VALUES (%s,%s,%s,%s,getCvTermId('location',%s,NULL),1,%s)",
         "NEVENT": "INSERT INTO nest_event (nest_id,status_id,user_id,event_date) VALUES"
                   + "(%s,getCvTermId('nest_status',%s,NULL),%s,%s)",
         "RELATE": "INSERT INTO bird_relationship (type_id,subject_id,object_id,create_date) "
                   + "VALUES(getCvTermId('bird_relationship',%s,NULL),%s,%s,%s)",
         "TERM": "INSERT INTO cv_term (cv_id,name,definition,display_name,is_current,data_type) "
                 + "VALUES(getCvId('location',NULL),%s,%s,%s,1,'text')",
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


def call_responder(server, endpoint, payload=''): # pylint: disable=R1710
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


def db_connect(dbd): # pylint: disable=R1710
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
    CONN['lite'] = sqlite3.connect(ARG.FILE)
    CONN['lite'].row_factory = sqlite3.Row
    CURSOR['lite'] = CONN['lite'].cursor()


def get_cv_terms():
    """ Add CV terms to global dictionaries
        Keyword arguments:
          None
        Returns:
          None
    """
    CURSOR['lite'].execute("SELECT * FROM birds_color")
    rows = CURSOR['lite'].fetchall()
    for row in rows:
        COLOR[row['id']] = {"name": row['name'], "abbrv": row['abbrv']}
    CURSOR['lite'].execute("SELECT * FROM birds_status")
    rows = CURSOR['lite'].fetchall()
    for row in rows:
        BSTATUS[row['id']] = row['name']
    CURSOR['lite'].execute("SELECT * FROM birds_neststatus")
    rows = CURSOR['lite'].fetchall()
    for row in rows:
        NSTATUS[row['id']] = row['name'].replace(" ", "_")


def insert_cv_terms():
    """ Transfer location CV terms to the MySQL database. Do not preserve IDs.
        Keyword arguments:
          None
        Returns:
          None
    """
    LOGGER.info("Inserting CV terms")
    CURSOR['lite'].execute("SELECT * FROM birds_location")
    rows = CURSOR['lite'].fetchall()
    for row in rows:
        name = 'see "notes"' if row['name'] == '"see ""notes"""' \
            else row['name']
        LOCATION[row['id']] = name
        try:
            CURSOR['bird'].execute(WRITE['TERM'], tuple([name] * 3))
        except Exception as err:
            terminate_program(sql_error(err))


def valid_bird_animal_row(row):
    """ Check to see if a bird from SQLite is valid. Check banding, hatch date, sex, and location
        Keyword arguments:
          row: birds_animal row
        Returns:
          True if valid, False otherwise
    """
    upper = lower = ""
    if row['band_color_id'] and row['band_number']:
        upper = COLOR[row['band_color_id']]['abbrv'] + str(row['band_number'])
    if row['band_color2_id'] and row['band_number2']:
        lower = COLOR[row['band_color2_id']]['abbrv'] + str(row['band_number2'])
    band = upper + lower
    error = ""
    if not band:
        error = f"No bands for {row['uuid']} {band} (Nest ID {row['nest_id']} " \
                + f"hatch date {row['hatch_date']})"
    elif not row['band_color_id']:
        error = f"No upper color for {row['uuid']}  {band} (Nest ID {row['nest_id']} " \
                + f"hatch date {row['hatch_date']})"
    elif row['band_color_id'] not in COLOR:
        error = f"Bad upper color ID {row['band_color_id']} for {row['uuid']} {band}"
    elif not row['band_color2_id']:
        error = f"No lower color for {row['uuid']} {band} (Nest ID {row['nest_id']} " \
                + f"hatch date {row['hatch_date']})"
    elif row['band_color2_id'] not in COLOR:
        error = f"Bad lower color ID {row['band_color2_id']} for {row['uuid']} {band}"
    elif not row['hatch_date']:
        error = f"No hatch_date for {row['uuid']} {band}"
    elif row['sex'] not in ['F', 'M', 'U']:
        error = f"Invalid sex ({row['sex']}) for {row['uuid']} {band}"
    elif row['location_id'] and row['location_id'] not in LOCATION:
        error = f"Bad location ID {row['location_id']} for {row['uuid']} {band}"
    if error:
        ERR.write(error + "\n")
        return False
    return True


def relate_birds(bird_id, sire_id, damsel_id, hdate):
    try:
        bind = ("sired_by", bird_id, sire_id, hdate)
        CURSOR['bird'].execute(WRITE["RELATE"], bind)
    except MySQLdb.Error as err:
        sql_error(err)
    try:
        bind = ("sire_to", sire_id, bird_id, hdate)
        CURSOR['bird'].execute(WRITE["RELATE"], bind)
    except MySQLdb.Error as err:
        sql_error(err)
    try:
        bind = ("borne_by", bird_id, damsel_id, hdate)
        CURSOR['bird'].execute(WRITE["RELATE"], bind)
    except MySQLdb.Error as err:
        sql_error(err)
    try:
        bind = ("damsel_to", damsel_id, bird_id, hdate)
        CURSOR['bird'].execute(WRITE["RELATE"], bind)
    except MySQLdb.Error as err:
        sql_error(err)


def add_sibling_relationships():
    """ Add relationships for siblings and half siblings.
        Keyword arguments:
          None
        Returns:
          None
    """
    try:
        CURSOR['bird'].execute(READ["BORNE"])
        borne_by = CURSOR['bird'].fetchall()
    except Exception as err:
        terminate_program(sql_error(err))
    damsel = {}
    for child in borne_by:
        damsel[child['subject_id']] = child['object_id']
    try:
        CURSOR['bird'].execute(READ["SIRED"])
        sired_by = CURSOR['bird'].fetchall()
    except Exception as err:
        terminate_program(sql_error(err))
    for child in tqdm(sired_by, desc="Birds: Add sibling relationships"):
        bird_id = child['subject_id']
        sire_id = child['object_id']
        damsel_id = damsel[bird_id]
        hdate = child['create_date']
        try:
            CURSOR['bird'].execute(READ["SIBLINGS"], (sire_id,))
            siblings = CURSOR['bird'].fetchall()
        except Exception as err:
            terminate_program(sql_error(err))
        for sib in siblings:
            sib_id = sib['subject_id']
            if bird_id == sib_id:
                continue
            relationship = "sibling_of" if damsel[bird_id] == damsel_id else "half_sibling_of"
            if relationship == "half_sibling_of":
                print("Half")
            try:
                CURSOR['bird'].execute(WRITE["RELATE"], (relationship, bird_id, sib_id, hdate))
            except Exception as err:
                terminate_program(sql_error(err))


def add_relationships(bird, parent):
    """ Transfer information from the birds_parent table to the bird_relationship table.
        Keyword arguments:
          bird: SQLite bird dictionary
          parent: bird parent dictionary
        Returns:
          None
    """
    for bid in tqdm(bird, desc="Birds: Add relationships"):
        if bid in DO_NOT_INSERT:
            continue
        row = bird[bid]
        if bid in parent:
            if not parent[bid]['sire'] and not parent[bid]['damsel']:
                continue
            if not parent[bid]['sire']:
                ERR.write(f"Missing sire for {bid} {row['name']}\n")
                continue
            if not parent[bid]['damsel']:
                ERR.write(f"Missing damsel for {bid} {row['name']}\n")
                continue
            if parent[bid]['sire'] not in BIRD_ID:
                LOGGER.error("Sire %s was not inserted", parent[bid]['sire'])
                continue
            if parent[bid]['damsel'] not in BIRD_ID:
                LOGGER.error("Damsel %s was not inserted", parent[bid]['damsel'])
                continue
            relate_birds(row['bird_id'],BIRD_ID[parent[bid]['sire']],
                         BIRD_ID[parent[bid]['damsel']], row['hatch_date'])
    add_sibling_relationships()


def process_birds_parent(bird):
    """ Transfer information from the birds_parent table to the bird_relationship table.
        Keyword arguments:
          bird: SQLite bird dictionary
        Returns:
          None
    """
    LOGGER.info("Adding bird relationships")
    TIMER['birds_parent'] = time.time()
    CURSOR['lite'].execute("SELECT * FROM birds_parent ORDER BY child_id")
    rows = CURSOR['lite'].fetchall()
    parent = {}
    relationship = {}
    for row in rows:
        if row['child_id'] not in relationship:
            relationship[row['child_id']] = []
        relationship[row['child_id']].append(row['parent_id'])
    for bid in tqdm(bird, desc="Birds: parentage check"):
        row = bird[bid]
        parent[bid] = {"damsel": None, "sire": None}
        if bid not in relationship:
            COUNT['birds_parent'] += 1
            continue
        for par in relationship[bid]:
            if par not in bird:
                COUNT['birds_ref'] += 1
                DO_NOT_INSERT[bid] = True
                continue
            if bird[par]['sex'] == 'M':
                if parent[bid]['sire']:
                    ERR.write(f"Bird {bid} {row['name']} has more than one sire\n")
                parent[bid]['sire'] = bird[par]['name']
            elif bird[par]['sex'] == 'F':
                if parent[bid]['damsel']:
                    ERR.write(f"Bird {bid} {row['name']} has more than one damsel\n")
                parent[bid]['damsel'] = bird[par]['name']
            else:
                ERR.write(f"Bird {bid} {row['name']} has a parent with an unknown sex\n")
    add_relationships(bird, parent)
    ELAPSED.append(f"birds_parent processing: {time.time()-TIMER['birds_parent']:.2f}")


def process_birds_claim(bird):
    """ Update information from the birds_claim table in the bird table.
        Keyword arguments:
          bird: SQLite bird dictionary
        Returns:
          None
    """
    LOGGER.info("Adding bird claims")
    TIMER['birds_claim'] = time.time()
    CURSOR['lite'].execute("SELECT * FROM birds_claim ORDER BY date")
    rows = CURSOR['lite'].fetchall()
    for row in tqdm(rows, desc="Bird claims"):
        bid = row['animal_id']
        if bid not in bird:
            continue
        bind = (row['username_id'], bird[bid]['bird_id'])
        LOGGER.debug(WRITE['CLAIM'], bind)
        try:
            CURSOR['bird'].execute(WRITE['CLAIM'], bind)
        except Exception as err:
            terminate_program(sql_error(err))
        if not row['username_id']:
            continue
        location = LOCATION[bird[bid]['location_id']] if bird[bid]['location_id'] else 'UNKNOWN'
        bind = (bird[bid]['bird_id'], location, 'claimed', row['username_id'], False, row['date'])
        LOGGER.debug(WRITE['BEVENT'], bind)
        try:
            CURSOR['bird'].execute(WRITE['BEVENT'], bind)
        except Exception as err:
            terminate_program(sql_error(err))
    ELAPSED.append(f"birds_claim processing: {time.time()-TIMER['birds_claim']:.2f}")


def process_birds_event(bird):
    """ Transfer information from the birds_event table to the bird_event table.
        Keyword arguments:
          bird: SQLite bird dictionary
        Returns:
          None
    """
    LOGGER.info("Adding bird events")
    TIMER['birds_event'] = time.time()
    CURSOR['lite'].execute("SELECT * FROM birds_event ORDER BY animal_id,date")
    rows = CURSOR['lite'].fetchall()
    mark_alive = {}
    for row in tqdm(rows, desc="Bird events"):
        bid = row['animal_id']
        if bid not in bird:
            continue
        if bird[bid]['bird_id'] not in mark_alive:
            bind = (str(bird[bid]['bird_id']),)
            try:
                CURSOR['bird'].execute(WRITE['ALIVE'], bind)
            except Exception as err:
                terminate_program(sql_error(err))
            mark_alive[bird[bid]['bird_id']] = True
        location = LOCATION[row['location_id']] if row['location_id'] else 'UNKNOWN'
        terminal = BSTATUS[row['status_id']] in ["died", "euthanized"]
        bind = (bird[bid]['bird_id'], location, BSTATUS[row['status_id']],
                row['entered_by_id'], terminal, row['date'])
        LOGGER.debug(WRITE['BEVENT'], bind)
        try:
            CURSOR['bird'].execute(WRITE['BEVENT'], bind)
        except Exception as err:
            terminate_program(sql_error(err))
        if terminal:
            bind = (row['date'], bird[bid]['bird_id'])
            try:
                CURSOR['bird'].execute(WRITE['DEAD'], bind)
            except Exception as err:
                terminate_program(sql_error(err))
    ELAPSED.append(f"birds_event processing: {time.time()-TIMER['birds_event']:.2f}")


def get_nest_band(name):
    """ Given a nest name, return the nest band (two appended color abbreviations)
        Keyword arguments:
          name: nest name
        Returns:
          nest band
    """
    colors = re.findall(r"([a-z]+)", name)
    band = ""
    for bcol in colors:
        for col in COLOR:
            if COLOR[col]['name'] == bcol:
                band += COLOR[col]['abbrv']
                break
    return band


def process_birds_nestevent(nest):
    """ Transfer information from the birds_nestevent table to the nest_event table.
        Keyword arguments:
          nest: SQLite nest dictionary
        Returns:
          None
    """
    LOGGER.info("Adding nest events")
    TIMER['birds_nestevent'] = time.time()
    CURSOR['lite'].execute("SELECT * FROM birds_nestevent ORDER BY nest_id,date")
    rows = CURSOR['lite'].fetchall()
    for row in tqdm(rows, desc="Nest events"):
        nid = row['nest_id']
        if nid not in nest:
            continue
        bind = (nest[nid]['nest_id'], NSTATUS[row['status_id']], row['entered_by_id'], row['date'])
        LOGGER.debug(WRITE['NEVENT'], bind)
        try:
            CURSOR['bird'].execute(WRITE['NEVENT'], bind)
        except Exception as err:
            terminate_program(sql_error(err))
    ELAPSED.append(f"birds_nestevent processing: {time.time()-TIMER['birds_nestevent']:.2f}")


def process_birds_nest(bird):
    """ Transfer information from the birds_nest table to the nest table.
        Keyword arguments:
          bird: SQLite bird dictionary
        Returns:
          None
    """
    LOGGER.info("Adding nests")
    TIMER['birds_nest'] = time.time()
    CURSOR['lite'].execute("SELECT * FROM birds_nest")
    rows = CURSOR['lite'].fetchall()
    nest = {}
    remove_digits = str.maketrans('', '', digits)
    for row in tqdm(rows, desc="Nests"):
        COUNT["nests"] += 1
        if not row['sire_id'] and not row['dam_id']:
            COUNT["nests_no_parents"] += 1
            continue
        if row['sire_id'] not in bird or row['dam_id'] not in bird:
            COUNT["nests_one_parent"] += 1
            continue
        nest[row['uuid']] = dict(row)
        hdate = bird[row['sire_id']]['hatch_date'].replace("-", "")
        name = bird[row['sire_id']]['name'].split("_")[-1]
        band = get_nest_band(name)
        name = "_".join([hdate, name.translate(remove_digits)])
        nest[row['uuid']]['band'] = band
        nest[row['uuid']]['name'] = name
        location = LOCATION[row['location_ptr_id']] if row['location_ptr_id'] else 'UNKNOWN'
        bind = (name, band, bird[row['sire_id']]['bird_id'], bird[row['dam_id']]['bird_id'],
                location, row['created'])
        LOGGER.debug(WRITE['NEST'], bind)
        try:
            CURSOR['bird'].execute(WRITE['NEST'], bind)
            nest[row['uuid']]['nest_id'] = CURSOR['bird'].lastrowid
            NESTLOC[nest[row['uuid']]['nest_id']] = location
            COUNT["nests_write"] += 1
        except Exception as err:
            terminate_program(sql_error(err))
    for bid in tqdm(bird, desc="Assign birds to nests"):
        row = bird[bid]
        if not row['nest_id'] or row['nest_id'] not in nest:
            continue
        inest = nest[row['nest_id']]['nest_id']
        bind = (inest, row['bird_id'])
        LOGGER.debug(WRITE['BNEST'], bind)
        try:
            CURSOR['bird'].execute(WRITE['BNEST'], bind)
        except Exception as err:
            terminate_program(sql_error(err))
        if NESTLOC[inest].startswith("N"):
            LOGGER.debug(WRITE['BBNEST'], bind)
            try:
                CURSOR['bird'].execute(WRITE['BBNEST'], bind)
            except Exception as err:
                terminate_program(sql_error(err))
    ELAPSED.append(f"birds_nest processing: {time.time()-TIMER['birds_nest']:.2f}")
    # Add nest events
    process_birds_nestevent(nest)


def process_sqlite():
    """ Transfer information from SQLite to MySQL.
        Keyword arguments:
          None
        Returns:
          None
    """
    get_cv_terms()
    insert_cv_terms()
    TIMER['total'] = time.time()
    # Get a list of birds from birds_animal
    TIMER['birds_animal'] = time.time()
    CURSOR['lite'].execute("SELECT * FROM birds_animal ORDER BY hatch_date")
    rows = CURSOR['lite'].fetchall()
    band = {}
    bird = {}
    for row in tqdm(rows, desc="Birds: Pass 1"):
        COUNT['birds'] += 1
        if not valid_bird_animal_row(row):
            COUNT['birds_invalid'] += 1
            continue
        longband = COLOR[row['band_color_id']]['name'] + str(row['band_number']) \
                  + COLOR[row['band_color2_id']]['name'] + str(row['band_number2'])
        shortband = COLOR[row['band_color_id']]['abbrv'] + str(row['band_number']) \
                    + COLOR[row['band_color2_id']]['abbrv'] + str(row['band_number2'])
        fullname = row['hatch_date'].replace("-", "") + "_" + longband
        if longband in band:
            LOGGER.warning("%s has a duplicate band %s", fullname, longband)
            COUNT['birds_duplicate'] += 1
        band[shortband] = row['uuid']
        bird[row['uuid']] = dict(row)
        bird[row['uuid']]['band'] = shortband
        bird[row['uuid']]['name'] = fullname
    # Write birds to MySQL
    for bid in tqdm(bird, desc="Birds: Primary write"):
        if bid in DO_NOT_INSERT:
            continue
        row = bird[bid]
        location = LOCATION[row['location_id']] if row['location_id'] else 'UNKNOWN'
        try:
            hdate = row['hatch_date'].replace("-", "")
            CURSOR['bird'].execute(WRITE['BIRD'], (row['name'], row['band'], location,
                                                   row['sex'], row['notes'], hdate, hdate))
            COUNT['birds_write'] += 1
            bird[bid]['bird_id'] = CURSOR['bird'].lastrowid
            BIRD_ID[row['name']] = CURSOR['bird'].lastrowid
            if row['notes'] and "dead" in row['notes']:
                MARK_AS_DEAD[bird[bid]['bird_id']] = True
        except Exception as err:
            terminate_program(sql_error(err))
    ELAPSED.append(f"birds_animal processing: {time.time()-TIMER['birds_animal']:.2f}")
    # Add relationships
    process_birds_parent(bird)
    # Add bird claims
    process_birds_claim(bird)
    # Add bird events
    process_birds_event(bird)
    # Process nests
    process_birds_nest(bird)
    # Mark birds as dead
    for bid in MARK_AS_DEAD:
        bind = (None, bid)
        try:
            CURSOR['bird'].execute(WRITE['DEAD'], bind)
        except Exception as err:
            terminate_program(sql_error(err))
    ELAPSED.append(f"Total processing time: {time.time()-TIMER['total']:.2f}")


def wrapup():
    """ Commit database and display run diagnostics.
        Keyword arguments:
          None
        Returns:
          None
    """
    if ARG.WRITE:
        CONN['bird'].commit()
    print("Birds read from SQLite:          " + f"{COUNT['birds']}")
    print("Birds with missing data:         "
          + f"{COUNT['birds_invalid']} ({COUNT['birds_invalid']/COUNT['birds']*100:.2f}%)")
    print("Duplicate birds:                 "
          + f"{COUNT['birds_duplicate']} ({COUNT['birds_duplicate']/COUNT['birds']*100:.2f}%)")
    birds1 = COUNT['birds'] - COUNT['birds_invalid']
    print("Valid birds after Pass 1:        " + f"{birds1}")
    print("Birds with no parents:           "
          + f"{COUNT['birds_parent']} ({COUNT['birds_parent']/birds1*100:.2f}%)")
    print("Birds with bad parent reference: "
          + f"{COUNT['birds_ref']} ({COUNT['birds_ref']/birds1*100:.2f}%)")
    print("Birds written to MySQL:          " + f"{COUNT['birds_write']}")
    print("Nests read from SQLite:          " + f"{COUNT['nests']}")
    print("Nests with no sire or damsel:    " + f"{COUNT['nests_no_parents']}")
    print("Nests with one parent:           " + f"{COUNT['nests_one_parent']}")
    print("Birds written to MySQL:          " + f"{COUNT['nests_write']}")
    for row in ELAPSED:
        print(row)

# *****************************************************************************

if __name__ == '__main__':
    PARSER = argparse.ArgumentParser(description="Load allelic states")
    PARSER.add_argument('--file', dest='FILE', action='store',
                        default='db.sqlite3', help='File')
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
    ERROR_FILE = f"etl_errors_{datetime.today().strftime('%Y%m%d%H%M%S')}.txt"
    ERR = open(ERROR_FILE, 'w', encoding="utf8")
    process_sqlite()
    wrapup()
    ERR.close()
    terminate_program()
