''' Upload a JSON file to create tasks in assignment-manager
'''

import argparse
import sys
import json
import os
import requests
import colorlog

# Configuration
CONFIG = {'config': {'url': 'http://config.int.janelia.org/'}}

def call_responder(server, endpoint, post=''):
    ''' Call a responder
        Keyword arguments:
          server: server
          endpoint: REST endpoint
          post: payload for POST requests
    '''
    url = CONFIG[server]['url'] + endpoint
    print(url)
    try:
        if post:
            headers = {"Content-Type": "application/json",
                       "Authorization": "Bearer " + ARGS.bearer}
            req = requests.post(url, headers=headers, json=post)
        else:
            req = requests.get(url)
    except requests.exceptions.RequestException as err:
        LOGGER.critical(err)
        sys.exit(-1)
    if req.status_code in (200, 201):
        return req.json()
    if req.status_code == 404:
        return ''
    try:
        LOGGER.critical('%s: %s', str(req.status_code), req.json()['rest']['message'])
    except: # pylint: disable=W0702
        LOGGER.critical('%s: %s', str(req.status_code), req.text)
    sys.exit(-1)


def process_file(file):
    ''' Process and upload a JSON file
        Keyword arguments:
          file: filename
    '''
    LOGGER.info("Opening %s", file)
    try:
        with open(file, 'r') as content_file:
            content = content_file.read()
    except IOError:
        LOGGER.critical("Could not read file %s", file)
        sys.exit(-1)
    if ARGS.assign:
        assignment = os.path.splitext(file)
        endpoint = '/'.join(['tasks', ARGS.protocol, ARGS.project, assignment[0]])
    else:
        endpoint = '/'.join(['tasks', ARGS.protocol, ARGS.project])
    #CONFIG['assignment-manager'] = {"url": "http://svirskasr-wm2.janelia.org/"} #PLUG
    try:
        content = json.loads(content)
    except ValueError:
        LOGGER.critical('File contains invalid JSON')
        sys.exit(-1)
    response = call_responder('assignment-manager', endpoint, content)
    if response['rest']['error']:
        LOGGER.critical(response['rest']['error'])
    else:
        LOGGER.info("Tasks inserted: %s", response['rest']['tasks_inserted'])


# -----------------------------------------------------------------------------

if __name__ == '__main__':
    PARSER = argparse.ArgumentParser(description='Create project/assignment/tasks from a JSON file')
    PARSER.add_argument('--protocol', dest='protocol', action='store',
                        default='cell_type_validation',
                        help='Protocol (optional, default=cell_type_validation)')
    PARSER.add_argument('--project', dest='project', action='store', required=True,
                        help='Project name')
    PARSER.add_argument('--assign', action='store_true', dest='assign',
                        default=False, help='Create assignment (use file name)')
    PARSER.add_argument('--bearer', dest='bearer', action='store',
                        help='JWT token')
    PARSER.add_argument('--file', dest='file', action='store', required=True,
                        help='JSON file')
    PARSER.add_argument('--verbose', action='store_true', dest='verbose',
                        default=False, help='Turn on verbose output')
    PARSER.add_argument('--debug', action='store_true', dest='debug',
                        default=False, help='Turn on debug output')
    PARSER.add_argument('--test', action='store_true', dest='test',
                        default=False, help='Test mode - does not actually upload')
    ARGS = PARSER.parse_args()
    VERBOSE = ARGS.verbose
    DEBUG = ARGS.debug
    TEST = ARGS.test
    if DEBUG:
        VERBOSE = True
    if not ARGS.bearer:
        if 'ASSIGNMENT_MANAGER_JWT' in os.environ:
            ARGS.bearer = os.environ['ASSIGNMENT_MANAGER_JWT']
        else:
            ARGS.bearer = input("Web token: ")
    LOGGER = colorlog.getLogger()
    if DEBUG:
        LOGGER.setLevel(colorlog.colorlog.logging.DEBUG)
    elif VERBOSE:
        LOGGER.setLevel(colorlog.colorlog.logging.INFO)
    else:
        LOGGER.setLevel(colorlog.colorlog.logging.WARNING)
    HANDLER = colorlog.StreamHandler()
    HANDLER.setFormatter(colorlog.ColoredFormatter())
    LOGGER.addHandler(HANDLER)
    DATA = call_responder('config', 'config/rest_services')
    CONFIG = DATA['config']
    process_file(ARGS.file)
