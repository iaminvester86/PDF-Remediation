import json,sys
d=json.load(open(sys.argv[1]))
def walk(o):
    if isinstance(o,dict):
        if 'ruleSummaries' in o:
            for r in o['ruleSummaries']: print('  FAIL', r.get('clause'), r.get('testNumber'), r.get('failedChecks'), '-', r.get('description','')[:120])
        if 'isCompliant' in o: print('  isCompliant =', o['isCompliant'], o.get('profileName',''))
        for v in o.values(): walk(v)
    elif isinstance(o,list):
        for v in o: walk(v)
walk(d)
