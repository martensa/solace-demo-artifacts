#!/usr/bin/env python3
"""Deterministic seed generator for the mfg_plant MongoDB store.

Produces station-telemetry.ndjson and material-consumption.ndjson
in this directory. Both files are checked in; re-run only when the
storyline changes. Storyline (ECO-2025-118):

- Plant 2 (Graz) L3 builds the IX-450 impact driver. From
  2025-07-28 it builds with the new HD-22 sintered clutch disc,
  but station EOL-2 still runs the OLD torque calibration
  (spec 17.5-18.5 Nm, station_spec_revision B) because the ECO
  was never acknowledged -> measured ~22 Nm -> FAIL.
- Plant 1 (Hamburg) L2 builds the CK-350 clutch kit. It
  acknowledged the ECO on 2025-07-21: from 07-22 the station
  tests against the NEW spec 21.5-22.5 Nm (revision C) -> PASS.
- Plant 1 consumption of MAT_CLT_HD22 ramps from ~180/day to
  ~460/day (vs planned 120/day), draining the balance from 7450
  to ~1850 by 2025-08-05 (matches mfg_scm.mfg_inventory).
"""

import json
import random
from datetime import datetime, timedelta

random.seed(118)  # deterministic

HAM = {"plant_id": "PLANT_HAM", "plant_name": "Plant 1 - Hamburg",
       "city": "Hamburg", "country": "Germany"}
GRZ = {"plant_id": "PLANT_GRZ", "plant_name": "Plant 2 - Graz",
       "city": "Graz", "country": "Austria"}

START = datetime(2025, 7, 10)
END = datetime(2025, 8, 5)
ECO_ADOPTED_HAM = datetime(2025, 7, 22)   # HAM builds to new spec
HD22_AT_GRZ = datetime(2025, 7, 28)       # GRZ builds HD-22, old spec
L3_START = datetime(2025, 7, 24)          # PRD-118-4718 starts

SHIFTS = [("Early", 6), ("Late", 14)]

telemetry = []
consumption = []
seq = {"t": 0, "c": 0}


def iso(dt):
    return {"$date": dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")}


def tid(dt, plant, line):
    seq["t"] += 1
    return "TST_%s_%s_%s_%04d" % (
        dt.strftime("%Y%m%d_%H%M%S"), plant["plant_id"][-3:], line, seq["t"])


def cid(dt, plant):
    seq["c"] += 1
    return "ISS_%s_%s_%04d" % (
        dt.strftime("%Y%m%d_%H%M"), plant["plant_id"][-3:], seq["c"])


def add_test(dt, plant, line, station, prod_order, material, name, serial,
             ttype, measured, unit, smin, smax, spec_rev, cycle, operator):
    result = "PASS" if smin <= measured <= smax else "FAIL"
    doc = {
        "_id": tid(dt, plant, line),
        "ts": iso(dt),
        "plant": plant,
        "line_id": line,
        "station_id": station,
        "prod_order_id": prod_order,
        "product": {"material_id": material, "name": name},
        "serial_no": serial,
        "test": {"type": ttype, "measured": round(measured, 2),
                 "unit": unit, "spec_min": smin, "spec_max": smax,
                 "station_spec_revision": spec_rev},
        "result": result,
        "cycle_time_s": round(cycle, 1),
        "operator_id": operator,
        "shift": "Early" if dt.hour < 14 else "Late",
    }
    if result == "FAIL":
        doc["failure_code"] = ("TORQUE_OUT_OF_SPEC" if ttype == "torque"
                               else ttype.upper() + "_OUT_OF_SPEC")
    telemetry.append(doc)


def day_range(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def times_in_day(day, n):
    out = []
    for _, shift_start in SHIFTS:
        for i in range(n // 2):
            out.append(day.replace(hour=shift_start)
                       + timedelta(minutes=int(i * (7 * 60 / max(1, n // 2)))
                                   + random.randint(0, 12)))
    return sorted(out)


serial_no = 40000

# --- Plant 2 Graz, L3: IX-450 EOL torque (THE incident line) ----
for day in day_range(L3_START, END):
    for t in times_in_day(day, 20):
        serial_no += 1
        if t >= HD22_AT_GRZ:
            measured = random.gauss(22.0, 0.22)   # HD-22 reality
        else:
            measured = random.gauss(18.1, 0.15)   # HD-20 build
        add_test(t, GRZ, "L3", "EOL-2", "PRD-118-4718",
                 "FG_IX450", "IX-450 Cordless Impact Driver 18V",
                 "IX450-%06d" % serial_no,
                 "torque", measured, "Nm", 17.5, 18.5, "B",
                 random.gauss(42, 4), "OP_GRZ_%02d" % random.randint(1, 6))

# --- Plant 2 Graz, L1: AG-900 runout (healthy line) --------------
for day in day_range(START, END):
    for t in times_in_day(day, 8):
        serial_no += 1
        add_test(t, GRZ, "L1", "EOL-1", "PRD-118-4692",
                 "FG_AG900", "AG-900 Angle Grinder 125mm",
                 "AG900-%06d" % serial_no,
                 "runout", max(0.01, random.gauss(0.032, 0.008)),
                 "mm", 0.0, 0.05, "A",
                 random.gauss(35, 3), "OP_GRZ_%02d" % random.randint(1, 6))

# --- Plant 1 Hamburg, L2: CK-350 engagement torque ---------------
for day in day_range(START, END):
    for t in times_in_day(day, 12):
        serial_no += 1
        if t >= ECO_ADOPTED_HAM:
            measured, smin, smax, rev = random.gauss(22.0, 0.2), 21.5, 22.5, "C"
            po = "PRD-118-4711"
        else:
            measured, smin, smax, rev = random.gauss(18.0, 0.18), 17.5, 18.5, "B"
            po = "PRD-118-4680"
        add_test(t, HAM, "L2", "EOL-4", po,
                 "FG_CK350", "CK-350 Clutch Kit",
                 "CK350-%06d" % serial_no,
                 "torque", measured, "Nm", smin, smax, rev,
                 random.gauss(55, 5), "OP_HAM_%02d" % random.randint(1, 8))

# --- Plant 1 Hamburg, L4: BR-120 pressure hold (healthy) ---------
for day in day_range(START, END):
    for t in times_in_day(day, 6):
        serial_no += 1
        add_test(t, HAM, "L4", "EOL-7", "PRD-118-4703",
                 "FG_BR120", "BR-120 Brake Caliper Front",
                 "BR120-%06d" % serial_no,
                 "pressure_drop", max(0.0, random.gauss(0.04, 0.02)),
                 "bar", 0.0, 0.1, "B",
                 random.gauss(48, 4), "OP_HAM_%02d" % random.randint(1, 8))


def add_issue(dt, plant, material, desc, prod_order, line, qty, balance):
    consumption.append({
        "_id": cid(dt, plant),
        "ts": iso(dt),
        "plant": {"plant_id": plant["plant_id"],
                  "plant_name": plant["plant_name"]},
        "material_id": material,
        "description": desc,
        "prod_order_id": prod_order,
        "line_id": line,
        "qty_issued": qty,
        "balance_after": balance,
        "uom": "EA",
    })


# --- HAM: HD-20 until 07-21 (~120/day), then HD-22 ramp ----------
bal20 = 1650
for day in day_range(START, datetime(2025, 7, 21)):
    for t in times_in_day(day, 4):
        qty = random.randint(26, 34)
        bal20 = max(310, bal20 - qty)
        add_issue(t, HAM, "MAT_CLT_HD20", "HD-20 Clutch Disc (hardened)",
                  "PRD-118-4680", "L2", qty, bal20)

bal22 = 7450
for day in day_range(ECO_ADOPTED_HAM, END):
    ramp_day = (day - ECO_ADOPTED_HAM).days
    daily = min(480, 225 + ramp_day * 25)          # 225 -> 480/day
    n = 8
    for t in times_in_day(day, n):
        qty = max(10, int(random.gauss(daily / n, 4)))
        bal22 = max(1850, bal22 - qty)
        add_issue(t, HAM, "MAT_CLT_HD22", "HD-22 Clutch Disc (sintered)",
                  "PRD-118-4711", "L2", qty, bal22)

# --- GRZ: small HD-22 consumption from 07-28 ---------------------
balg = 1200
for day in day_range(HD22_AT_GRZ, END):
    for t in times_in_day(day, 2):
        qty = random.randint(12, 20)
        balg = max(950, balg - qty)
        add_issue(t, GRZ, "MAT_CLT_HD22", "HD-22 Clutch Disc (sintered)",
                  "PRD-118-4718", "L3", qty, balg)

# --- HAM: spring kits + bearings for realism ---------------------
bals, balb = 8900, 19800
for day in day_range(START, END):
    for t in times_in_day(day, 2):
        q = random.randint(70, 95)
        bals = max(5200, bals - q)
        add_issue(t, HAM, "MAT_SPR_KIT", "Diaphragm Spring Kit",
                  "PRD-118-4711", "L2", q, bals)
        q = random.randint(260, 330)
        balb = max(14500, balb - q)
        add_issue(t, HAM, "MAT_BRG_6205", "6205-2RS Deep Groove Bearing",
                  "PRD-118-4703", "L4", q, balb)

telemetry.sort(key=lambda d: d["ts"]["$date"])
consumption.sort(key=lambda d: d["ts"]["$date"])

import os
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "station-telemetry.ndjson"), "w") as f:
    for doc in telemetry:
        f.write(json.dumps(doc) + "\n")
with open(os.path.join(here, "material-consumption.ndjson"), "w") as f:
    for doc in consumption:
        f.write(json.dumps(doc) + "\n")

fails = sum(1 for d in telemetry if d["result"] == "FAIL")
print("telemetry: %d docs (%d FAIL)" % (len(telemetry), fails))
print("consumption: %d docs" % len(consumption))
print("HD-22 HAM end balance: %d" % bal22)
