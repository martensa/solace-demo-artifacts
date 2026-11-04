"""demo-ui: presenter page (German, large type) with SSE event stream.

Left: live ticker per issuer + issuer status. Middle: the four steps
with one button each. Right: event stream (watch, alert, workflow
nodes, branch, desk note, action). Top: links to Grafana and the SAM
Activities view (Visualizer).

Step 1 entry modes (ENTRY_MODE):
  entrypoint  publish the trader's prompt on bsg/desk/requests/{id};
              the SAM event-mesh entrypoint rule hands it to the
              agent bsg-desk-assistant, whose answer comes back on
              bsg/desk/replies (successOutput). Default.
  direct      FALLBACK: publish the watch command on bsg/control/watch
              directly (no agent); the UI shows a banner saying so.

Workflow node progress comes from bsg/desk/progress/{watch_id}
(published by the deterministic tools) and, if SAM_STATUS_TOPICS is
set, from SAM's own A2A status topics on the same VPN (read only,
Gate 0 decides the filter).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .. import catalog, topics
from ..mqttio import Bus

log = logging.getLogger("demo-ui")
STATIC = Path(__file__).parent / "static"

ENTRY_MODE = os.environ.get("ENTRY_MODE", "entrypoint")
WATCHER_URL = os.environ.get("WATCHER_URL", "http://feed-watcher.bsg-demo.svc:8080")
GRAFANA_URL = os.environ.get(
    "GRAFANA_URL", "https://monitoring.solace.lab/d/sam-bsg-trading-desk"
    "?from=now-15m&to=now&var-agent=bsg-.*")
VISUALIZER_URL = os.environ.get("VISUALIZER_URL", "https://sam.solace.lab/")
SAM_STATUS_TOPICS = [t for t in os.environ.get("SAM_STATUS_TOPICS", "").split(",") if t]
DEFAULT_PROMPT = os.environ.get(
    "DEFAULT_PROMPT",
    "Beobachte die Quotes von Emittent Alpha in DAX-Turbos und melde dich, wenn der "
    "Spread länger als 10 Sekunden über 0,5 % liegt.")
DIRECT_WATCH = {"issuer": "alpha", "product_class": "dax-turbo", "metric": "spread_pct",
                "op": ">", "threshold": 0.5, "hold_seconds": 10, "ttl_minutes": 30}


def collect_text(obj: Any, out: list[str] | None = None) -> list[str]:
    """All strings under a "text" key (A2A task JSON -> answer text)."""
    out = [] if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "text" and isinstance(v, str):
                out.append(v)
            else:
                collect_text(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_text(v, out)
    return out


class Hub:
    """MQTT -> state + fan-out to SSE subscribers."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.events: deque[dict[str, Any]] = deque(maxlen=300)
        self.last_quote: dict[str, dict[str, Any]] = {}
        self.issuer_status = {i: "normal" for i in catalog.ISSUERS}
        self.scenario: dict[str, Any] = {"scenario": "normal"}
        self.queues: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        subs = ["bsg/#", *SAM_STATUS_TOPICS]
        self.bus = Bus("demo-ui", subs, self.on_message)

    def emit(self, kind: str, data: dict[str, Any]) -> None:
        ev = {"kind": kind, "ts": time.time(), "data": data}
        with self.lock:
            self.events.append(ev)
        self._fan(ev)

    def _fan(self, ev: dict[str, Any]) -> None:
        if not self.loop:
            return
        for q in list(self.queues):
            self.loop.call_soon_threadsafe(q.put_nowait, ev)

    def on_message(self, topic: str, payload: Any) -> None:
        if topic.startswith("bsg/quotes/"):
            if isinstance(payload, dict):
                with self.lock:
                    self.last_quote[payload["isin"]] = payload
            return
        if topic.startswith(("bsg/reference/",)):
            return
        if not topic.startswith("bsg/"):  # SAM status topics (read only)
            self.emit("sam", {"topic": topic, "payload": payload if isinstance(payload, dict)
                              else str(payload)[:2000]})
            return
        p = payload if isinstance(payload, dict) else {"raw": payload}
        if topic == topics.CONTROL_SCENARIO_STATE:
            changed = p.get("scenario") != self.scenario.get("scenario")
            self.scenario = p
            if changed:  # the 1 s countdown rides on the ticker snapshot
                self.emit("scenario", p)
        elif topic.startswith("bsg/watches/"):
            self.emit("watch", {"topic": topic, **p})
        elif topic.startswith("bsg/alerts/"):
            self.emit("alert", p)
        elif topic.startswith("bsg/desk/progress/"):
            self.emit("progress", p)
        elif topic.startswith("bsg/desk/notes/"):
            self.emit("note", p)
        elif topic == topics.DESK_ERRORS:
            self.emit("error", {"text": "\n".join(collect_text(p))[:2000], "raw": p})
        elif topic == topics.DESK_RESULTS:
            self.emit("result", {"text": "\n".join(collect_text(p))[:2000], "raw": p})
        elif topic == topics.DESK_REPLIES:
            self.emit("reply", {"text": "\n".join(collect_text(p))[:4000], "raw": p})
        elif topic.startswith("bsg/desk/requests/"):
            self.emit("request", p)
        elif topic.startswith("bsg/desk/issuer-status/"):
            self.issuer_status[p.get("issuer", "?")] = p.get("status", "normal")
            self.emit("issuer_status", p)
        elif topic == topics.DESK_ACTIONS:
            self.emit("action", p)
        elif topic == topics.NEWS:
            self.emit("news", p)
        elif topic == topics.CONTROL_WATCH:
            self.emit("watch_cmd", p)

    def ticker(self) -> dict[str, Any]:
        with self.lock:
            quotes = list(self.last_quote.values())
        return {"quotes": quotes, "issuer_status": self.issuer_status, "scenario": self.scenario}


hub = Hub()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    hub.loop = asyncio.get_running_loop()
    hub.bus.start(wait_s=0)
    yield
    hub.bus.stop()


app = FastAPI(title="BSG Trading Desk Demo UI", lifespan=lifespan)


class Step1(BaseModel):
    prompt: str


class ScenarioReq(BaseModel):
    scenario: str
    issuer: str | None = None
    duration_s: int = 30


class ActionReq(BaseModel):
    issuer: str
    action: str = "plausibility_check"
    note_ref: str | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
def config() -> dict[str, Any]:
    return {"entry_mode": ENTRY_MODE, "grafana_url": GRAFANA_URL,
            "visualizer_url": VISUALIZER_URL, "default_prompt": DEFAULT_PROMPT,
            "issuers": catalog.ISSUERS, "mqtt": hub.bus.connected.is_set()}


@app.post("/api/step1")
def step1(req: Step1) -> dict[str, Any]:
    if ENTRY_MODE == "direct":
        wid = "w-" + uuid.uuid4().hex[:6]
        cmd = {"cmd": "create", "watch_id": wid,
               "topic_filter": f"bsg/quotes/{DIRECT_WATCH['issuer']}/"
                               f"{DIRECT_WATCH['product_class']}/>",
               **{k: v for k, v in DIRECT_WATCH.items() if k not in ("issuer", "product_class")},
               "description": "FALLBACK: direkt von der UI publiziert (kein Agent)"}
        hub.bus.publish(topics.CONTROL_WATCH, cmd, qos=1)
        hub.emit("fallback", {"text": "Fallback aktiv: Watch-Kommando direkt publiziert, "
                                      "ohne Agent.", "command": cmd})
        return {"mode": "direct", "watch_id": wid}
    rid = "r-" + uuid.uuid4().hex[:8]
    msg = {"request_id": rid, "prompt": req.prompt.strip()[:2000], "ts": time.time()}
    hub.bus.publish(topics.DESK_REQUEST.format(request_id=rid), msg, qos=1)
    return {"mode": "entrypoint", "request_id": rid}


@app.post("/api/scenario")
def scenario(req: ScenarioReq) -> dict[str, Any]:
    name = req.scenario.replace("-", "_")
    if name not in ("wide_spread", "market_wide", "stale", "reset"):
        raise HTTPException(400, "unknown scenario")
    cmd = {"scenario": name, "duration_s": req.duration_s}
    if req.issuer:
        cmd["issuer"] = req.issuer
    hub.bus.publish(topics.CONTROL_SCENARIO, cmd, qos=1)
    return cmd


@app.post("/api/action")
def action(req: ActionReq) -> dict[str, Any]:
    msg = {"action_id": "act-" + uuid.uuid4().hex[:8], "action": req.action,
           "issuer": req.issuer, "by": "QLP-Desk (Demo-UI)", "note_ref": req.note_ref,
           "ts": time.time()}
    hub.bus.publish(topics.DESK_ACTIONS, msg, qos=1)
    return msg


@app.post("/api/reset")
def reset() -> dict[str, Any]:
    hub.bus.publish(topics.CONTROL_SCENARIO, {"scenario": "reset"}, qos=1)
    hub.bus.publish(topics.CONTROL_WATCH, {"cmd": "clear"}, qos=1)
    hub.bus.publish(topics.DESK_ACTIONS, {"action": "reset", "by": "demo-reset"}, qos=1)
    with hub.lock:
        hub.events.clear()
    hub._fan({"kind": "reset", "ts": time.time(), "data": {}})
    return {"status": "reset"}


@app.get("/api/chart")
def chart(issuers: str = "alpha,beta,gamma", product_class: str = "dax-turbo",
          minutes: float = 15) -> dict[str, Any]:
    """Spread series per issuer (5 s buckets, mean over products) for the
    UI chart -- deterministic, straight from the watcher."""
    try:
        rows = httpx.get(f"{WATCHER_URL}/recent", timeout=5, params={
            "issuer": issuers, "product_class": product_class, "minutes": minutes,
            "resample_s": 5}).json()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"watcher unreachable: {exc}") from exc
    series: dict[str, dict[int, list[float]]] = {}
    for r in rows:
        series.setdefault(r["issuer"], {}).setdefault(r["ts_ms"] // 5000 * 5000, []).append(
            r["spread_pct"])
    return {i: [[t, round(sum(v) / len(v), 4)] for t, v in sorted(b.items())]
            for i, b in series.items()}


@app.get("/api/events")
async def events() -> StreamingResponse:
    q: asyncio.Queue = asyncio.Queue(maxsize=2000)
    hub.queues.add(q)

    async def gen():
        try:
            with hub.lock:
                backlog = list(hub.events)
            yield f"event: snapshot\ndata: {json.dumps(backlog, ensure_ascii=False)}\n\n"
            last_tick = 0.0
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=0.5)
                    yield f"event: ev\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    pass
                if time.monotonic() - last_tick >= 0.5:
                    last_tick = time.monotonic()
                    yield (f"event: ticker\ndata: "
                           f"{json.dumps(hub.ticker(), ensure_ascii=False)}\n\n")
        finally:
            hub.queues.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "mqtt": hub.bus.connected.is_set()}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), log_level="warning")


if __name__ == "__main__":
    main()
