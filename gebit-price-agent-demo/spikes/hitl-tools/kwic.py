import sys, re
path = sys.argv[1]
before = int(sys.argv[2]); after = int(sys.argv[3])
kws = sys.argv[4:]
data = open(path, 'rb').read().decode('latin-1')
seen = set()
for kw in kws:
    for m in re.finditer(kw, data):
        s = max(0, m.start()-before); e = min(len(data), m.end()+after)
        snip = data[s:e].replace('\n', ' | ')
        key = snip[before-40:before+80]
        if key in seen: continue
        seen.add(key)
        print('>>', snip)
