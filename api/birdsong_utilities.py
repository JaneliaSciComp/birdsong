''' birdsong_utilities.py
    Birdsong manager utilities
'''

from datetime import datetime
import inspect
import random
import re
import string
from urllib.parse import parse_qs
from flask import g, request
import requests

# pylint: disable=C0302, W0703

CONFIG = {'config': {"url": "http://config.int.janelia.org/"}}
BEARER = ""
KEY_TYPE_IDS = {}

# SQL statements
READ = {
    'BSUMMARY': "SELECT * FROM bird_vw ORDER BY name DESC",
    'CSUMMARY': "SELECT * FROM clutch_vw ORDER BY name DESC",
    'COMPARISON': "SELECT bird1,bird2,relationship,comparison,value FROM bird_comparison_vw "
                  + "WHERE bird1=%s OR bird2=%s ORDER BY 1,2",
    'INUSE': "SELECT c.name,display_name,COUNT(b.id) AS cnt FROM cv_term c "
             + "LEFT OUTER JOIN bird b ON (b.location_id=c.id) "
             + "WHERE cv_id=getCvId('location','') GROUP BY 1,2 HAVING cnt>0",
    'ISPARENTX': "SELECT * FROM bird_relationship_vw WHERE type='genetic' AND (sire=%s "
                "OR damsel=%s)",
    'ISPARENT': "SELECT * FROM bird_relationship_vw where type IN ('sire_to','damsel_to') "
                + "AND subject=%s",
    'LSUMMARY': "SELECT c.name,display_name,definition,c.id,COUNT(b.id) AS cnt,"
                + "COUNT(DISTINCT n.id) AS ncnt FROM cv_term c LEFT OUTER JOIN bird b ON "
                + "(b.location_id=c.id) LEFT OUTER JOIN nest n ON (n.location_id=c.id) "
                + "WHERE cv_id=getCvId('location','') GROUP BY 1,2,3,4",
    'NSUMMARY': "SELECT * FROM nest_vw ORDER BY name DESC",
}
WRITE = {
    'INSERT_BIRD': "INSERT INTO bird (species_id,name,band,nest_id,birth_nest_id,clutch_id,"
                   + "location_id,vendor_id,user_id,notes,alive,hatch_early,"
                   + "hatch_late,sex) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s)",
    'INSERT_CV': "INSERT INTO cv (name,definition,display_name,version,"
                 + "is_current) VALUES (%s,%s,%s,%s,%s)",
    'INSERT_CVTERM': "INSERT INTO cv_term (cv_id,name,definition,display_name"
                     + ",is_current,data_type) VALUES (getCvId(%s,''),%s,%s,"
                     + "%s,%s,%s)",
    'INSERT_REL': "INSERT INTO bird_relationship (type_id,subject_id,object_id) "
                  + "VALUES(getCvTermId('bird_relationship',%s,NULL),%s,%s)",
    'INSERT_UPERM': "INSERT INTO user_permission (user_id,permission_id) VALUES "
                    + "(%s,getCvTermId('permission','%s','')) "
                    + "ON DUPLICATE KEY UPDATE permission_id=permission_id",
    'INSERT_USER': "INSERT INTO user (name,first,last,janelia_id,email,organization) "
                   + "VALUES (%s,%s,%s,%s,%s,%s)",
}
# *****************************************************************************
# * Classes                                                                   *
# *****************************************************************************
class InvalidUsage(Exception):
    ''' Return an error response
    '''
    status_code = 400

    def __init__(self, message, status_code=None, payload=None):
        Exception.__init__(self)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        ''' Build error response
        '''
        retval = dict(self.payload or ())
        retval['rest'] = {'error': self.message}
        return retval


# *****************************************************************************
# * Color/banding functions                                                   *
# *****************************************************************************

def apply_color(text, true_color, condition=True, false_color=None, false_text=None):
    ''' Return colorized text
        Keyword arguments:
          text: text to colorize
          true_color: color if condition is true
          condition: condition to determine color
          false_color: color if condition is false
          false_text: text replacement if condition is false
        Returns:
          colorized text
    '''
    if not condition:
        if false_text:
            text = false_text
        if not false_color:
            return text
    if condition:
        return f"<span style='color:{true_color}'>{text}</span>"
    return f"<span style='color:{false_color}'>{text}</span>"


def colorband(name, text=None, pretext=None, big=False):
    ''' Create a bands color display
        Keyword arguments:
          name: bird, clutch, or nest name
          text: optional text to display
        Returns:
          HTML
    '''
    html = '<div class="bands">'
    if pretext:
        html += pretext + "&nbsp;" * 2
    bclass = "band"
    if big:
        bclass += " bigband"
    name = re.sub(".+_", "", name)
    if re.search(r"\d", name):
        cols = re.findall("[a-z]+", name)
        for col in cols:
            html += f"<div class='{bclass} {col}'></div>"
    else:
        cols = re.finditer(r"black|blue|brown|green|orange|pink|purple|red|tut|white|yellow", name)
        for col in cols:
            html += f"<div class='{bclass} {col.group()}'></div>"
    if text:
        html += f"&nbsp;&nbsp;<div class='flexcol'>{text}</div>"
    html += '</div>'
    return html


def convert_banding(term):
    ''' Convert a banding style - accepts bands with long or short colors,
        and returns short or long colors. For example, passing in
        "20210506_red32blue45" will return "20210506_rd32bu45".
        Keyword arguments:
          term: name with upper/lower bands
        Returns:
          Converted name
    '''
    rows = get_cv_terms("color")
    color = {}
    for row in rows:
        color[row['cv_term']] = row['display_name']
    match = re.findall(r"([a-z]+)(\d+)([a-z]+)(\d+)$", term)[0]
    original = "".join(match)
    newterm = ""
    # If the input banding has short colors, invert the color dict
    if not(match[0] in color and match[2] in color):
        color = dict(map(reversed, color.items()))
    newterm = term.replace(original, "".join([color[match[0]], match[1],
                                              color[match[2]], match[3]]))
    return newterm


def get_nest_from_id(nid):
    ''' Get nest information
        Keyword arguments:
          nid: nest ID
        Returns:
          nest record
    '''
    try:
        g.c.execute("SELECT * FROM nest_vw WHERE id=%s", (nid,))
        row = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    return row


def get_banding(ipd):
    ''' Get banding and nest information
        Keyword arguments:
          ipd: request payload
        Returns:
          name: nest name
          band: nest band
    '''
    # Colors
    try:
        g.c.execute("SELECT display_name,cv_term FROM cv_term_vw WHERE cv='color'")
        rows = g.c.fetchall()
        color = {}
        for row in rows:
            color[row['cv_term']] = row['display_name']
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    name = "".join([ipd["start_date"].replace("-", ""), "_", ipd["color1"], ipd["color2"]])
    band = color[ipd["color1"]] + color[ipd["color2"]]
    return name, band


def get_banding_and_location(ipd):
    ''' Get banding, nest, and location information
        Keyword arguments:
          ipd: request payload
        Returns:
          band: list of bird names and band names
          nest: nest record
          loc_id: location ID
    '''
    color = {}
    rows = get_cv_terms("color")
    for row in rows:
        color[row['display_name']] = row['cv_term']
    # Nest
    try:
        g.c.execute("SELECT * FROM nest WHERE id=%s", (ipd['nest_id'],))
        nest = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    # Location
    try:
        g.c.execute("SELECT location_id FROM bird WHERE id=%s", (nest["sire_id"],))
        row = g.c.fetchone()
        loc_id = row["location_id"]
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    # Bands
    band = []
    for barr in ipd['bands']:
        nband = "".join([nest['band'][0:2], barr[0], nest['band'][-2:], barr[1]])
        color1 = color[nest["band"][0:2]]
        color2 = color[nest["band"][-2:]]
        name = "".join([ipd["start_date"].replace("-", ""), "_", color1, barr[0],
                        color2, barr[1]])
        band.append({"name": name, "band": nband})
    return band, nest, loc_id


def parse_bird_name(name):
    ''' Parse a given bird name (standard format: "20210506_red32blue45") into its components
        Keyword arguments:
          name: bird name
        Returns:
          dict of bird name components
    '''
    color = {}
    rows = get_cv_terms("color")
    for row in rows:
        color[row['cv_term']] = row['display_name']
    field = re.findall(r"([a-z]+|\d+)", name)
    bhash = {"date": field[0]}
    bhash["band"] = color[field[1]] + field[2] + color[field[3]] + field[4]
    bhash["color"] = {"upper": field[1], "lower": field[3]}
    bhash["abbreviation"] = {"upper": color[field[1]], "lower": color[field[3]]}
    bhash["number"] = {"upper": field[2], "lower": field[4]}
    return bhash


def parse_nest_band(band):
    ''' Parse a given nest band (standard format: "repu") into its components
        Keyword arguments:
          name: bird band
        Returns:
          colors: array of colors
    '''
    color = {}
    rows = get_cv_terms("color")
    for row in rows:
        color[row['display_name']] = row['cv_term']
    field = re.findall(r"([a-z][a-z])", band)
    nhash = {"color": {"upper": color[field[0]], "lower": color[field[1]]}}
    nhash['abbreviation'] = {"upper": field[0], "lower": field[1]}
    return nhash


# *****************************************************************************
# * Table generators                                                          *
# *****************************************************************************

def generate_birdlist_table(rows, showall=True):
    ''' Given rows from bird_vw, return an HTML table
        Keyword arguments:
          rows: rows from database search
          showall: show all birds
        Returns:
          HTML table
    '''
    if rows:
        header = ['Name', 'Band', 'Nest', 'Location', 'Sex', 'Notes',
                  'Current age', 'Alive']
        if showall:
            header.insert(3, "Claimed by")
        birds = '''
        <table id="birds" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        birds += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr class="%s">' + ''.join("<td>%s</td>")*len(header) + "</tr>"
        fileoutput = ''
        ftemplate = "\t".join(["%s"]*len(header)) + "\n"
        for row in rows:
            for col in ("nest", "notes", "sex", "username"):
                if not row[col]:
                    row[col] = ""
            if not row['nest_location']:
                row['nest_location'] = 'Outside vendor'
            outcol = [row['name'], row['band'], row['nest_location'] + ' ' + row['nest'],
                      row['location'], row['sex'], row['notes'], row['current_age'], row['alive']]
            if showall:
                outcol.insert(3, row["username"])
            fileoutput += ftemplate % tuple(outcol)
            rclass = 'alive' if row['alive'] else 'dead'
            bird = colorband(row['name'], f"<a href='/bird/{row['name']}'>{row['name']}</a>")
            if not row['alive']:
                row['current_age'] = '-'
            alive = apply_color("YES", "lime", row["alive"], "red", "NO")
            nest = row['nest_location'] + f" <a href='/nest/{row['nest']}'>{row['nest']}</a>"
            outcol = [rclass, bird, row['band'], nest, row['location'], row['sex'],
                      row['notes'], row['current_age'], alive]
            if showall:
                outcol.insert(4, row["username"])
            birds += template % tuple(outcol)
        birds += "</tbody></table>"
        downloadable = create_downloadable('birds', header, ftemplate, fileoutput)
        birds = f"<a class='btn btn-outline-info btn-sm' href='/download/{downloadable}' " \
                + 'role="button">Download table</a>' + birds
        birds = f"<span style='font-size:16pt'>Birds found: {len(rows)}</span>" + "<br>" + birds
    else:
        birds = "<span style='font-size:16pt'>No birds were found</span>"
    return birds


def generate_clutchlist_table(rows):
    ''' Given rows from clutch_vw, return an HTML table
        Keyword arguments:
          rows: rows from database search
        Returns:
          HTML table
    '''
    if rows:
        header = ['Name', 'Nest', 'Clutch early', 'Clutch late', 'Bird count', 'Notes']
        clutches = '''
        <table id="clutches" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        clutches += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr class="open">' + ''.join("<td>%s</td>")*len(header) + "</tr>"
        fileoutput = ''
        ftemplate = "\t".join(["%s"]*len(header)) + "\n"
        for row in rows:
            cnt = get_clutch_or_nest_count(row["id"])
            fileoutput += ftemplate % (row['name'], row['nest_location'] + ' ' + row['nest'],
                                       strip_time(row['clutch_early']),
                                       strip_time(row['clutch_late']), cnt, row['notes'])
            nest = row['nest_location'] +  f" <a href='/nest/{row['nest']}'>{row['nest']}</a>"
            clutch = colorband(row['name'], f"<a href='/clutch/{row['name']}'>{row['name']}</a>")
            clutches += template % (clutch, nest, strip_time(row['clutch_early']),
                                    strip_time(row['clutch_late']), cnt, row['notes'])
        clutches += "</tbody></table>"
        downloadable = create_downloadable('clutches', header, ftemplate, fileoutput)
        clutches = f'<a class="btn btn-outline-info btn-sm" href="/download/{downloadable}" ' \
                   + 'role="button">Download table</a>' + clutches
        clutches = f"<span style='font-size:16pt'>Clutches found: {len(rows)}</span>" \
                   + "<br>" + clutches
    else:
        clutches = "<span style='font-size:16pt'>No clutches were found</span>"
    return clutches


def generate_nestlist_table(rows):
    ''' Given rows from nest_vw, return an HTML table
        Keyword arguments:
          rows: rows from database search
        Returns:
          HTML table
    '''
    if rows:
        header = ['Name', 'Band', 'Sire', 'Damsel', 'Bird count', 'Location', 'Notes']
        nests = '''
        <table id="nests" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        nests += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr class="open">' + ''.join("<td>%s</td>")*len(header) + "</tr>"
        fileoutput = ''
        ftemplate = "\t".join(["%s"]*len(header)) + "\n"
        for row in rows:
            cnt = get_clutch_or_nest_count(row["id"], 'nest')
            fileoutput += ftemplate % (row['name'], row['band'], row['sire'],
                                       row['damsel'], cnt, row['location'], row['notes'])
            nest = colorband(row['name'], f"<a href='/nest/{row['name']}'>{row['name']}</a>")
            sire = colorband(row['sire'], f"<a href='/bird/{row['sire']}'>{row['sire']}</a>")
            damsel = colorband(row['damsel'], f"<a href='/bird/{row['damsel']}'>"
                               + f"{row['damsel']}</a>")
            nests += template % (nest, row['band'], sire, damsel,
                                 cnt, row['location'], row['notes'])
        nests += "</tbody></table>"
        downloadable = create_downloadable('nests', header, ftemplate, fileoutput)
        nests = f'<a class="btn btn-outline-info btn-sm" href="/download/{downloadable}" ' \
                 + 'role="button">Download table</a>' + nests
        nests = f"<span style='font-size:16pt'>Nests found: {len(rows)}</span>" + "<br>" + nests
    else:
        nests = "<span style='font-size:16pt'>No nests were found</span>"
    return nests


# *****************************************************************************
# * Pulldown generators                                                       *
# *****************************************************************************

def generate_bird_pulldown(sex, sid):
    ''' Generate pulldown menu of all live birds of a particular sex
        Keyword arguments:
          sex: sex
          sid: select ID
          use: nest use (breeding or fostering)
        Returns:
          HTML menu
    '''
    controls = ''
    # Exclusions
    sql = "SELECT * FROM nest_vw"
    try:
        g.c.execute(sql)
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    exclude = {}
    for row in rows:
        for rname in ["sire", "damsel", "female1", "female2", "female3"]:
            if row[rname]:
                exclude[row[rname]] = 1
    # Birds
    sql = "SELECT id,name FROM bird where sex=%s AND alive=1 ORDER BY 2"
    try:
        g.c.execute(sql, (sex,))
        irows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    rows = []
    for row in irows:
        if row["name"] not in exclude:
            rows.append(row)
    if not rows:
        return '<span style="color:red">No birds available</span>'
    controls = f"<select id='{sid}' class='form-control col-sm-8'><option value=''>" \
               + 'Select a bird...</option>'
    for row in rows:
        controls += f"<option value='{row['id']}'>{row['name']}</option>"
    controls += "</select>"
    return controls


def generate_claim_pulldown(sid, simple=False):
    ''' Generate pulldown menu of all bird claimants
        Keyword arguments:
          sid: select ID
          simple: do not use Bootstrap controle
        Returns:
          HTML menu
    '''
    controls = ''
    sql = "SELECT DISTINCT username FROM bird_vw WHERE username IS NOT NULL " \
          + "ORDER BY 1"
    try:
        g.c.execute(sql)
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    if simple:
        controls = f"<select id='{sid}'><option value=''>" \
                   + 'Select a claimant...</option>'
    else:
        controls = f"<select id='{sid}' class='form-control col-sm-5'><option value=''>" \
                   + 'Select a claimant...</option>'
    for row in rows:
        controls += f"<option value='{row['username']}'>{row['username']}</option>"
    controls += "</select>"
    return controls


def generate_color_pulldown(sid, simple=False):
    ''' Generate pulldown menu of all colors
        Keyword arguments:
          sid: select ID
          simple: do not use Bootstrap controle
        Returns:
          HTML menu
    '''
    controls = ''
    rows = get_cv_terms('color')
    if simple:
        controls = f"<select id='{sid}'><option value=''>" \
                   + 'Select a color...</option>'
    else:
        controls = f"<select id='{sid}' class='form-control col-sm-5'><option value=''>" \
                   + 'Select a color...</option>'
    for row in sorted(rows, key=lambda d: d['cv_term']):
        controls += f"<option value='{row['cv_term']}'>{row['cv_term']}</option>"
    controls += "</select>"
    return controls


def generate_location_pulldown(sid, used=True, simple=False):
    ''' Generate pulldown menu of all in-use locations
        Keyword arguments:
          sid: select ID
          simple: do not use Bootstrap controle
        Returns:
          HTML menu
    '''
    controls = ''
    try:
        if used:
            g.c.execute(READ["INUSE"])
            rows = g.c.fetchall()
        else:
            rows = get_cv_terms('location')
    except Exception as err:
        return err
    if simple:
        controls = f"<select id='{sid}'><option value=''>" \
                   + 'Select a location...</option>'
    else:
        controls = f"<select id='{sid}' class='form-control col-sm-10'><option value=''>" \
                   + 'Select a location...</option>'
    for row in rows:
        controls += f"<option value='{row['name'] if 'name' in row else row['id']}'>" \
                    + f"{row['display_name']}</option>"
    controls += "</select>"
    return controls


def generate_movement_pulldown(this_id, item_type=None, current=None):
    ''' Generate pulldown menu of all locations (except the current one)
        Keyword arguments:
          this_id: bird or nest ID
          item_type: type of item to move (bird, nest)
          current: current location
        Returns:
          HTML menu
    '''
    controls = ""
    rows = get_cv_terms('location')
    if this_id:
        controls = f"Move {'nest' if item_type != 'bird' else 'bird'} to new location"
    controls += '<select id="location" class="form-control col-sm-4" onchange="select_location(' \
                + str(this_id) + ',this);"><option value="">Select a new location...</option>'
    for row in rows:
        if row["display_name"] == current:
            continue
        controls += f"<option value='{row['id']}'>{row['display_name']}</option>"
    controls += "</select><br>"
    return controls


def generate_nest_pulldown(ntype, from_nest=None, default_nest=None):
    ''' Generate pulldown menu of all nests (with conditions)
        Keyword arguments:
          ntype: nest type
          from_nest: clutch ID or current_nest ID
          default_nest: ID of nest to select
        Returns:
          HTML menu
    '''
    sql = "SELECT id,name,location FROM nest_vw WHERE active=1 AND "
    clause = []
    if 'breeding' in ntype:
        clause.append("(sire IS NOT NULL AND damsel IS NOT NULL AND breeding=1)")
    if 'fostering' in ntype:
        clause.append("(fostering=1)")
    sql += " OR ".join(clause) + " ORDER BY 2"
    try:
        g.c.execute(sql)
        rows = g.c.fetchall()
    except Exception as err:
        return err
    if not rows:
        return '<span style="color:red">No nests available</span>'
    if from_nest:
        default_nest = from_nest
        controls = '<select id="nest" onchange="select_nest(' + str(from_nest) \
                   + ',this);" class="form-control col-sm-8"><option value="">' \
                   + 'Select a new nest...</option>'
    else:
        controls = '<select id="nest" class="form-control col-sm-8"><option value="">' \
                   + 'Select a nest...</option>'
    for row in rows:
        controls += f"<option value='{row['id']}' " \
                    + f"{'selected' if default_nest==str(row['id']) else ''}>" \
                    + f"{row['location']} {row['name']}</option>"
    controls += "</select><br>"
    return controls


def generate_tutor_pulldown(bird_id):
    ''' Generate pulldown menu of all eligible tutors (with conditions)
        Keyword arguments:
          None
        Returns:
          HTML menu
    '''
    #onchange="select_location('+ str(bird_id) + ',this)
    controls = '<select id="tutor" class="form-control col-sm-4" onchange="select_tutor(' \
               + str(bird_id) + ',this)" ><option value="">' \
               + 'Select a tutor...</option>'
    # Current tutor
    sql = "SELECT * FROM bird_tutor WHERE bird_id=%s ORDER BY create_date DESC LIMIT 1"
    try:
        g.c.execute(sql, (bird_id))
        trow = g.c.fetchone()
    except Exception as err:
        return err
    # Computers
    sql = "SELECT id,display_name FROM cv_term_vw WHERE cv='tutor' AND is_current=1 ORDER BY 2"
    try:
        g.c.execute(sql)
        rows = g.c.fetchall()
    except Exception as err:
        return err
    if not rows:
        return '<span style="color:red">No tutors available</span>'
    for row in rows:
        if trow and trow["type"] == "computer" and trow["computer_id"] == row['id']:
            continue
        controls += f"<option value='computer_{row['id']}'>{row['display_name']}</option>"
    # Birds
    sql = "SELECT id,name FROM bird_vw WHERE sex='M' AND alive=1 ORDER BY 2"
    try:
        g.c.execute(sql)
        rows = g.c.fetchall()
    except Exception as err:
        return err
    if not rows:
        return '<span style="color:red">No tutors available</span>'
    for row in rows:
        if trow and trow["type"] == "bird" and trow["tutor_id"] == row['id']:
            continue
        controls += f"<option value='bird_{row['id']}'>{row['name']}</option>"
    controls += "</select><br><br>"
    return controls


def generate_vendor_pulldown(sid, simple=False):
    ''' Generate pulldown menu of all vendors
        Keyword arguments:
          sid: select ID
          simple: do not use Bootstrap controle
        Returns:
          HTML menu
    '''
    controls = ''
    try:
        rows = get_cv_terms('vendor')
    except Exception as err:
        return err
    if simple:
        controls = f"<select id='{sid}'><option value=''>" \
                   + 'Select a vendor...</option>'
    else:
        controls = f"<select id='{sid}' class='form-control col-sm-10'><option value=''>" \
                   + 'Select a vendor...</option>'
    for row in rows:
        controls += f"<option value='{row['id']}'>{row['display_name']}</option>"
    controls += "</select>"
    return controls


def generate_notes_field(this_id):
    ''' Generate notes field
        Keyword arguments:
          this_id: bird ID
        Returns:
          HTML menu
    '''
    controls = '<input type="text" class="form-control" id="notes" onchange="add_notes(' \
               + str(this_id) + ',this);"/>'
    return controls


def generate_sex_pulldown(this_id):
    ''' Generate pulldown menu for sex
        Keyword arguments:
          this_id: bird ID
        Returns:
          HTML menu
    '''
    controls = ''
    controls += '<select id="sex" class="form-control col-sm-8" onchange="select_sex(' \
                + str(this_id) + ',this);"><option value="">Select a sex...</option>'
    for sex in ["M", "F"]:
        controls += f"<option value='{sex}'>{sex}</option>"
    controls += "</select>"
    controls += "<input type='checkbox' id='tutor'><label>Assign nest sire as tutor</label>"
    return controls


def generate_dead_or_alive(standalone=False):
    ''' Return dead or alive checkboxes
        Keyword arguments:
          standalone: generate standalone control
        Returns:
          HTML
    '''
    core = '''
      <div class="flexrow">
        <div class="flexcol"></div>
        <div class="flexcol">
          <label>Alive</label>
          <input type="checkbox" id="alive" checked onchange="get_birds();">
          &nbsp;
          <label>Dead</label>
          <input type="checkbox" id="dead" onchange="get_birds();">
        </div>
      </div>
    '''
    if standalone:
        core = f"<div style='float: left;margin-left: 15px;'>{core}</div>"
    return core


def generate_which_pulldown():
    ''' Return a pulldown menu to select bird claimant
        Keyword arguments:
          None
        Returns:
          HTML
    '''
    return '''
    <div style='float: left;margin-left: 15px;'>
      <div class="flexrow">
        <div class="flexcol">
          Birds to show:
        </div>
        <div class="flexcol">
          <select id="which" onchange="get_birds();">
            <option value="mine" selected>Claimed by me</option>
            <option value="eligible">Claimed by me or unclaimed</option>
            <option value="unclaimed">Unclaimed birds only</option>
            <option value="claimed">Claimed birds only</option>
            <option value="all">All birds</option>
          </select>
        </div>
      </div>
    ''' + generate_dead_or_alive() + "</div>"


# *****************************************************************************
# * Payload functions                                                         *
# *****************************************************************************

def receive_payload(result):
    ''' Get a request payload (form or JSON).
        Keyword arguments:
          result: result dictionary
        Returns:
          payload dictionary
    '''
    pay = {}
    if not request.get_data():
        return pay
    try:
        if request.form:
            result["rest"]["form"] = request.form
            for itm in request.form:
                pay[itm] = request.form[itm]
        elif request.json:
            result["rest"]["json"] = request.json
            pay = request.json
    except Exception as err:
        temp = "{2}: An exception of type {0} occurred. Arguments:\n{1!r}"
        mess = temp.format(type(err).__name__, err.args, inspect.stack()[0][3])
        raise InvalidUsage(mess, 500) from err
    return pay


def check_missing_parms(ipd, required):
    ''' Check for missing parameters
        Keyword arguments:
          ipd: request payload
          required: list of required parameters
    '''
    missing = ""
    for prm in required:
        if prm not in ipd:
            missing = missing + prm + " "
    if missing:
        raise InvalidUsage("Missing arguments: " + missing)


# *****************************************************************************
# * Trigger functions                                                         *
# *****************************************************************************
def add_sex_trigger(bird_id):
    ''' Add the nest's sire as a tutor.
        Keyword arguments:
          bird_id: bird ID
        Returns:
          None
    '''
    sql = "SELECT nest_id FROM bird WHERE id=%s"
    try:
        bind = (bird_id)
        g.c.execute(sql, bind)
        row = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    if not row["nest_id"]:
        return
    sql = "SELECT sire_id FROM nest WHERE id=%s"
    try:
        bind = (row["nest_id"])
        g.c.execute(sql, bind)
        row = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    if not row["sire_id"]:
        return
    sql = "INSERT INTO bird_tutor (bird_id,type,tutor_id) VALUES (%s,'bird',%s)"
    try:
        bind = (bird_id, row["sire_id"])
        g.c.execute(sql, bind)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    return


# *****************************************************************************
# * Verification/validation functions                                         *
# *****************************************************************************

def build_permissions_table(calling_user, user):
    ''' Generate a user permission table.
        Keyword arguments:
          calling_user: calling user
          user: user instance
    '''
    permissions = user["permissions"].split(",") if user["permissions"] else []
    template = '<tr><td style="width:300px">%s</td><td style="text-align: center">%s</td></tr>'
    rows = get_cv_terms('permission')
    # Permissions
    parray = []
    disabled = "" if check_permission(calling_user, ["admin"]) else "disabled"
    for row in rows:
        perm = row["cv_term"]
        display = row["display_name"]
        val = 'checked="checked"' if perm in permissions else ''
        check = f"<input type='checkbox' {val} id='{row['cv_term']}' " \
                + f"{disabled} onchange='changebox(this);'>"
        if row["cv_term"] in permissions:
            permissions.remove(row["cv_term"])
        parray.append(template % (display, check))
    ptable = '<table><thead><tr style="color:#069"><th>Permission</th>' \
             + '<th>Enabled</th></tr></thead><tbody>' \
             + ''.join(parray) + '</tbody></table>'
    return ptable


def check_dates(ipd):
    ''' Ensure that start/stop dates are in sequence
        Keyword arguments:
          ipd: request payload
        Returns:
          None (or raised error for dates out of sequence)
    '''
    if "start_date" in ipd and "stop_date" in ipd:
        if ipd["start_date"] and ipd["stop_date"]:
            if ipd["stop_date"] < ipd["start_date"]:
                raise InvalidUsage("Stop date must be >= start date")


def check_permission(user, permission=None):
    ''' Validate that a user has a specified permission
        Keyword arguments:
          user: user name
          permission: single permission or list of permissions
        Returns::
          List of permissions if no permission is specified, otherwise True/False
    '''
    if not permission:
        stmt = "SELECT * FROM user_permission_vw WHERE name=%s"
        try:
            g.c.execute(stmt, (user))
            rows = g.c.fetchall()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
        perm = [row['permission'] for row in rows]
        return perm
    if type(permission).__name__ == 'str':
        permission = [permission]
    stmt = "SELECT * FROM user_permission_vw WHERE name=%s AND permission=%s"
    for per in permission:
        bind = (user, per)
        try:
            g.c.execute(stmt, bind)
            row = g.c.fetchone()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
        if row:
            return True
    return False


def get_user_id(user):
    ''' Get a user's ID from the "user" table
        Keyword arguments:
          user: user
    '''
    try:
        g.c.execute("SELECT id FROM user WHERE name=%s", (user))
        row = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    if not row or "id" not in row:
        raise InvalidUsage(f"User {user} was not found", 404)
    return row['id']


def validate_user(user):
    ''' Validate a user
        Keyword arguments:
          user: user name or Janelia ID
        Returns:
          True or False
    '''
    stmt = "SELECT * FROM user_vw WHERE name=%s OR janelia_id=%s"
    try:
        g.c.execute(stmt, (user, user))
        usr = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    return bool(usr)


# *****************************************************************************
# * Database search functions                                                 *
# *****************************************************************************

def process_color_search(ipd):
    ''' Build SQL statement and bind tuple for color search
        Keyword arguments:
          ipd: request payload
        Returns:
          sql: SQL statement
          bind: bind tuple
    '''
    sql = f"SELECT * FROM {ipd['key_type']}_vw WHERE name "
    if ipd['uppercolor']:
        if ipd['lowercolor']:
            sql += "REGEXP %s"
            if ipd['key_type'] == 'bird':
                term = ipd["uppercolor"] + "[0-9]+" + ipd["lowercolor"] + "[0-9]+$"
            else:
                term = ipd["uppercolor"] + ipd["lowercolor"]
        else:
            sql += "LIKE %s"
            term = "%\\_" + ipd["uppercolor"] + "%"
    elif ipd["lowercolor"]:
        if ipd['key_type'] == 'bird':
            sql += "REGEXP %s"
            term = ipd["lowercolor"] + "[0-9]+$"
        else:
            sql += "REGEXP %s"
            term = ipd["lowercolor"] + "$"
    sql += " ORDER BY name"
    return sql, (term)


def process_number_search(ipd):
    ''' Build SQL statement and bind tuple for number search
        Keyword arguments:
          ipd: request payload
        Returns:
          sql: SQL statement
          bind: bind tuple
    '''
    sql = "SELECT * FROM bird_vw WHERE band "
    if ipd['uppernum']:
        if ipd['lowernum']:
            sql += "REGEXP %s"
            term = ipd["uppernum"] + "[a-z]+" + ipd["lowernum"]
        else:
            sql += "REGEXP %s"
            term = "^[a-z]+" + ipd["uppernum"] + "[a-z]"
    elif ipd["lowernum"]:
        sql += "REGEXP %s"
        term = "[a-z]+" + ipd["lowernum"] + "$"
    sql += " ORDER BY name"
    return sql, (term)


def get_search_sql(ipd):
    ''' Build SQL statement and bind tuple for searches
        Keyword arguments:
          ipd: request payload
        Returns:
          sql: SQL statement
          bind: bind tuple
    '''
    if ipd['stype'] == 'sbu':
        check_missing_parms(ipd, ['claim'])
        sql = "SELECT * FROM bird_vw WHERE username=%s ORDER BY name"
        bind = (ipd['claim'])
    elif ipd['stype'] == 'sbl':
        check_missing_parms(ipd, ['location'])
        if ipd['key_type'] == 'nest':
            sql = "SELECT * FROM nest_vw WHERE location=%s ORDER BY name"
        else:
            sql = "SELECT * FROM bird_vw WHERE location=%s ORDER BY name"
        bind = (ipd['location'])
    elif ipd['stype'] == 'sbt':
        check_missing_parms(ipd, ['key_text'])
        bind = ("%" + ipd['key_text'] + "%", "%" + ipd['key_text'] + "%", "%" \
                + ipd['key_text'] + "%")
        if ipd['key_type'] == 'bird':
            sql = 'SELECT * FROM bird_vw WHERE name LIKE %s OR band like %s OR ' \
                  + 'notes LIKE %s ORDER BY name'
        elif ipd['key_type'] == 'clutch':
            sql = 'SELECT * FROM clutch_vw WHERE name LIKE %s OR notes LIKE %s ORDER BY name'
            bind = ("%" + ipd['key_text'] + "%", "%" + ipd['key_text'] + "%")
        elif ipd['key_type'] == 'nest':
            sql = 'SELECT * FROM nest_vw WHERE name LIKE %s OR band like %s OR ' \
                  + 'notes LIKE %s ORDER BY name'
    elif ipd['stype'] == 'sbc':
        sql, bind = process_color_search(ipd)
    elif ipd['stype'] == 'sbn':
        sql, bind = process_number_search(ipd)
    return sql, bind


# *****************************************************************************
# * Database functions                                                        *
# *****************************************************************************

def add_key_value_pair(key, val, separator, sql, bind):
    ''' Add a key/value pair to the WHERE clause of a SQL statement
        Keyword arguments:
          key: column
          value: value
          separator: logical separator (AND, OR)
          sql: SQL statement
          bind: bind tuple
    '''
    eprefix = ''
    if not isinstance(key, str):
        key = key.decode('utf-8')
    if re.search(r'[!><]$', key):
        match = re.search(r'[!><]$', key)
        eprefix = match.group(0)
        key = re.sub(r'[!><]$', '', key)
    if not isinstance(val[0], str):
        val[0] = val[0].decode('utf-8')
    if '*' in val[0]:
        val[0] = val[0].replace('*', '%')
        if eprefix == '!':
            eprefix = ' NOT'
        else:
            eprefix = ''
        sql += separator + ' ' + key + eprefix + ' LIKE %s'
    else:
        sql += separator + ' ' + key + eprefix + '=%s'
    bind = bind + (val,)
    return sql, bind


def valid_dates(ipd):
    ''' Check for valid srat/stop dates
        Keyword arguments:
          ipd: request payload
        Returns:
          True or False
    '''
    if "start_date" in ipd and ipd["start_date"]:
        if not re.fullmatch(r"^\d{4}-\d{2}-\d{2}$", ipd["start_date"]):
            return False
    if "stop_date" in ipd and ipd["stop_date"]:
        if not re.fullmatch(r"^\d{4}-\d{2}-\d{2}$", ipd["stop_date"]):
            return False
    return True


def bird_summary_query(ipd, user): # pylint: disable=R0912
    ''' Build a bird summary query
        Keyword arguments:
          ipd: request payload
          user: user
        Returns:
          SQL query
    '''
    sql = READ["BSUMMARY"]
    clause = []
    if not valid_dates(ipd):
        return False
    if "start_date" in ipd and ipd["start_date"] and "stop_date" in ipd and ipd["stop_date"]:
        clause.append((" ('%s' BETWEEN DATE(hatch_early) AND DATE(hatch_late)) OR "
                       + "('%s' BETWEEN DATE(hatch_early) AND DATE(hatch_late)) OR "
                       + "(DATE(hatch_early) BETWEEN '%s' AND '%s') OR "
                       + "(DATE(hatch_late) BETWEEN '%s' AND '%s')")
                      % ((ipd['start_date'], ipd["stop_date"]) * 3))
    elif "start_date" in ipd and ipd["start_date"]:
        clause.append(f" (DATE(hatch_early) >= '{ipd['start_date']}' OR " \
                      + f"DATE(hatch_late) >= '{ipd['start_date']}')")
    elif "stop_date" in ipd and ipd["stop_date"]:
        clause.append(f" (DATE(hatch_early) <= '{ipd['stop_date']}' OR " \
                      + f"DATE(hatch_late) <= '{ipd['stop_date']}')")
    if "which" in ipd:
        if ipd["which"] == "mine":
            clause.append(f" user='{user}'")
        elif ipd["which"] == "eligible":
            clause.append(f" (user='{user}' OR user IS NULL)")
        elif ipd["which"] == "claimed":
            clause.append(" user IS NOT NULL")
        elif ipd["which"] == "unclaimed":
            clause.append(" user IS NULL")
    if "alive" in ipd and "dead" in ipd and not (ipd["alive"] and ipd["dead"]):
        if not ipd["alive"]:
            clause.append(" NOT alive")
        elif not ipd["dead"]:
            clause.append(" alive")
    if clause:
        where = ' AND '.join(clause)
        sql = sql.replace("ORDER BY", "WHERE "  + where + " ORDER BY")
    return sql


def clutch_summary_query(ipd):
    ''' Build a clutch summary query
        Keyword arguments:
          ipd: request payload
        Returns:
          SQL query
    '''
    sql = READ["CSUMMARY"]
    clause = []
    if "start_date" in ipd and ipd["start_date"]:
        clause.append(f" (DATE(clutch_start) >= '{ipd['start_date']}' OR " \
                      + f"DATE(clutch_end) >= '{ipd['start_date']}')")
    if "stop_date" in ipd and ipd["stop_date"]:
        clause.append(f" (DATE(clutch_start) <= '{ipd['stop_date']}' OR " \
                      + f"DATE(clutch_end) >= '{ipd['stop_date']}')")
    if clause:
        where = ' AND '.join(clause)
        sql = sql.replace("ORDER BY", "WHERE "  + where + " ORDER BY")
    return sql


def create_relationship(result, bird_id, nest):
    ''' Create a bird relationship
        Keyword arguments:
          result: result dictionary
          bird_id: bird ID
          nest: nest record
        Returns:
          SQL query
    '''
    sql = WRITE['INSERT_REL']
    try:
        bind = ("sired_by", bird_id, nest["sire_id"])
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage("sired_by " + sql_error(err), 500) from err
    try:
        bind = ("sire_to", nest["sire_id"], bird_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage("sire_to " + sql_error(err), 500) from err
    try:
        bind = ("borne_by", bird_id, nest["damsel_id"])
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage("borne_by " + sql_error(err), 500) from err
    try:
        bind = ("damsel_to", nest["damsel_id"], bird_id)
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
    except Exception as err:
        raise InvalidUsage("damsel_to " + sql_error(err), 500) from err


def execute_sql(result, sql, debug, container="data", group=None):
    ''' Build and execute a SQL statement.
        Keyword arguments:
          result: result dictionary
          sql: base SQL statement
          debug:: debug flag
          container: name of dictionary in result disctionary to return rows
        Returns:
          True if successful
    '''
    sql, bind = generate_sql(result, sql)
    if group:
        add = f" GROUP BY {group}"
        if "ORDER BY" in sql:
            sql = sql.replace("ORDER BY", add + " ORDER BY")
        else:
            sql += add
    if debug: # pragma: no cover
        if bind:
            print(sql % bind)
        else:
            print(sql)
    try:
        if bind:
            g.c.execute(sql, bind)
        else:
            g.c.execute(sql)
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    result[container] = []
    if rows:
        result[container] = rows
        result["rest"]["row_count"] = len(rows)
        result["rest"]["sql_statement"] = g.c.mogrify(sql, bind)
        return True
    raise InvalidUsage(f"No rows returned for query {sql}", 404)


def generate_sql(result, sql):
    ''' Generate a SQL statement and tuple of associated bind variables.
        Keyword arguments:
          result: result dictionary
          sql: base SQL statement
    '''
    bind = ()
    query_string = request.query_string
    order = ''
    if query_string:
        if not isinstance(query_string, str):
            query_string = query_string.decode('utf-8')
        ipd = parse_qs(query_string)
        separator = ' AND' if ' WHERE ' in sql else ' WHERE'
        for key, val in ipd.items():
            if key == '_sort':
                order = ' ORDER BY ' + val[0]
            elif key == '_columns':
                sql = sql.replace('*', val[0])
            elif key == '_distinct':
                if 'DISTINCT' not in sql:
                    sql = sql.replace('SELECT', 'SELECT DISTINCT')
            else:
                sql, bind = add_key_value_pair(key, val, separator, sql, bind)
                separator = ' AND'
    sql += order
    if bind:
        result['rest']['sql_statement'] = sql % bind
    else:
        result['rest']['sql_statement'] = sql
    return sql, bind


def get_cv_terms(ccv):
    ''' Get CV terms for a given CV
        Keyword arguments:
          ccv: cv
        Returns:
          list of CV term rows
    '''
    try:
        g.c.execute("SELECT id,cv_term,display_name,definition FROM cv_term_vw " \
                    + "WHERE cv=%s ORDER BY display_name", (ccv))
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    return rows


def get_clutches_in_nest(nest):
    ''' Return an HTML-formatted list of clutches
        Keyword arguments:
          nest: nest name
        Returns:
           Clutches table
    '''
    try:
        g.c.execute("SELECT * FROM clutch_vw WHERE nest=%s ORDER BY 1", (nest,))
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    if rows:
        header = ['Name', 'Notes', 'Clutch early', "Clutch late"]
        clutches = '''
        <h3>Clutches</h3>
        <table id="clutches" class="tablesorter standard">
        <thead>
        <tr><th>
        '''
        clutches += '</th><th>'.join(header) + '</th></tr></thead><tbody>'
        template = '<tr>' + ''.join("<td>%s</td>")*len(header) + "</tr>"
        for row in rows:
            nname = f"<a href='/clutch/{row['name']}'>{row['name']}</a>"
            outcol = [nname, row['notes'], strip_time(row['clutch_early']),
                      strip_time(row["clutch_late"])]
            clutches += template % tuple(outcol)
        clutches += "</tbody></table>"
    else:
        clutches = "There are no clutches in this nest."
    return clutches


def get_clutch_or_nest_count(cnid, which="clutch"):
    ''' Return the number of birds in a clutch or nest
        Keyword arguments:
          cnid: clutch or nest ID
          ehich: "clutch" or "nest"
        Returns:
           Bird count
    '''
    try:
        sql = f"SELECT COUNT(1) AS cnt FROM bird WHERE {which}_id={cnid}"
        g.c.execute(sql)
        rows = g.c.fetchall()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    return rows[0]["cnt"]


def get_key_type_id(key_type):
    ''' Determine the ID for a key type
        Keyword arguments:
          key_type: key type
        Returns:
          key type ID
    '''
    if key_type not in KEY_TYPE_IDS:
        try:
            g.c.execute("SELECT id,cv_term FROM cv_term_vw WHERE cv='key'")
            cv_terms = g.c.fetchall()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
        for term in cv_terms:
            KEY_TYPE_IDS[term['cv_term']] = term['id']
    return KEY_TYPE_IDS[key_type]


def get_record(id_or_name, what="clutch"):
    ''' Get a clutch record
        Keyword arguments:
          id_or_name: clutch ID or name
          what: bird, clutch, or nest
        Returns:
          Record
    '''
    sql = f"SELECT * FROM {what}_vw WHERE "
    if id_or_name.isnumeric():
        sql += "id=%s"
    else:
        sql += "name=%s"
    try:
        g.c.execute(sql, (id_or_name))
        result = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    return result


def get_user_by_name(uname):
    ''' Given a user name, return the user record
        Keyword arguments:
          uname: user name
        Returns:
          user record
    '''
    try:
        g.c.execute("SELECT * FROM user_vw WHERE name=%s", (uname))
        row = g.c.fetchone()
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err
    return row


def nest_summary_query(ipd):
    ''' Build a nest summary query
        Keyword arguments:
          ipd: request payload
        Returns:
          SQL query
    '''
    sql = READ["NSUMMARY"]
    clause = []
    if "start_date" in ipd and ipd["start_date"]:
        clause.append(f" DATE(create_date) >= '{ipd['start_date']}'")
    if "stop_date" in ipd and ipd["stop_date"]:
        clause.append(f" DATE(create_date) <= '{ipd['stop_date']}'")
    if clause:
        where = " AND ".join(clause)
        sql = sql.replace("ORDER BY", "WHERE " + where + " ORDER BY")
    return sql


def sql_error(err):
    ''' Given a MySQL error, return the error message
        Keyword arguments:
          err: MySQL error
    '''
    error_msg = ''
    try:
        error_msg = f"MySQL error [{err.args[0]}]: {err.args[1]}"
    except IndexError:
        error_msg = f"Error: {err}"
    if error_msg:
        print(error_msg)
    return error_msg


def update_property(pid, table, name, value):
    ''' Insert/update a property
        Keyword arguments:
          id: parent ID
          result: result dictionary
          table: parent table
          name: CV term
          value: value
    '''
    stmt = "INSERT INTO %s_property (%s_id,type_id,value) VALUES " \
           + "(!s,getCvTermId(!s,!s,NULL),!s) ON DUPLICATE KEY UPDATE value=!s"
    stmt = stmt % (table, table)
    stmt = stmt.replace('!s', '%s')
    bind = (pid, table, name, value, value)
    try:
        g.c.execute(stmt, bind)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err


def assign_tutor(result, bird_id, tutor_type, tutor_id):
    ''' Insert/update a property
        Keyword arguments:
          result: result dictionary
          bird_id: bird ID
          tutor type: "bird" or "computer"
          tutor_id: tutor ID
    '''
    sql = "INSERT INTO bird_tutor (bird_id,type,tutor_id) VALUES (%s,%s,%s)"
    if tutor_type == "bird":
        if bird_id == tutor_id:
            raise InvalidUsage(f"Bird {tutor_id} can't tutor itself")
        tutor = get_record(tutor_id, "bird")
        if not tutor:
            raise InvalidUsage(f"{tutor_id} is not a valid bird tutor ID")
        if not tutor["alive"]:
            raise InvalidUsage(f"Tutor {bird_id} is dead")
    elif tutor_type == "computer":
        try:
            g.c.execute("SELECT * FROM cv_term_vw WHERE id=%s", (tutor_id,))
            tutor = g.c.fetchone()
        except Exception as err:
            raise InvalidUsage(sql_error(err), 500) from err
        sql = sql.replace("tutor_id", "computer_id")
    else:
        raise InvalidUsage(f"{tutor_type} is not a valid tutor type")
    if "row_count" not in result["rest"]:
        result["rest"]["row_count"] = 0
    try:
        bind = (bird_id, tutor_type, tutor["id"])
        g.c.execute(sql, bind)
        result["rest"]["row_count"] += g.c.rowcount
        #log_bird_event(bird_id, status="moved", user=result['rest']['user'],
        #               location_id=location_id)
    except Exception as err:
        raise InvalidUsage(sql_error(err), 500) from err


# *****************************************************************************
# * General functions                                                         *
# *****************************************************************************

def call_responder(server, endpoint):
    ''' Call a responder
        Keyword arguments:
          server: server
          endpoint: REST endpoint
    '''
    if server not in CONFIG:
        raise Exception(f"Configuration key {server} is not defined")
    url = CONFIG[server]['url'] + endpoint
    try:
        req = requests.get(url, timeout=10)
    except requests.exceptions.RequestException as err:
        print(err)
        raise InvalidUsage(sql_error(err), 500) from err
    if req.status_code == 200:
        return req.json()
    print(f"Could not get response from {url}: {req.text}")
    #raise InvalidUsage("Could not get response from %s: %s" % (url, req.text))
    raise InvalidUsage(req.text, req.status_code)


def create_downloadable(name, header, template, content):
    ''' Generate a dowenloadabe content file
        Keyword arguments:
          name: base file name
          header: table header
          template: header row template
          content: table content
        Returns:
          File name
    '''
    fname = f"{name}_{random_string()}_{datetime.today().strftime('%Y%m%d%H%M%S')}.tsv"
    with open(f"/tmp/{fname}", "w", encoding="utf8") as text_file:
        text_file.write(template % tuple(header))
        text_file.write(content)
    return fname


def humansize(num: int, suffix='B') -> str:
    ''' Return a human-readable storage size
        Keyword arguments:
          num: size
          suffix: default suffix
        Returns:
          string
    '''
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti']:
        if abs(num) < 1024.0:
            return f"{num:.1f} {unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f} P{suffix}"


def random_string(strlen=8):
    ''' Generate a random string of letters and digits
        Keyword arguments:
          strlen: length of generated string
    '''
    components = string.ascii_letters + string.digits
    return ''.join(random.choice(components) for i in range(strlen))


def strip_time(ddt):
    ''' Return the date portion of a datetime
        Keyword arguments:
          ddt: datetime
        Returns:
          String date
    '''
    return ddt.strftime("%Y-%m-%d")
