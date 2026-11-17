"""G0-13: vergleicht die SQL-Plausibilitaet (95-sanity.sql) mit calc_output.txt.

Usage: python3 -I compare_calc.py <sanity-log> <calc_output.txt>
Vergleicht TR1/TR2/TR6 Stufen (Preis, gezeigt, Stueck, Rest, DB, Delta,
Marge, Sperre), TR3 (Preis, v, Stueck, DB, Marge, Abstand), TR4/TR5
(Preis, Marge) und Punkte. Ausgabe: je Block n/n identisch.
"""
import re
import sys


def num(s):
    s = s.strip().replace("%", "").replace("+", "")
    return f"{float(s):.1f}" if s and s not in ("-",) else ""


def calc_rows(text):
    rows, tr = {}, None
    for line in text.splitlines():
        m = re.match(r"== (TR\d)", line)
        if m:
            tr = m.group(1)
            continue
        m = re.match(r"\s+(none|\d+)\s+(\d+\.\d\d)\s+(-\d+%)?\s+([\d.]+)\s+([\d.]+)\s+(-?[\d.]+)\s+"
                     r"([+-][\d.]+)\s+(-?[\d.]+)%\s*(.*)$", line)
        if m and tr in ("TR1", "TR2", "TR6"):
            st, pr, sh, u, l, gp, d, mg, bl = m.groups()
            rows[(tr, st)] = (pr, (sh or "").strip(), num(u), num(l), num(gp), num(d), num(mg), bl.strip())
    return rows


def sql_rows(text):
    rows = {}
    blk = text.split("== S5", 1)[1].split("== S6", 1)[0]
    for line in blk.splitlines():
        p = [x.strip() for x in line.split("|")]
        if len(p) == 10 and p[0].startswith("TR"):
            tr, st, pr, sh, u, l, gp, d, mg, bl = p
            rows[(tr, st)] = (pr, sh, num(u), num(l), num(gp), num(d), num(mg), bl)
    return rows


def main():
    sql = open(sys.argv[1], encoding="utf-8").read()
    calc = open(sys.argv[2], encoding="utf-8").read()
    a, b = calc_rows(calc), sql_rows(sql)
    same = [k for k in a if b.get(k) == a[k]]
    print(f"TR1/TR2/TR6 Stufen: {len(same)}/{len(a)} identisch (SQL-Zeilen {len(b)})")
    for k in a:
        if b.get(k) != a[k]:
            print("  DIFF", k, "calc", a[k], "sql", b.get(k))

    # TR3
    c3 = re.findall(r"(\d\.\d\d): v ([\d.]+)/h units\s+([\d.]+) GP\s+([\d.]+) margin\s+([\d.]+)% gap\s+([\d.]+)%", calc)
    blk = sql.split("== S7", 1)[1].split("== S8", 1)[0]
    s3 = []
    for line in blk.splitlines():
        p = [x.strip() for x in line.split("|")]
        if len(p) == 7 and re.match(r"-?\d", p[0]):
            s3.append((p[1], p[2], p[3], p[4], p[5].rstrip("%"), p[6].rstrip("%")))
    ok3 = sum(1 for x, y in zip(c3, s3) if x == y)
    print(f"TR3 Espresso: {ok3}/{len(c3)} identisch")

    # TR4/TR5 coupon prices and margins
    c45 = {"article003": re.search(r"-> (\d\.\d\d), net [\d.]+, margin ([\d.]+)%", calc).groups()}
    for name, art in (("Cantuccini", "article008"), ("Kaffeepads", "article030")):
        c45[art] = re.search(name + r"[^:]*: [\d.]+ -> (\d\.\d\d) margin ([\d.]+)%", calc).groups()
    blk = sql.split("== S8", 1)[1].split("== S9", 1)[0]
    s45 = {}
    for line in blk.splitlines():
        p = [x.strip() for x in line.split("|")]
        if len(p) == 6 and p[0].startswith("OFF-"):
            s45[p[1]] = (p[3], p[4].rstrip("%"))
    ok45 = sum(1 for k in c45 if s45.get(k) == c45[k])
    print(f"TR4/TR5 Coupons: {ok45}/{len(c45)} identisch")

    # points
    cp = dict(re.findall(r"points for ([\d.]+) EUR: (\d+)", calc))
    blk = sql.split("== S9", 1)[1].split("== S10", 1)[0]
    sp = {}
    for line in blk.splitlines():
        p = [x.strip() for x in line.split("|")]
        if len(p) == 2 and re.match(r"\d", p[0]):
            sp[p[0]] = p[1]
    okp = sum(1 for k in cp if sp.get(k) == cp[k])
    print(f"Punkte: {okp}/{len(cp)} identisch")
    total = len(a) + len(c3) + len(c45) + len(cp)
    good = len(same) + ok3 + ok45 + okp
    print(f"GESAMT {good}/{total}")
    sys.exit(0 if good == total else 1)


if __name__ == "__main__":
    main()
