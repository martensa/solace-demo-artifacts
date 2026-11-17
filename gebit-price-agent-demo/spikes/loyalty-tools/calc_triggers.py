"""Recompute the trigger catalogue numbers with the DESIGN.md 8.1 formulas.

q(p)   = min(avail, v * (p/p0)^eps * H)
GP(p)  = (p_net - c) * q - w * c * max(0, avail - q - target_end)
pct    = floor((ref30 - p) / ref30 * 100)     (integer cents)
price point (shelf promo/markdown): highest x.99/.89/.79/.49 <= exact step price
"""
import math

ENDINGS = (99, 89, 79, 49)

def price_point(exact_cents):
    best = None
    for euros in range(0, exact_cents // 100 + 1):
        for e in ENDINGS:
            c = euros * 100 + e
            if c <= exact_cents and (best is None or c > best):
                best = c
    return best

def pct_shown(ref_c, p_c):
    return (100 * (ref_c - p_c)) // ref_c

def evaluate(name, p0, vat, cost, avail, v, eps, H, w, target_end=0,
             steps=(10, 20, 30, 40), floor_pct=20, max_one_click=30,
             ref30=None, price_override=None):
    ref30 = ref30 or p0
    p0c, refc = round(p0 * 100), round(ref30 * 100)
    rows = []
    cands = [(0, p0c)]
    for s in steps:
        cands.append((s, price_point(math.floor(p0c * (100 - s) / 100))))
    if price_override:
        cands = [(None, round(x * 100)) for x in price_override]
    for s, pc in cands:
        p = pc / 100
        pnet = p / (1 + vat / 100)
        q = min(avail, v * (p / p0) ** eps * H)
        left = max(0.0, avail - q - target_end)
        gp = (pnet - cost) * q - w * cost * left
        margin = (pnet - cost) / pnet * 100
        disc_vs_regular = (p0c - pc) * 100 / p0c
        shown = pct_shown(refc, pc) if pc < refc else 0
        blocked = []
        if pc < p0c and margin < floor_pct:
            blocked.append(f"margin<{floor_pct}")
        if shown > max_one_click:
            blocked.append(f"disc>{max_one_click}")
        rows.append(dict(step=s, price=p, shown=shown, q=q, left=left,
                         gp=gp, margin=margin, disc=disc_vs_regular,
                         blocked=",".join(blocked)))
    base = rows[0]["gp"]
    ok = [r for r in rows[1:] if not r["blocked"]]
    best = max(ok, key=lambda r: r["gp"]) if ok else None
    print(f"\n== {name}: p0 {p0:.2f} vat {vat} cost {cost:.2f} avail {avail} v {v}/h eps {eps} H {H} h w {w} target_end {target_end} ref30 {ref30:.2f}")
    print(" step  price  shown   units  left    GP     dGP  margin  blocked")
    for r in rows:
        st = "none" if r["step"] == 0 else (str(r["step"]) if r["step"] is not None else "-")
        print(f" {st:>4} {r['price']:6.2f} {('-'+str(r['shown'])+'%') if r['shown'] else '':>6} {r['q']:7.1f} {r['left']:5.1f} {r['gp']:7.1f} {r['gp']-base:+6.1f} {r['margin']:6.1f}%  {r['blocked']}")
    if best:
        print(f" -> slot A: {best['price']:.2f} (shown -{best['shown']} %), dGP {best['gp']-base:+.1f}")
    return rows

# TR1 Ente (DESIGN S1, reproduce)
evaluate("TR1 GEBIT Ente (slow seller)", 8.67, 19, 4.40, 42, 0.85, -2.0, 30, 0.4,
         floor_pct=20)
# TR2 Kaffeepads (on plan, overstock after delivery advice 72, target end stock 34)
evaluate("TR2 Kaffeepads 36 St (overstock + Lieferavis)", 4.99, 7, 2.45, 40 + 72, 1.4, -2.2, 30, 0.3,
         target_end=34, floor_pct=12)
# TR6 Valentins-Pralinen after season (H = 66 store hours until Tue 23.02. 20:00)
evaluate("TR6 Valentins-Pralinen (season end)", 6.99, 7, 3.20, 60, 0.36, -2.0, 66, 0.6,
         floor_pct=12)

# TR3 Espresso vs competitor flyer 6.99 (relative-price model calibrated on observed drop)
p0, comp, vplan, vobs, H, stock, cost, vat = 7.99, 6.99, 1.5, 0.9, 42, 72, 4.20, 7
eps_rel = math.log(vobs / vplan) / math.log(p0 / comp)
print(f"\n== TR3 Espresso vs competitor {comp}: eps_rel {eps_rel:.2f} (from {vobs}/h observed vs plan {vplan}/h)")
for p in (7.99, 7.49, 6.99):
    v = vplan * (p / comp) ** eps_rel if p > comp else vplan
    q = min(stock, v * H)
    pnet = p / (1 + vat / 100)
    gp = (pnet - cost) * q
    margin = (pnet - cost) / pnet * 100
    gap = (p - comp) / comp * 100
    shown = pct_shown(round(p0 * 100), round(p * 100)) if p < p0 else 0
    print(f"  {p:.2f}: v {v:.2f}/h units {q:5.1f} GP {gp:6.1f} margin {margin:5.1f}% gap {gap:4.1f}% shown -{shown}% stock_ok {stock >= v * H}")

# TR4 tied offer Chips -> Guacamole -30 %
g, gcost, gvat = 2.99, 1.35, 7
gp_c = math.floor(round(g * 100) * 0.70)
gprice = gp_c / 100
gnet = gprice / (1 + gvat / 100)
print(f"\n== TR4 Guacamole tied offer: {g:.2f} -> {gprice:.2f}, net {gnet:.3f}, margin {(gnet-gcost)/gnet*100:.1f}%, unit price 1 kg = {gprice*5:.2f}")
lift, conf = 2.6, 0.18
lift_norm = min(1, (lift - 1) / 3)
for label, s, match in (("anonymous", 0.5, 0.6), ("Filmabend (Snacks/Dips)", 0.5, 1.0)):
    pacc = 0.20 + 0.30 * s
    egp = pacc * (gnet - gcost)
    print(f"  {label}: P_accept {pacc:.2f} E[GP] {egp:.3f} score {lift_norm*match*egp:.3f}")

# TR5 member coupon, persona Kaffeepause: Cantuccini -30 % vs Kaffeepads -30 % (clearance)
for name, p, c, vat, lift, match, clear in (("Cantuccini 200 g", 2.29, 0.95, 7, 2.9, 1.0, 0.0),
                                             ("Kaffeepads 36 St", 4.99, 2.45, 7, 1.6, 1.0, None)):
    pc = math.floor(round(p * 100) * 0.70) / 100
    pnet = pc / (1 + vat / 100)
    pacc = 0.20 + 0.30 * 0.5
    egp = pacc * (pnet - c)
    if clear is None:
        # clearance bonus w*c*min(1, L0/stock) with TR2 numbers (w 0.3, L0 = 112-42-34 = 36, stock 112)
        clear = 0.3 * c * min(1, 36 / 112)
    ln = min(1, (lift - 1) / 3)
    print(f"  TR5 {name}: {p:.2f} -> {pc:.2f} margin {(pnet-c)/pnet*100:.1f}% E[GP] {egp:.3f} clear {clear:.3f} score {ln*match*(egp+clear):.3f}")

# points: 1 point per full 2 EUR (matches GEBIT sample: 8.67 -> 4)
for total in (8.67, 14.88, 12.16):
    print(f"  points for {total:.2f} EUR: {math.floor(total/2)}")
