''' relatedness_plots.py
    Generate plots for bird comparisons
'''

import argparse
import os
import sys
import colorlog
import matplotlib.pyplot as plt
import MySQLdb
import numpy as np
import requests
from tqdm import tqdm

# pylint: disable=W0703

# Configuration
CONFIG = {'config': {'url': os.environ.get('CONFIG_SERVER_URL')}}
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


def call_responder(server, endpoint):
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


def prefetch_matches(males):
    """ Get a list of genotype comparisons for males
        Keyword arguments:
          males: dict of male birds
        Returns:
           Dictionary of genotype comparisons
    """
    LOGGER.info("Fetching %s", ARG.GENOTYPE)
    try:
        CURSOR['bird'].execute("SELECT bird1,bird2,value FROM bird_comparison_vw WHERE " \
                               + "comparison=%s ORDER BY 1,2", (ARG.GENOTYPE,))
        rows = CURSOR['bird'].fetchall()
    except Exception as err:
        sql_error(err)
    pdict = {}
    for row in tqdm(rows, desc=ARG.GENOTYPE):
        bird1 = row["bird1"]
        bird2 = row["bird2"]
        if (bird1 not in males) or (bird2 not in males):
            continue
        if bird1 not in pdict:
            pdict[bird1] = {bird2: row["value"]}
        else:
            pdict[bird1][bird2] = row["value"]
    return pdict


def generate_heatmap(xlist, ylist, title):
    """ Generate a heatmap
        Keyword arguments:
          xlist: X coordinates
          ylist: Y coordinates
          title: graph title
        Returns:
           None
    """
    heatmap, xedges, yedges = np.histogram2d(xlist, ylist, bins=100)
    extent = [xedges[0], xedges[-1], yedges[0], yedges[-1]]
    plt.figure(figsize=(10, 10))
    plt.clf()
    plt.imshow(heatmap.T, extent=extent, origin='lower')
    plt.title(title)
    plt.xlabel(ARG.PHENOTYPE)
    plt.ylabel(ARG.GENOTYPE)
    plt.colorbar()


def generate_plots(xpoint, ypoint, xpointr, ypointr, count):
    """ Generate plots
        Keyword arguments:
          xpoint: X coordinates for unrelated birds
          ypoint: Y coordinates for unrelated birds
          xpointr: X coordinates for related birds
          ypointr: Y coordinates for related birds
          count: bird count dictionary
        Returns:
           None
    """
    print(f"Points to plot: {len(xpointr)} (related), {len(xpoint)} (unrelated)")
    # Scatterplot
    plt.figure(figsize=(10, 10))
    plt.scatter(xpoint, ypoint, s=1.5, c="gray", label=f"{count['unrelated']} unrelated birds")
    plt.scatter(xpointr, ypointr, s=1.5, c="blue", label=f"{count['related']} related birds")
    plt.title(f"{ARG.PHENOTYPE} vs {ARG.GENOTYPE}")
    plt.xlabel(ARG.PHENOTYPE)
    plt.ylabel(ARG.GENOTYPE)
    plt.legend(loc="upper right")
    plt.savefig("scatterplot.png")
    # Heatmaps
    generate_heatmap(xpoint, ypoint, f"{count['unrelated']} " \
                     + f"unrelated birds {ARG.PHENOTYPE} vs {ARG.GENOTYPE}")
    plt.savefig("heatmap_unrelated.png")
    generate_heatmap(xpointr, ypointr, f"{count['related']} related birds " \
                     + f"{ARG.PHENOTYPE} vs {ARG.GENOTYPE}")
    plt.savefig("heatmap_related.png")


def process_data():
    """ Process comparisons
        Keyword arguments:
          None
        Returns:
           None
    """
    LOGGER.info("Fetching males")
    # Correction in case any females/unknowns have phenotype measurement
    males = {}
    try:
        CURSOR['bird'].execute("SELECT name FROM bird WHERE sex='M'")
        rows = CURSOR['bird'].fetchall()
    except Exception as err:
        sql_error(err)
    for row in rows:
        males[row["name"]] = True
    ams = prefetch_matches(males)
    try:
        CURSOR['bird'].execute("SELECT bird1,bird2,ABS(value) AS value,relationship " \
                               + "FROM bird_comparison_vw WHERE comparison=%s " \
                               + "ORDER BY 1,2", (ARG.PHENOTYPE,))
        rows = CURSOR['bird'].fetchall()
    except Exception as err:
        sql_error(err)
    xpoint = []
    ypoint = []
    xpointr = []
    ypointr = []
    for row in tqdm(rows, desc=ARG.PHENOTYPE):
        bird1 = row["bird1"]
        bird2 = row["bird2"]
        if (bird1 not in males) or (bird2 not in males):
            continue
        if row["relationship"]:
            xpointr.append(float(row["value"]))
            ypointr.append(round(float(ams[row["bird1"]][row["bird2"]]), 4))
        else:
            xpoint.append(float(row["value"]))
            ypoint.append(round(float(ams[row["bird1"]][row["bird2"]]), 4))
    sql = "SELECT COUNT(1) AS cnt FROM session WHERE " \
          + f"type_id=getCvTermId('phenotype','{ARG.PHENOTYPE}',NULL)" \
          + " AND bird_id NOT IN (SELECT subject_id FROM bird_relationship)"
    count = {}
    try:
        CURSOR["bird"].execute(sql)
        count["unrelated"] = CURSOR['bird'].fetchone()["cnt"]
        sql = sql.replace("NOT IN", "IN")
        CURSOR["bird"].execute(sql)
        count["related"] = CURSOR['bird'].fetchone()["cnt"]
    except Exception as err:
        sql_error(err)
    generate_plots(xpoint, ypoint, xpointr, ypointr, count)


# *****************************************************************************

if __name__ == '__main__':
    PARSER = argparse.ArgumentParser(description="Generate comparison plots")
    PARSER.add_argument('--genotype', dest='GENOTYPE', action='store',
                        default="allele_match_seq", help='Genotype measurement [allele_match_seq]')
    PARSER.add_argument('--phenotype', dest='PHENOTYPE', action='store',
                        default="median_tempo", help='Phenotype [median_tempo]')
    PARSER.add_argument('--manifold', dest='MANIFOLD', action='store',
                        default='dev', choices=["dev", "prod"],
                        help='Manifold')
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
    process_data()
    sys.exit(0)
