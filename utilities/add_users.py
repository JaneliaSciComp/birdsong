''' Populate the user table with users
'''

import requests

USERS = {"alvaradoc": "alvaradocx4",
         "ballingers": "sam.ballinger96",
         "bergs": "stuarteberg",
         "ducloso": "octave2014",
         "eubanksb": "bryoneubanks11",
         "finleys": "sammie42finley",
         "forknalln": "nforknall",
         "francisa": "alfrancis1996",
         "katzw": "billkatz",
         "hornej": "janeannehorne",
         "hubbardp": "hubbardpneu",
         "hsuj": "jlhsu225",
         "joycee": "emily.m.joyce1",
         "knechtc": "cjk7067",
         "lauchies": "Slauchie",
         "manleye": "emanley8794",
         "neacee": "erika.neace",
         "ogundeyio": "omotaraogundeyi",
         "olbrisd": "olbris",
         "ordishc": "cordish25",
         "parekhr": "ruchi.janelia",
         "patersont": "paterson1391",
         "plazas": "plaza.stephen",
         "ribeiroc": "ribeirocaitlin",
         "rivlinp": "patrivlin",
         "sammonsm": "megansammons44",
         "scotta": "Scott.AshleyLauren",
         "scotta10": "anniekayscott",
         "shinomiyaa": "quatretribunal",
         "shinomiyak": "kshinomniya",
         "smithc": "csmith792",
         "smithn": "natalielynnsmith",
         "suleimana": "aliansuleiman95",
         "takemurasa": "satn2030",
         "talebii": "lifesabeach0011",
         "tenshawe": "emilytenshaw",
         "tiscarenoc": "charli.tiscareno",
         "umayaml": "lumayam",
         "yangt": "tansygarvey",
         "zhaot": "tingzhao"
        }
PRIVILEGED = ['neacee', 'rivlinp']
PERMISSIONS = ['admin', 'Connectome Annotation Team', 'FlyEM Project and Software',
               'FlyEM Proofreaders', 'cell_type_validation', 'cleave',
               'connection_validation', 'orphan_link', 'todo']

def call_responder(url, endpoint, payload=''):
    ''' Call a responder
        Keyword arguments:
          url: URL
          endpoint: REST endpoint
          payload: payload for POST requests
    '''
    url += endpoint
    try:
        if payload:
            headers = {"Content-Type": "application/json",
                       "Authorization": "Bearer " + BEARER}
            req = requests.post(url, headers=headers, json=payload)
        else:
            req = requests.get(url)
    except requests.exceptions.RequestException as err:
        print(err)
        raise err
    if req.status_code == 200:
        return
    if 'is already' in req.text:
        print(req.json()['rest']['error'])
    else:
        print(req.text)
    return

BEARER = input("Bearer token: ")
SERVER = 'http://flyem-assignment.int.janelia.org/'
SERVER = 'http://svirskasr-wm2.janelia.org/'
for user in USERS:
    record = {"janelia_id": user,
              "name": USERS[user] + '@gmail.com'}
    call_responder(SERVER, 'adduser', record)
for user in PRIVILEGED:
    record = {"name": USERS[user] + '@gmail.com',
              "permissions": PERMISSIONS}
    call_responder(SERVER, 'user_permissions', record)
