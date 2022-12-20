import argparse
import colorlog
import pandas as pd
from tqdm import tqdm

# General
BIRD_COL = "IND_ID" # Column name for bird
SEX_COL = "SEX" # Column name for bird sex

def combine_files():
    oldfile = "OLD_FORMAT/Genetic_and_phenotypic_data.pkl"
    newfile = "bd_and_gen_dat_for_db_test.pkl"
    dfro = pd.read_pickle(oldfile)
    LOGGER.info("Dimensions: %dx%d", dfro.shape[0], dfro.shape[1])
    LOGGER.info("Birds: %d", len(dfro[BIRD_COL].unique()))
    dfrn = pd.read_pickle(newfile)
    LOGGER.info("Dimensions: %dx%d", dfrn.shape[0], dfrn.shape[1])
    LOGGER.info("Birds: %d", len(dfrn[BIRD_COL].unique()))
    print(dfro)
    phenotype = {}
    for idx, row in tqdm(dfro.iterrows(), total=dfro.shape[0]):
        phenotype[row[BIRD_COL]] = row["MEDIAN_TEMPO"]
        print(row[BIRD_COL], row["MEDIAN_TEMPO"])

# *****************************************************************************

if __name__ == '__main__':
    PARSER = argparse.ArgumentParser(description="Combiner")
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

    combine_files()
