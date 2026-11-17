import sys, re
for fn in sys.argv[1:]:
    lines = open(fn).read().splitlines()
    out = []
    for l in lines:
        s = l.strip()
        if not s or s.startswith("//"):
            continue
        if s.startswith("option java"):
            continue
        out.append(l.rstrip())
    print("// ---- " + fn)
    print("\n".join(out))
