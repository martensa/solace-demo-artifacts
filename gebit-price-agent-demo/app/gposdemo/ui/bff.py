"""BFF of ``gpos-ui``: REST API 10.1, SSE 10.2 and the static pages (port 8090).

:class:`Bff` holds the business methods (pure enough to test without HTTP);
:func:`build_app` wires them to FastAPI routes. The browser never gets broker or SAM
credentials; every call to another service goes through :mod:`.clients` or
:mod:`.facade`.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import anyio.to_thread
from fastapi import FastAPI, Request
from fastapi.responses import (FileResponse, JSONResponse, RedirectResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles

from ..common.bus import Bus
from ..common.clock import demo_now, from_ts
from ..common.config import Settings
from ..common.fmt import dt_label, eur
from ..common.money import from_money
from ..common.topics import parse_location
from . import texts
from .clients import EngineClient, LoyaltyClient, PosAdminClient, UpstreamError, WwsClient
from .facade import FacadeResult, PosFacade
from .feed import Hub, classify, sse_stream
from .refdata import RefData, category_rank

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
RESET_SCOPES = ("booth", "day")
FORWARD_RULES = ("r4", "p4")
FORWARD_ATTEMPTS = 3
FORWARD_BACKOFF_S = 1.0
HEALTH_CACHE_S = 2.0
PRICE_SOURCE_PREFIX = "PRICE_SOURCE_"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
REVALIDATE = {"Cache-Control": "no-cache"}
T = TypeVar("T")


@dataclass(frozen=True)
class Gateways:
    """The other services, as the BFF reaches them."""

    facade: PosFacade
    wws: WwsClient
    loyalty: LoyaltyClient
    engine: EngineClient
    pos_admin: PosAdminClient

    def close(self) -> None:
        for client in (self.facade, self.wws, self.loyalty, self.engine, self.pos_admin):
            client.close()


def with_state(obj: Any) -> Any:
    """Engine objects carry the DB column ``status``; events and scripts read ``state``.
    Adds ``state`` (same value) when only ``status`` is there."""
    if isinstance(obj, dict) and "state" not in obj and "status" in obj:
        return {**obj, "state": obj["status"]}
    return obj


def catalog_article(raw: dict[str, Any], tz: str) -> dict[str, Any]:
    """One ``/api/catalog`` article from a WWS ``Article`` (proto3 JSON, 4.3)."""
    price = raw.get("price") or {}
    valid_to = price.get("validTo")
    source = str(price.get("source", "")).removeprefix(PRICE_SOURCE_PREFIX)
    return {
        "article_number": str(raw.get("articleNumber", "")),
        "article_id": str(raw.get("articleId", "")),
        "gtin": str(raw.get("gtin", "")),
        "name": str(raw.get("name", "")),
        "category": str(raw.get("category", "")),
        "category_label": str(raw.get("categoryLabel", "")),
        "pack": str(raw.get("packLabel", "")),
        "price": eur(from_money(price["price"])) if "price" in price else "",
        "regular_price": eur(from_money(price["regularPrice"])) if "regularPrice" in price
        else "",
        "price_source": source if source and source != "UNSPECIFIED" else "REGULAR",
        "valid_to_label": dt_label(from_ts(valid_to, tz)) if valid_to else "",
    }


class Bff:
    """Business side of the BFF (``Service.service``)."""

    def __init__(self, settings: Settings, bus: Bus, hub: Hub, gateways: Gateways,
                 refdata: RefData):
        self.settings = settings
        self.bus = bus
        self.hub = hub
        self.gw = gateways
        self.refdata = refdata
        self.booth_store, self.booth_till = hub.booth
        self.till_stores = {till: parse_location(loc)[2]
                            for till, loc in gateways.facade.tills.items()}
        self.probe = parse_location(settings.probe_location)[2:]
        self._catalogs: dict[str, dict[str, Any]] = {}
        self._catalog_gen = 0
        self._catalog_lock = threading.Lock()
        self._health: tuple[float, dict[str, Any]] | None = None
        self._health_lock = threading.Lock()
        self._forwarder = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sam-error")

    # reference data -----------------------------------------------------------
    def store_of(self, till: str | None) -> str | None:
        """Store of a till id (default booth), ``None`` for an unknown till."""
        return self.till_stores.get(till or self.booth_till)

    def cards(self) -> list[dict[str, Any]]:
        return [card.public() for card in self.refdata.cards]

    def scenarios(self) -> list[dict[str, Any]]:
        return [dict(s) for s in self.refdata.scenarios]

    def catalog(self, store: str) -> dict[str, Any]:
        """Articles of ``store`` from WWS ``ListArticles`` (cached until the next
        ``price_change``; an answer that was in flight across a price change is served
        once but not cached)."""
        with self._catalog_lock:
            cached, generation = self._catalogs.get(store), self._catalog_gen
        if cached is not None:
            return cached
        articles = sorted((catalog_article(a, self.settings.tz)
                           for a in self.gw.wws.list_articles(store)),
                          key=lambda a: a["article_number"])
        labels = {a["category"]: a["category_label"] for a in articles}
        categories = [{"tag": tag, "label": labels[tag]}
                      for tag in sorted(labels, key=category_rank)]
        result = {"store": store, "articles": articles, "categories": categories}
        with self._catalog_lock:
            if generation == self._catalog_gen:
                self._catalogs[store] = result
        return result

    def invalidate_catalog(self) -> None:
        with self._catalog_lock:
            self._catalog_gen += 1
            self._catalogs.clear()

    # state ----------------------------------------------------------------------
    def refresh_bon(self, till: str) -> bool:
        """Read the open receipt of ``till`` authoritatively from POS admin."""
        try:
            self.hub.load_bon(till, self.gw.pos_admin.till(till))
        except UpstreamError as exc:
            log.warning("open receipt of till %s not refreshed: %s", till, exc)
            return False
        return True

    def state(self, till: str) -> dict[str, Any]:
        """``GET /api/state``: receipt, last 30 events, review, proposal, counters."""
        store = self.till_stores[till]
        snap = self.hub.snapshot(till)
        engine_ok = True
        try:
            engine = self.gw.engine.state(store, till)
        except UpstreamError as exc:
            log.warning("engine state unavailable: %s", exc)
            engine, engine_ok = {}, False
        proposal = with_state(engine.get("proposal")) or snap["proposal_event"]
        return {
            "store": store, "till": till,
            "booth": {"store": self.booth_store, "till": self.booth_till},
            "demo_date": self.settings.demo_date.isoformat(),
            "demo_now": demo_now(self.settings).isoformat(timespec="seconds"),
            "bon": snap["bon"],
            "events": snap["events"],
            "review": snap["review"] or with_state(engine.get("review")),
            "proposal": proposal,
            "proposal_event": snap["proposal_event"],
            "engine_counts": engine.get("counts"),
            "engine_ok": engine_ok,
            "counters": self.hub.counters.to_dict(),
            "sam_url": self.settings.sam_url,
        }

    def proposal(self, proposal_id: str) -> dict[str, Any] | None:
        """Read-only proxy of engine ``GET /api/proposals/{id}``."""
        return with_state(self.gw.engine.proposal(proposal_id))

    # POS facade ------------------------------------------------------------------
    def pos(self, method: str, body: Any, till: str | None) -> FacadeResult:
        result = self.gw.facade.call(method, body, till)
        if result.ok and method == "AssignLoyaltyMembership":
            req = result.request
            self.hub.note_card(
                self.gw.facade.till_or_none(till) or "",
                str(req.get("purchaseTransactionId") or req.get("purchase_transaction_id", "")),
                str(req.get("membershipIdentificationValue")
                    or req.get("membership_identification_value", "")))
        return result

    # reset -------------------------------------------------------------------------
    def _step(self, steps: dict[str, Any], name: str,
              call: Callable[[], dict[str, Any]]) -> bool:
        try:
            steps[name] = {"ok": True, **(call() or {})}
            return True
        except UpstreamError as exc:
            log.error("reset step %s failed: %s", name, exc)
            steps[name] = {"ok": False, "error": exc.message}
            return False

    def reset(self, scope: str) -> dict[str, Any]:
        """Reset chain 11.7 steps 1-5 in this order; a failed step is reported and the
        chain goes on. Ends with SSE ``reset``."""
        if scope not in RESET_SCOPES:
            raise ValueError(f"scope must be one of {RESET_SCOPES}, got {scope!r}")
        full, trace = scope == "day", f"reset-{scope}"
        steps: dict[str, Any] = {}
        oks = [
            self._step(steps, "engine", lambda: self.gw.engine.reset(scope, self.booth_store)),
            self._step(steps, "wws", lambda: self.gw.wws.reset(self.booth_store, full, trace)),
            self._step(steps, "pos", self.gw.pos_admin.reset),
            self._step(steps, "loyalty", lambda: self.gw.loyalty.reset(full, trace)),
        ]
        before = self.hub.counters.to_dict()
        dropped = self.hub.clear()
        self.hub.counters.reset()
        self.invalidate_catalog()
        steps["bff"] = {"ok": True, "events_cleared": dropped, "counters_before": before}
        self.hub.broadcast("reset", {"scope": scope})
        self.hub.broadcast("counters", self.hub.counters.to_dict())
        return {"ok": all(oks), "scope": scope, "store": self.booth_store, "steps": steps}

    # bus --------------------------------------------------------------------------
    def on_message(self, topic: str, payload: bytes, props: dict[str, str]) -> None:
        """Bus handler of all ``gpos-ui`` subscriptions."""
        if classify(topic) == "price_change":
            self.invalidate_catalog()  # before the pages hear of it and reload the catalog
        event = self.hub.handle(topic, payload, props)
        if event is None:
            return
        kind, data = event
        if kind == "sam_run" and not data["ok"] and data["rule"] in FORWARD_RULES:
            self._forwarder.submit(self.forward_sam_error, data["rule"], data["error"])

    def forward_sam_error(self, rule: str, error: str) -> bool:
        """``POST /api/sam-error`` for an R4/P4 ``errorOutput`` (``r4`` -> booth,
        ``p4`` -> probe till); idempotent at the engine, so it is retried."""
        store, till = (self.booth_store, self.booth_till) if rule == "r4" else self.probe
        for attempt in range(1, FORWARD_ATTEMPTS + 1):
            try:
                self.gw.engine.sam_error(rule, store, till, error)
                return True
            except UpstreamError as exc:
                log.warning("sam-error %s attempt %d failed: %s", rule, attempt, exc)
                if attempt < FORWARD_ATTEMPTS:
                    time.sleep(FORWARD_BACKOFF_S * attempt)
        log.error("sam-error %s not delivered to the engine", rule)
        return False

    # health -----------------------------------------------------------------------
    def _check_health(self) -> dict[str, Any]:
        probes = {"bus": lambda: bool(getattr(self.bus, "healthy", lambda: True)()),
                  "pos": self.gw.facade.healthy, "wws": self.gw.wws.healthy,
                  "engine": self.gw.engine.healthy}
        with ThreadPoolExecutor(max_workers=len(probes)) as pool:
            futures = {key: pool.submit(probe) for key, probe in probes.items()}
            results = {key: bool(f.result()) for key, f in futures.items()}
        return {"status": "ok" if all(results.values()) else "degraded", **results}

    def health(self) -> dict[str, Any]:
        """``{"status", "bus", "pos", "wws", "engine"}``; cached for 2 s, probes run in
        parallel with short timeouts."""
        with self._health_lock:
            if self._health and time.monotonic() - self._health[0] < HEALTH_CACHE_S:
                return self._health[1]
            result = self._check_health()
            self._health = (time.monotonic(), result)
            return result

    def close(self) -> None:
        self._forwarder.shutdown(wait=False, cancel_futures=True)
        self.gw.close()


# ------------------------------------------------------------------------ routes
class RevalidatedStatic(StaticFiles):
    """Static files the browser must revalidate (ETag) on every load: a kiosk never keeps
    a stale page after an image update."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _bad_request(message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "message": message}, status_code=400)


def _upstream(exc: UpstreamError) -> JSONResponse:
    return JSONResponse({"ok": False, "service": exc.service, "message": exc.message},
                        status_code=503)


async def _json_body(request: Request) -> Any:
    raw = await request.body()
    if not raw.strip():
        return {}
    try:
        return await request.json()
    except ValueError:
        return None


def build_app(bff: Bff, heartbeat_s: float = 15.0) -> FastAPI:
    """FastAPI app of the BFF (routes of 10.1, SSE 10.2, static pages 10.3/10.4)."""
    app = FastAPI(title="gpos-ui", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/monitor", status_code=302)

    @app.get("/kasse", include_in_schema=False)
    def kasse(till: str | None = None) -> Response:
        till_id = bff.gw.facade.till_or_none(till)
        if till_id is None:
            return _bad_request(f"Unbekannte Kasse: {till}")
        bff.refresh_bon(till_id)
        return FileResponse(STATIC_DIR / "kasse" / "index.html", headers=REVALIDATE)

    @app.get("/monitor", include_in_schema=False)
    def monitor() -> FileResponse:
        return FileResponse(STATIC_DIR / "monitor" / "index.html", headers=REVALIDATE)

    @app.get("/static/shared/texts.js", include_in_schema=False)
    def texts_js() -> Response:
        return Response(texts.texts_js(), media_type="application/javascript; charset=utf-8",
                        headers=REVALIDATE)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return bff.health()

    @app.get("/api/catalog")
    def catalog(till: str | None = None) -> Response:
        store = bff.store_of(till)
        if store is None:
            return _bad_request(f"Unbekannte Kasse: {till}")
        try:
            return JSONResponse(bff.catalog(store))
        except UpstreamError as exc:
            return _upstream(exc)

    @app.get("/api/cards")
    def cards() -> list[dict[str, Any]]:
        return bff.cards()

    @app.get("/api/scenarios")
    def scenarios() -> list[dict[str, Any]]:
        return bff.scenarios()

    @app.post("/api/pos/{method}")
    async def pos(method: str, request: Request, till: str | None = None) -> JSONResponse:
        body = await _json_body(request)
        result = await _in_thread(bff.pos, method, body, till)
        return JSONResponse(result.body, status_code=result.status)

    @app.get("/api/state")
    def state(till: str | None = None) -> Response:
        till_id = bff.gw.facade.till_or_none(till)
        if till_id is None:
            return _bad_request(f"Unbekannte Kasse: {till}")
        return JSONResponse(bff.state(till_id))

    @app.get("/api/proposals/{proposal_id}")
    def proposal(proposal_id: str) -> Response:
        if not _SAFE_ID.match(proposal_id):
            return _bad_request("ungültige Vorschlags-ID")
        try:
            found = bff.proposal(proposal_id)
        except UpstreamError as exc:
            return _upstream(exc)
        if found is None:
            return JSONResponse({"ok": False, "message": "Vorschlag unbekannt"},
                                status_code=404)
        return JSONResponse(found)

    @app.post("/api/demo/reset")
    async def reset(request: Request) -> JSONResponse:
        body = await _json_body(request)
        scope = body.get("scope", "booth") if isinstance(body, dict) else None
        if scope not in RESET_SCOPES:
            return _bad_request('scope muss "booth" oder "day" sein')
        result = await _in_thread(bff.reset, scope)
        return JSONResponse(result, status_code=200 if result["ok"] else 502)

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        sub = bff.hub.subscribe()
        stream = sse_stream(bff.hub, sub, lambda: bff.state(bff.booth_till), heartbeat_s)
        return StreamingResponse(stream, media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    app.mount("/static", RevalidatedStatic(directory=STATIC_DIR), name="static")
    return app


async def _in_thread(fn: Callable[..., T], *args: Any) -> T:
    """Run a blocking BFF method (gRPC/HTTP) off the event loop."""
    return await anyio.to_thread.run_sync(fn, *args)
