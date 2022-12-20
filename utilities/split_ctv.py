import argparse
import json

def write_sublist(filenum, one_list):
    filename = 'ctv_list_%s.json' % (str(filenum))
    print("Write file %s" % (filename))
    outfile = open(filename, 'w')
    print(len(one_list))
    out_json = dict()
    out_json["file type"] = "Neu3 task list"
    out_json["file version"] = 1
    out_json["task list"] = one_list
    outfile.write(json.dumps(out_json))
    outfile.close()


if __name__ == '__main__':
    PARSER = argparse.ArgumentParser(description='Split a cell type verification JSON file')
    PARSER.add_argument('--file', dest='filename', action='store',
                        help='Filename')
    ARGS = PARSER.parse_args()
    body = filenum = 1
    with open(ARGS.filename) as x: f = x.read()
    x.close()
    in_json = json.loads(f)
    one_list = []
    for task in in_json['task list']:
        one_list.append(task)
        if body == 1000:
            body = 1
            write_sublist(filenum, one_list)
            filenum += 1
            one_list = []
        else:
            body += 1
    if body >= 1:
        write_sublist(filenum, one_list)
