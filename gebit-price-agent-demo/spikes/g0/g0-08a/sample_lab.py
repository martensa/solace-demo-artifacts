"""G0-08a: read-only lab sampler, one sample every --interval seconds.

  python sample_lab.py --out logs/samples.jsonl --tasks-out logs/tasks.jsonl \
      --duration 1900 --interval 60

Per sample (all read-only):
- kubectl get pods (sam-solace-lab): restarts, start time, ready of
  awe/gwe/str (+ postgresql, seaweedfs) and of the G0-01 stub (gpos-g0)
- kubectl top pods: CPU/memory of the same pods
- SEMP v2 monitor on solace-1 (localhost:8080): VPN sam spool usage and
  message count, every queue on VPN sam (messages, bytes); VPN default
  spool (input side). Admin creds are read from event-mesh-deployment
  terraform.tfvars at runtime and never printed or logged.
- SAM tasks API (samapi.sh, newest 100 runs): runs of the stub workflow
  gpos-spike-p01-pos since --since, with status, start/end and the
  sequence id (metadata.offset in initialRequestText).
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TFVARS = HERE.parents[3] / "event-mesh-deployment" / "terraform" / "terraform.tfvars"
SEMP = "http://localhost:8080/SEMP/v2/monitor"
NS = "sam-solace-lab"
STUB_NS = "gpos-g0"
WORKFLOW = "gpos-spike-p01-pos"
ENTRYPOINT_ID = "01a1c9ff-6a43-7e97-810e-2b062aecda36"
OFFSET_RE = re.compile(r'"offset":\s*"(\d+)"')


def tfvar(name: str) -> str:
    m = re.search(rf'^{name}\s*=\s*"(.*)"', TFVARS.read_text(), re.M)
    return m.group(1) if m else ""


AUTH = "Basic " + base64.b64encode(
    f"{tfvar('solace_1_username')}:{tfvar('solace_1_password')}".encode()).decode()


def semp(path: str) -> dict:
    req = urllib.request.Request(SEMP + path, headers={"Authorization": AUTH})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def sh(cmd: list[str], timeout: float = 20) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          check=True).stdout


def role(name: str) -> str:
    # "seaweedfs" contains "awe": match the SAM roles as "-awe-" etc.
    for k in ("seaweedfs", "postgresql", "p01-stub"):
        if k in name:
            return k
    for k in ("awe", "gwe", "str"):
        if f"-{k}-" in name:
            return k
    return ""


def pods() -> dict:
    res = {}
    for ns in (NS, STUB_NS):
        for p in json.loads(sh(["kubectl", "get", "pods", "-n", ns, "-o", "json"]))["items"]:
            r = role(p["metadata"]["name"])
            if not r:
                continue
            cs = (p["status"].get("containerStatuses") or [{}])[0]
            res[r] = {"pod": p["metadata"]["name"], "restarts": cs.get("restartCount"),
                      "ready": cs.get("ready"), "phase": p["status"].get("phase"),
                      "started": (cs.get("state", {}).get("running") or {}).get("startedAt")}
    return res


def top() -> dict:
    res = {}
    for ns in (NS, STUB_NS):
        try:
            txt = sh(["kubectl", "top", "pods", "-n", ns, "--no-headers"])
        except subprocess.CalledProcessError as exc:
            res[f"_error_{ns}"] = exc.stderr.strip()[:200]
            continue
        for line in txt.splitlines():
            f = line.split()
            if len(f) >= 3 and role(f[0]):
                res[role(f[0])] = {"cpu_m": int(f[1].rstrip("m")) if f[1].endswith("m")
                                   else int(float(f[1]) * 1000),
                                   "mem_mi": int(f[2].rstrip("Mi")) if f[2].endswith("Mi")
                                   else f[2]}
    return res


def broker() -> dict:
    sel = "msgVpnName,msgSpoolUsage,maxMsgSpoolUsage,msgSpoolMsgCount,rxMsgRate,txMsgRate"
    res = {}
    for vpn in ("sam", "default"):
        res[f"vpn_{vpn}"] = semp(f"/msgVpns/{vpn}?select={sel}")["data"]
    d = semp("/msgVpns/sam/queues?count=100")
    queues = {}
    for q, c in zip(d["data"], d["collections"]):
        queues[q["queueName"]] = {"msgs": c.get("msgs", {}).get("count", 0),
                                  "bytes": q.get("msgSpoolUsage", 0),
                                  "peak": q.get("msgSpoolPeakUsage", 0),
                                  "unacked": q.get("txUnackedMsgCount", 0)}
    res["sam_queue_count"] = len(queues)
    res["sam_queue_msgs_total"] = sum(v["msgs"] for v in queues.values())
    res["sam_queue_bytes_total"] = sum(v["bytes"] for v in queues.values())
    nonzero = {k: v for k, v in queues.items() if v["msgs"] or v["bytes"]}
    res["sam_queues_nonzero"] = nonzero
    for k, v in queues.items():
        if ("01a1c9ff" in k or k.endswith("str/builtin-tools-worker")
                or "task_log" in k or "resource_tracker" in k):
            res.setdefault("sam_queues_watch", {})[k] = v
    return res


def tasks(since: float, seen: dict, out) -> dict:
    try:
        txt = subprocess.run([str(HERE / "samapi.sh"), "/api/v1/tasks?pageSize=100"],
                             capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    if txt.returncode != 0:
        return {"error": (txt.stderr or txt.stdout).strip()[:200]}
    data = json.loads(txt.stdout)["data"]
    new = changed = mine = 0
    for t in data:
        if (t.get("subject") or {}).get("name") != WORKFLOW:
            continue
        st = datetime.fromisoformat(t["startTime"]).timestamp()
        if st < since:
            continue
        mine += 1
        m = OFFSET_RE.search(t.get("initialRequestText") or "")
        et = datetime.fromisoformat(t["endTime"]).timestamp() if t.get("endTime") else None
        rec = {"id": t["id"], "status": t.get("status"), "start": st, "end": et,
               "sam_s": round(et - st, 4) if et else None,
               "offset": int(m.group(1)) if m else None,
               "entrypoint_ok": (t.get("trigger") or {}).get("entrypointId") == ENTRYPOINT_ID,
               "channel": (t.get("trigger") or {}).get("channel"), "user": t.get("userId"),
               "events": t.get("eventCount"),
               "tokens": (t.get("totalInputTokens") or 0) + (t.get("totalOutputTokens") or 0)}
        old = seen.get(t["id"])
        if old is None:
            new += 1
        elif old["status"] != rec["status"]:
            changed += 1
        else:
            continue
        seen[t["id"]] = rec
        out.write(json.dumps({"t": round(time.time(), 3), **rec}) + "\n")
        out.flush()
    oldest = min((datetime.fromisoformat(t["startTime"]).timestamp() for t in data),
                 default=None)
    return {"page": len(data), "mine_in_page": mine, "new": new, "changed": changed,
            "seen_total": len(seen), "page_oldest_age_s":
            round(time.time() - oldest, 1) if oldest else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--tasks-out", required=True)
    ap.add_argument("--duration", type=float, default=1900)
    ap.add_argument("--interval", type=float, default=60)
    ap.add_argument("--since", type=float, default=0.0, help="epoch; default = now")
    a = ap.parse_args()
    since = a.since or time.time()
    out = open(a.out, "a", encoding="utf-8")
    tout = open(a.tasks_out, "a", encoding="utf-8")
    seen: dict = {}
    t0 = time.time()
    n = 0
    while True:
        s = {"t": round(time.time(), 3), "n": n,
             "clock": time.strftime("%H:%M:%S")}
        for name, fn in (("pods", pods), ("top", top), ("broker", broker)):
            try:
                s[name] = fn()
            except Exception as exc:  # noqa: BLE001 - keep sampling
                s[name] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        try:
            s["tasks"] = tasks(since, seen, tout)
        except Exception as exc:  # noqa: BLE001
            s["tasks"] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        out.write(json.dumps(s, ensure_ascii=False) + "\n")
        out.flush()
        p, tp, b = s["pods"], s["top"], s["broker"]
        line = [s["clock"]]
        for r in ("awe", "gwe", "str"):
            line.append(f"{r} rs={p.get(r, {}).get('restarts')} "
                        f"cpu={tp.get(r, {}).get('cpu_m')}m mem={tp.get(r, {}).get('mem_mi')}Mi")
        if "vpn_sam" in b:
            line.append(f"sam spool={b['vpn_sam']['msgSpoolUsage']}B "
                        f"msgs={b['vpn_sam']['msgSpoolMsgCount']} "
                        f"qmsgs={b['sam_queue_msgs_total']}")
        line.append(f"tasks={s['tasks']}")
        print(" | ".join(line), flush=True)
        n += 1
        if time.time() - t0 + a.interval > a.duration:
            break
        time.sleep(max(0.0, t0 + n * a.interval - time.time()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
