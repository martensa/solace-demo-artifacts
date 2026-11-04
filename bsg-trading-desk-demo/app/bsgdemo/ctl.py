"""bsgctl: publish demo control events (used by the Makefile through
``kubectl exec deploy/demo-ui -- python -m bsgdemo.ctl ...``).

  scenario wide_spread --issuer alpha --duration 30
  scenario market_wide --duration 30
  scenario stale --issuer beta --duration 20
  scenario reset
  watches clear
  action plausibility_check --issuer alpha
  reset                      scenario reset + clear watches + issuer status normal
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import topics
from .mqttio import Bus


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bsgctl")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scenario")
    sc.add_argument("name", choices=["wide_spread", "market_wide", "stale", "reset"])
    sc.add_argument("--issuer", default="alpha")
    sc.add_argument("--duration", type=int, default=30)
    w = sub.add_parser("watches")
    w.add_argument("op", choices=["clear", "rearm"])
    ac = sub.add_parser("action")
    ac.add_argument("name", choices=["plausibility_check", "release", "reset"])
    ac.add_argument("--issuer", default="alpha")
    sub.add_parser("reset")
    a = ap.parse_args(argv)

    bus = Bus("bsgctl").start(wait_s=10)
    if not bus.connected.is_set():
        print("ERROR: no MQTT connection", file=sys.stderr)
        return 1
    msgs: list[tuple[str, dict]] = []
    if a.cmd == "scenario":
        cmd = {"scenario": a.name, "duration_s": a.duration}
        if a.name in ("wide_spread", "stale"):
            cmd["issuer"] = a.issuer
        msgs.append((topics.CONTROL_SCENARIO, cmd))
    elif a.cmd == "watches":
        msgs.append((topics.CONTROL_WATCH, {"cmd": a.op}))
    elif a.cmd == "action":
        msgs.append((topics.DESK_ACTIONS, {"action": a.name, "issuer": a.issuer, "by": "bsgctl"}))
    elif a.cmd == "reset":
        msgs += [(topics.CONTROL_SCENARIO, {"scenario": "reset"}),
                 (topics.CONTROL_WATCH, {"cmd": "clear"}),
                 (topics.DESK_ACTIONS, {"action": "reset", "by": "bsgctl"})]
    for topic, m in msgs:
        info = bus.client.publish(topic, json.dumps(m), qos=1)
        info.wait_for_publish(timeout=5)
        print(f"published {topic} {m}")
    time.sleep(0.3)
    bus.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
