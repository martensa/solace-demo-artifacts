"""feed-watcher: deterministic watcher, 15-minute store and HTTP API.

MQTT in : bsg/quotes/#, bsg/reference/#, bsg/news,
          bsg/control/watch    {cmd: create|stop|clear|rearm, ...watch}
          bsg/control/scenario (reset -> rearm all watches)
          bsg/desk/actions     {action: plausibility_check|release|reset,
                                issuer, by, note_ref}
MQTT out: bsg/alerts/{watch_id}             one alert per watch (debounce)
          bsg/watches/{watch_id}/{event}    created|stopped|expired|
                                            rejected|cleared
          bsg/desk/issuer-status/{issuer}   on every status change

HTTP (port 8080):
  GET /health
  GET /recent?issuer=&isin=&product_class=&minutes=15&format=csv|json
             &resample_s=0
  GET /reference?underlying=&minutes=15&format=csv|json&resample_s=0
  GET /news?minutes=15
  GET /watches        GET /alerts        GET /issuer-status
  GET /stats?issuer=&product_class=&minutes=15   compact spread and
       reference statistics (deterministic, used by enrich_alert)

Everything lives 15 minutes (RETENTION_MINUTES) in memory and in a
SQLite file on an emptyDir (DB_PATH, default /data/feed.db).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import sqlite3
import statistics
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse

from . import catalog, topics
from .mqttio import Bus, now_ms
from .watch_engine import WatchEngine, WatchError

log = logging.getLogger("feed-watcher")

RETENTION_MIN = float(os.environ.get("RETENTION_MINUTES", "15"))
DB_PATH = os.environ.get("DB_PATH", "/data/feed.db")
PUBLIC_URL = os.environ.get("WATCHER_URL", "http://feed-watcher.bsg-demo.svc:8080")

QUOTE_COLS = ("ts_ms", "ts", "issuer", "isin", "product_class", "underlying",
              "bid", "ask", "spread_pct", "size", "ref_price")
REF_COLS = ("ts_ms", "ts", "underlying", "price")


def iso_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds")


class Store:
    """SQLite store (15-minute window) plus in-memory last values."""

    def __init__(self, path: str) -> None:
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript("""
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS quotes(ts_ms INTEGER, ts TEXT, issuer TEXT,
                isin TEXT, product_class TEXT, underlying TEXT, bid REAL, ask REAL,
                spread_pct REAL, size INTEGER, ref_price REAL);
              CREATE INDEX IF NOT EXISTS q_ts ON quotes(ts_ms);
              CREATE INDEX IF NOT EXISTS q_issuer ON quotes(issuer, ts_ms);
              CREATE TABLE IF NOT EXISTS reference(ts_ms INTEGER, ts TEXT,
                underlying TEXT, price REAL);
              CREATE INDEX IF NOT EXISTS r_ts ON reference(underlying, ts_ms);
              CREATE TABLE IF NOT EXISTS news(ts_ms INTEGER, id TEXT, body TEXT);
              CREATE TABLE IF NOT EXISTS events(ts_ms INTEGER, kind TEXT, body TEXT);
            """)
        self.pending_q: list[tuple] = []
        self.pending_r: list[tuple] = []
        self.last_quote: dict[str, dict[str, Any]] = {}
        self.last_quote_ms: dict[str, int] = {}
        self.last_ref: dict[str, float] = {}
        self.news_mem: deque[dict[str, Any]] = deque(maxlen=500)
        self.alerts: deque[dict[str, Any]] = deque(maxlen=200)

    def add_quote(self, q: dict[str, Any]) -> None:
        with self.lock:
            self.pending_q.append(tuple(q.get(c) for c in QUOTE_COLS))
            self.last_quote[q["isin"]] = q
            self.last_quote_ms[q["isin"]] = int(q["ts_ms"])

    def add_ref(self, r: dict[str, Any]) -> None:
        with self.lock:
            self.pending_r.append((r["ts_ms"], r["ts"], r["underlying"], r["price"]))
            self.last_ref[r["underlying"]] = float(r["price"])

    def add_news(self, n: dict[str, Any]) -> None:
        with self.lock:
            self.news_mem.append(n)
            self.db.execute("INSERT INTO news VALUES(?,?,?)",
                            (int(n.get("ts_ms") or now_ms()), n.get("id"), json.dumps(n)))

    def add_event(self, kind: str, body: dict[str, Any]) -> None:
        with self.lock:
            self.db.execute("INSERT INTO events VALUES(?,?,?)", (now_ms(), kind, json.dumps(body)))

    def flush(self) -> None:
        with self.lock:
            if self.pending_q:
                self.db.executemany(f"INSERT INTO quotes VALUES({','.join('?' * len(QUOTE_COLS))})",
                                    self.pending_q)
                self.pending_q = []
            if self.pending_r:
                self.db.executemany("INSERT INTO reference VALUES(?,?,?,?)", self.pending_r)
                self.pending_r = []
            self.db.commit()

    def prune(self) -> None:
        cutoff = now_ms() - int(RETENTION_MIN * 60_000)
        with self.lock:
            for table in ("quotes", "reference", "news", "events"):
                self.db.execute(f"DELETE FROM {table} WHERE ts_ms < ?", (cutoff,))
            self.db.commit()

    def query(self, sql: str, args: tuple) -> list[dict[str, Any]]:
        with self.lock:
            self.flush()
            cur = self.db.execute(sql, args)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    # -- read API ---------------------------------------------------------
    def recent(self, issuer: str | None, isin: str | None, product_class: str | None,
               minutes: float, resample_s: float) -> list[dict[str, Any]]:
        where, args = ["ts_ms >= ?"], [now_ms() - int(minutes * 60_000)]
        for col, val in (("issuer", issuer), ("isin", isin), ("product_class", product_class)):
            if val and val != "*":
                vals = [v.strip() for v in val.split(",") if v.strip()]
                where.append(f"{col} IN ({','.join('?' * len(vals))})")
                args.extend(vals)
        rows = self.query(f"SELECT {','.join(QUOTE_COLS)} FROM quotes WHERE {' AND '.join(where)} "
                          "ORDER BY ts_ms", tuple(args))
        return resample(rows, "isin", resample_s)

    def reference(self, underlying: str | None, minutes: float,
                  resample_s: float) -> list[dict[str, Any]]:
        where, args = ["ts_ms >= ?"], [now_ms() - int(minutes * 60_000)]
        if underlying:
            vals = [v.strip() for v in underlying.split(",") if v.strip()]
            where.append(f"underlying IN ({','.join('?' * len(vals))})")
            args.extend(vals)
        rows = self.query(f"SELECT {','.join(REF_COLS)} FROM reference WHERE {' AND '.join(where)} "
                          "ORDER BY ts_ms", tuple(args))
        return resample(rows, "underlying", resample_s)

    def news(self, minutes: float) -> list[dict[str, Any]]:
        cutoff = now_ms() - int(minutes * 60_000)
        with self.lock:
            return [n for n in self.news_mem if int(n.get("ts_ms") or 0) >= cutoff]


def resample(rows: list[dict[str, Any]], key: str, every_s: float) -> list[dict[str, Any]]:
    """Keep the last row per key and time bucket (every_s <= 0: all)."""
    if every_s <= 0:
        return rows
    bucket = int(every_s * 1000)
    last: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        last[(r[key], r["ts_ms"] // bucket)] = r
    return sorted(last.values(), key=lambda r: r["ts_ms"])


def to_csv(rows: list[dict[str, Any]], cols: tuple[str, ...]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(cols), extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def spread_stats(rows: list[dict[str, Any]], now: int, recent_s: float = 60,
                 since_ms: int | None = None) -> dict[str, Any]:
    """Per issuer: mean/median/max spread over the window and the last
    ``recent_s`` seconds (deterministic numbers for the enrich step).

    With ``since_ms`` -- the moment an alert's condition started -- every
    issuer also gets ``mean_spread_pct_since_alert`` over exactly that
    period. The 60 s mean dilutes a 10 s anomaly with 50 s of normal
    quotes, and the 15 minute window still carries the previous run of
    the same scenario, so neither number isolates the anomaly. This one
    does, which is what makes "issuer specific" provable: the alerting
    issuer is far above its own window while the peers are not.
    """
    out: dict[str, Any] = {}
    cut = now - int(recent_s * 1000)
    for issuer in sorted({r["issuer"] for r in rows}):
        mine = [r for r in rows if r["issuer"] == issuer]
        all_s = [r["spread_pct"] for r in mine]
        rec_s = [r["spread_pct"] for r in mine if r["ts_ms"] >= cut]
        out[issuer] = {
            "quotes": len(all_s),
            "mean_spread_pct_window": round(statistics.fmean(all_s), 4) if all_s else None,
            "median_spread_pct_window": round(statistics.median(all_s), 4) if all_s else None,
            "max_spread_pct_window": max(all_s) if all_s else None,
            f"mean_spread_pct_last_{int(recent_s)}s": round(statistics.fmean(rec_s), 4) if rec_s else None,
            f"quotes_last_{int(recent_s)}s": len(rec_s),
        }
        if since_ms:
            alert_s = [r["spread_pct"] for r in mine if r["ts_ms"] >= since_ms]
            out[issuer]["mean_spread_pct_since_alert"] = (
                round(statistics.fmean(alert_s), 4) if alert_s else None)
            out[issuer]["quotes_since_alert"] = len(alert_s)
    return out


def ref_stats(rows: list[dict[str, Any]], now: int, recent_s: float = 60) -> dict[str, Any]:
    out: dict[str, Any] = {}
    cut = now - int(recent_s * 1000)
    for und in sorted({r["underlying"] for r in rows}):
        series = [r for r in rows if r["underlying"] == und]
        first, last = series[0]["price"], series[-1]["price"]
        before = [r["price"] for r in series if r["ts_ms"] < cut]
        base = before[-1] if before else first
        prices = [r["price"] for r in series]
        out[und] = {
            "first": first, "last": last,
            "change_pct_window": round((last - first) / first * 100, 3),
            f"change_pct_last_{int(recent_s)}s": round((last - base) / base * 100, 3),
            "range_pct_window": round((max(prices) - min(prices)) / first * 100, 3),
        }
    return out


class Watcher:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.engine = WatchEngine()
        self.lock = threading.RLock()
        self.started_ms = now_ms()
        self.issuer_status: dict[str, dict[str, Any]] = {
            i: {"issuer": i, "status": "normal", "since_ms": self.started_ms}
            for i in catalog.ISSUERS}
        self.bus = Bus("feed-watcher", [
            "bsg/quotes/#", "bsg/reference/#", topics.NEWS, topics.CONTROL_WATCH,
            topics.CONTROL_SCENARIO, topics.DESK_ACTIONS], self.on_message)

    # -- context for alerts -----------------------------------------------
    def _context(self, w, isin: str) -> dict[str, Any]:
        p = catalog.BY_ISIN.get(isin)
        return {
            "triggered_at": iso_ms(now_ms()),
            "issuer_status": self.issuer_status.get(p.issuer if p else "", {}).get("status"),
            "live_reference": self.store.last_ref.get(p.underlying) if p else None,
            "watcher_api": PUBLIC_URL,
        }

    def _emit_alerts(self, alerts: list[dict[str, Any]]) -> None:
        for a in alerts:
            self.store.alerts.append(a)
            self.store.add_event("alert", a)
            self.bus.publish(topics.ALERT.format(watch_id=a["watch_id"]), a, qos=1)
            log.info("ALERT %s watch=%s isin=%s value=%s", a["alert_id"], a["watch_id"],
                     a["isin"], a["observed_value"])

    def _watch_event(self, watch_id: str, event: str, body: dict[str, Any]) -> None:
        self.bus.publish(topics.WATCH_EVENT.format(watch_id=watch_id, event=event),
                         {"event": event, "ts": iso_ms(now_ms()), **body})

    # -- MQTT dispatch ----------------------------------------------------
    def on_message(self, topic: str, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        with self.lock:
            if topic.startswith("bsg/quotes/"):
                self.store.add_quote(payload)
                live = self.store.last_ref.get(payload.get("underlying", ""))
                self._emit_alerts(self.engine.on_quote(topic, payload, live, self._context))
            elif topic.startswith("bsg/reference/"):
                self.store.add_ref(payload)
            elif topic == topics.NEWS:
                self.store.add_news(payload)
            elif topic == topics.CONTROL_WATCH:
                self._on_watch_cmd(payload)
            elif topic == topics.CONTROL_SCENARIO:
                if str(payload.get("scenario")) == "reset":
                    self.engine.rearm()
                    log.info("scenario reset -> watches re-armed")
            elif topic == topics.DESK_ACTIONS:
                self._on_action(payload)

    def _on_watch_cmd(self, cmd: dict[str, Any]) -> None:
        kind = str(cmd.get("cmd", "create"))
        if kind == "create":
            try:
                w = self.engine.create(cmd, now_ms())
            except WatchError as exc:
                self._watch_event(str(cmd.get("watch_id") or "invalid"), "rejected",
                                  {"reason": str(exc), "request": cmd})
                return
            self.store.add_event("watch_created", w.public())
            self._watch_event(w.watch_id, "created", w.public())
            log.info("watch created %s", w.public())
        elif kind == "stop":
            w = self.engine.stop(str(cmd.get("watch_id")))
            if w:
                self._watch_event(w.watch_id, "stopped", w.public())
        elif kind == "clear":
            for wid in self.engine.clear():
                self._watch_event(wid, "cleared", {"watch_id": wid})
        elif kind == "rearm":
            self.engine.rearm()

    def _on_action(self, a: dict[str, Any]) -> None:
        action = str(a.get("action", ""))
        if action == "reset":
            targets, status = list(catalog.ISSUERS), "normal"
        elif action in ("plausibility_check", "release"):
            issuer = str(a.get("issuer", "")).lower()
            if issuer not in catalog.ISSUERS:
                return
            targets = [issuer]
            status = "in_review" if action == "plausibility_check" else "normal"
        else:
            return
        for issuer in targets:
            st = {"issuer": issuer, "status": status, "since_ms": now_ms(),
                  "action": action, "by": a.get("by"), "action_id": a.get("action_id"),
                  "note_ref": a.get("note_ref")}
            self.issuer_status[issuer] = st
            self.bus.publish(topics.DESK_ISSUER_STATUS.format(issuer=issuer), st)
        self.store.add_event("action", a)

    # -- background -------------------------------------------------------
    def run_background(self) -> None:
        last_prune = time.time()
        while True:
            time.sleep(1.0)
            with self.lock:
                self.store.flush()
                alerts, expired = self.engine.tick(now_ms(), self.store.last_quote_ms,
                                                   self.started_ms, self._context)
                self._emit_alerts(alerts)
                for w in expired:
                    self._watch_event(w.watch_id, "expired", w.public())
            if time.time() - last_prune > 30:
                self.store.prune()
                last_prune = time.time()


def build_app(watcher: Watcher) -> FastAPI:
    app = FastAPI(title="bsg feed-watcher", version="0.1.0")
    store = watcher.store

    def rows_response(rows, cols, fmt):
        if fmt == "csv":
            return PlainTextResponse(to_csv(rows, cols), media_type="text/csv")
        return JSONResponse(rows)

    @app.get("/health")
    def health():
        return {"status": "ok", "mqtt_connected": watcher.bus.connected.is_set(),
                "products_seen": len(store.last_quote), "watches": len(watcher.engine.watches)}

    @app.get("/recent")
    def recent(issuer: str | None = None, isin: str | None = None,
               product_class: str | None = None,
               minutes: float = Query(15, gt=0, le=RETENTION_MIN),
               format: str = Query("json", pattern="^(json|csv)$"),
               resample_s: float = Query(0, ge=0, le=60)):
        return rows_response(store.recent(issuer, isin, product_class, minutes, resample_s),
                             QUOTE_COLS, format)

    @app.get("/reference")
    def reference(underlying: str | None = None,
                  minutes: float = Query(15, gt=0, le=RETENTION_MIN),
                  format: str = Query("json", pattern="^(json|csv)$"),
                  resample_s: float = Query(0, ge=0, le=60)):
        return rows_response(store.reference(underlying, minutes, resample_s), REF_COLS, format)

    @app.get("/news")
    def news(minutes: float = Query(15, gt=0, le=RETENTION_MIN)):
        return store.news(minutes)

    @app.get("/watches")
    def watches(status: str | None = None):
        with watcher.lock:
            return [w.public() for w in watcher.engine.watches.values()
                    if status is None or w.status == status]

    @app.get("/watches/{watch_id}")
    def watch(watch_id: str):
        with watcher.lock:
            w = watcher.engine.watches.get(watch_id)
            if not w:
                raise HTTPException(404, f"unknown watch {watch_id}")
            return w.public()

    @app.get("/alerts")
    def alerts(watch_id: str | None = None):
        return [a for a in store.alerts if watch_id is None or a["watch_id"] == watch_id]

    @app.get("/issuer-status")
    def issuer_status():
        return list(watcher.issuer_status.values())

    @app.get("/quotes/last")
    def last_quotes():
        with store.lock:
            return list(store.last_quote.values())

    @app.get("/stats")
    def stats(issuer: str | None = None, product_class: str | None = None,
              minutes: float = Query(15, gt=0, le=RETENTION_MIN),
              since_ms: int | None = Query(None, gt=0,
                                           description="Start of an alert's condition; "
                                                       "adds mean_spread_pct_since_alert")):
        now = now_ms()
        rows = store.recent(issuer, None, product_class, minutes, 0)
        unds = sorted({catalog.CLASS_UNDERLYING[c] for c in
                       (product_class.split(",") if product_class else catalog.PRODUCT_CLASSES)
                       if c in catalog.CLASS_UNDERLYING})
        refs = store.reference(",".join(unds), minutes, 0)
        return {"window_minutes": minutes, "as_of": iso_ms(now),
                "spread": spread_stats(rows, now, since_ms=since_ms),
                "reference": ref_stats(refs, now),
                "news_count": len(store.news(minutes)),
                "high_impact_news": [n for n in store.news(minutes) if n.get("impact") == "high"]}

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    watcher = Watcher(Store(DB_PATH))
    watcher.bus.start()
    threading.Thread(target=watcher.run_background, daemon=True, name="tick").start()
    uvicorn.run(build_app(watcher), host="0.0.0.0", port=int(os.environ.get("PORT", "8080")),
                log_level="warning")


if __name__ == "__main__":
    main()
