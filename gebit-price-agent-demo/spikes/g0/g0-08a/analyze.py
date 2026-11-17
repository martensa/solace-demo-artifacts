"""G0-08a: evaluate one load run (client times, SAM tasks, lab samples).

  python analyze.py --tag main > logs/main-analysis.txt
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(p / 100.0 * len(s) + 0.5)) - 1))
    return s[k]


def stats(v: list[float]) -> str:
    if not v:
        return "n=0"
    return (f"n={len(v)} min {min(v):.3f} p50 {pct(v, 50):.3f} p95 {pct(v, 95):.3f} "
            f"p99 {pct(v, 99):.3f} max {max(v):.3f} mean {statistics.fmean(v):.3f}")


def load(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.open(encoding="utf-8")] if p.exists() else []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="main")
    a = ap.parse_args()
    logs = HERE / "logs"
    run = load(logs / f"{a.tag}-run.jsonl")
    start = next(r for r in run if r["kind"] == "start")
    seq_base = start["seq_base"]
    sent = {r["seq"]: r for r in run if r["kind"] == "sent"}
    recv = {r["seq"]: r for r in run if r["kind"] == "recv"}
    summ = {r["seq"]: r for r in run if r["kind"] == "summary"}
    other = Counter(r["kind"] for r in run)
    t_first = min(r["t"] for r in sent.values())
    t_last = max(r["t"] for r in sent.values())
    print(f"== run {a.tag}: seq_base {seq_base}, sent {len(sent)}, bursts "
          f"{start['bursts']} x {start['burst']} every {start['interval_s']:.1f} s")
    print(f"first send {t_first:.1f}, last send {t_last:.1f}, span {t_last - t_first:.1f} s, "
          f"rate {len(sent) / (t_last - t_first + start['interval_s']) * 3600:.0f}/h")
    print("record kinds:", dict(other))
    ok = [s for s in summ.values() if s.get("reply") and not s.get("err")]
    durs = [s["dur_s"] for s in ok]
    print("\n== client: event -> successOutput (s)")
    print("all      ", stats(durs))
    by_v = defaultdict(list)
    for s in ok:
        by_v[s.get("verdict")].append(s["dur_s"])
    for v, d in sorted(by_v.items(), key=lambda x: str(x[0])):
        print(f"{str(v):9}", stats(d))
    by_idx = defaultdict(list)
    for seq, s in summ.items():
        if s.get("reply") and not s.get("err"):
            by_idx[sent[seq]["idx"]].append(s["dur_s"])
    print("by position in burst:")
    for i in sorted(by_idx):
        print(f"  idx {i}", stats(by_idx[i]))
    by_b = defaultdict(list)
    for seq, s in summ.items():
        if s.get("reply") and not s.get("err"):
            by_b[sent[seq]["burst"]].append(s["dur_s"])
    bmax = [max(v) for v in by_b.values()]
    print("burst max (last of 7 done):", stats(bmax))
    halves = defaultdict(list)
    nb = start["bursts"]
    for b, v in by_b.items():
        halves["1st half" if b < nb / 2 else "2nd half"].extend(v)
    for h, v in sorted(halves.items()):
        print(f"{h}:", stats(v))
    errs = [s for s in summ.values() if s.get("err")]
    miss = [s for s in summ.values() if not s.get("reply")]
    sha_bad = [s for s in ok if not s.get("sha_equal")]
    lit = [r for r in recv.values() if r.get("literal")]
    print(f"\n== failures: err {len(errs)}, missing {len(miss)}, "
          f"unmatched {other.get('recv_unmatched', 0)}, dup {other.get('recv_dup', 0)}, "
          f"sha mismatch {len(sha_bad)}, '{{{{' literal {len(lit)}, "
          f"puback missing {other.get('puback_missing', 0) + other.get('puback_error', 0)}, "
          f"disconnects {other.get('disconnect', 0)}")
    for s in errs[:10]:
        print("  err", s["seq"], recv.get(s["seq"], {}).get("error_body", "")[:300])
    for s in miss[:10]:
        print("  missing", s["seq"], sent[s["seq"]]["src"], sent[s["seq"]]["event"])
    verd = Counter(s.get("verdict") for s in ok)
    print("verdicts:", dict(verd))

    tasks = load(logs / f"{a.tag}-tasks.jsonl")
    last = {}
    for t in tasks:
        last[t["id"]] = t
    mine = {t["id"]: t for t in last.values()
            if t.get("offset") is not None and 0 <= t["offset"] - seq_base < len(sent) + 1000}
    by_seq = defaultdict(list)
    for t in mine.values():
        by_seq[t["offset"] - seq_base].append(t)
    print(f"\n== SAM tasks API (workflow gpos-spike-p01-pos, this run): {len(mine)} tasks, "
          f"{len(by_seq)} distinct seq of {len(sent)} sent")
    print("status:", dict(Counter(t["status"] for t in mine.values())))
    print("entrypoint ok:", dict(Counter(t["entrypoint_ok"] for t in mine.values())),
          "channel:", dict(Counter(t["channel"] for t in mine.values())),
          "user:", dict(Counter(t["user"] for t in mine.values())))
    print("tokens total:", sum(t.get("tokens") or 0 for t in mine.values()))
    multi = {k: v for k, v in by_seq.items() if len(v) > 1}
    print("seq with >1 task:", len(multi))
    sam = [t["sam_s"] for t in mine.values() if t.get("sam_s") is not None
           and t["status"] == "completed"]
    print("SAM start->end", stats(sam))
    notc = [t for t in mine.values() if t["status"] != "completed"]
    for t in notc[:10]:
        print("  not completed:", t["id"], t["status"], t["offset"] - seq_base)
    unseen = sorted(set(sent) - set(by_seq))
    print("seq not seen in tasks API:", len(unseen), unseen[:20])
    lag = []
    for seq, ts in by_seq.items():
        if seq in sent and seq in recv:
            lag.append(ts[0]["start"] - sent[seq]["t"])
    print("send -> SAM startTime (s)", stats(lag))

    samples = load(logs / f"{a.tag}-samples.jsonl")
    print(f"\n== lab samples: {len(samples)}")
    print("clock    | awe rs cpu mem | gwe rs cpu mem | str rs cpu mem | "
          "sam spoolB msgs qmsgs | wfq gwq | default spoolB msgs | tasks")
    for s in samples:
        p, tp, b = s.get("pods", {}), s.get("top", {}), s.get("broker", {})
        cells = [s["clock"]]
        for r in ("awe", "gwe", "str"):
            cells.append(f"{r} {p.get(r, {}).get('restarts')} {tp.get(r, {}).get('cpu_m')}m "
                         f"{tp.get(r, {}).get('mem_mi')}Mi")
        if "vpn_sam" in b:
            w = b.get("sam_queues_watch", {})
            wf = next((v["msgs"] for k, v in w.items() if "workflow_01a1c9ff" in k), None)
            gw = next((v["msgs"] for k, v in w.items() if "gateway/01a1c9ff" in k), None)
            cells.append(f"sam {b['vpn_sam']['msgSpoolUsage']} {b['vpn_sam']['msgSpoolMsgCount']} "
                         f"{b['sam_queue_msgs_total']}")
            cells.append(f"{wf} {gw}")
            cells.append(f"def {b['vpn_default']['msgSpoolUsage']} "
                         f"{b['vpn_default']['msgSpoolMsgCount']}")
        else:
            cells.append(f"broker {b}")
        tk = s.get("tasks", {})
        cells.append(f"page {tk.get('page')} mine {tk.get('mine_in_page')} new {tk.get('new')}"
                     if "error" not in tk else f"tasks ERROR {tk['error'][:60]}")
        print(" | ".join(cells))
    for r in ("awe", "gwe", "str"):
        rs = [s["pods"][r]["restarts"] for s in samples if r in s.get("pods", {})]
        st = {s["pods"][r]["started"] for s in samples if r in s.get("pods", {})}
        pods = {s["pods"][r]["pod"] for s in samples if r in s.get("pods", {})}
        cpu = [s["top"][r]["cpu_m"] for s in samples if r in s.get("top", {})]
        mem = [s["top"][r]["mem_mi"] for s in samples if r in s.get("top", {})]
        print(f"{r}: restarts {min(rs) if rs else '-'}..{max(rs) if rs else '-'}, pods {len(pods)},"
              f" startedAt {sorted(st)}, cpu {min(cpu) if cpu else '-'}..{max(cpu) if cpu else '-'}m"
              f" (median {statistics.median(cpu) if cpu else '-'}), mem "
              f"{min(mem) if mem else '-'}..{max(mem) if mem else '-'}Mi")
    sp = [s["broker"]["vpn_sam"]["msgSpoolUsage"] for s in samples if "vpn_sam" in s.get("broker", {})]
    sm = [s["broker"]["vpn_sam"]["msgSpoolMsgCount"] for s in samples
          if "vpn_sam" in s.get("broker", {})]
    qm = [s["broker"]["sam_queue_msgs_total"] for s in samples if "vpn_sam" in s.get("broker", {})]
    mx = [s["broker"]["vpn_sam"]["maxMsgSpoolUsage"] for s in samples
          if "vpn_sam" in s.get("broker", {})]
    if sp:
        print(f"VPN sam spool bytes {min(sp)}..{max(sp)} (first {sp[0]}, last {sp[-1]}), "
              f"msgs {min(sm)}..{max(sm)}, queue msgs {min(qm)}..{max(qm)}, "
              f"max spool {mx[0]} MB -> peak {max(sp) / (mx[0] * 1e6) * 100:.4f} %")
    dp = [s["broker"]["vpn_default"]["msgSpoolUsage"] for s in samples
          if "vpn_default" in s.get("broker", {})]
    if dp:
        print(f"VPN default spool bytes {min(dp)}..{max(dp)} (first {dp[0]}, last {dp[-1]})")
    nz = Counter()
    for s in samples:
        for k, v in s.get("broker", {}).get("sam_queues_nonzero", {}).items():
            if v["msgs"]:
                nz[k] = max(nz[k], v["msgs"])
    print("SAM queues ever non-empty (max msgs):", dict(nz))


if __name__ == "__main__":
    main()
