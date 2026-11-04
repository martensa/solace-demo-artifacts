"""Deterministic watch evaluation (no LLM, no I/O).

A watch is ``{watch_id, topic_filter, metric, op, threshold,
hold_seconds, ttl_minutes}`` with metric in

  spread_pct        spread of the quote in percent
  quote_age_s       seconds since the last quote of the product
                    (evaluated on the 1 s tick, catches stale feeds)
  drift_vs_ref_pct  |ref_price used by the issuer - live reference|
                    in percent of the live reference

The condition must hold continuously for ``hold_seconds``. Debounce:
at most ONE alert per watch and product, and at most ``max_alerts``
per watch (default 1) -- the trader asked to be told once ("melde
dich, wenn ..."), and one alert must start exactly one workflow run
even when several products of the issuer breach together. The alert
lists every product of the filter that is breaching at that moment.
:meth:`WatchEngine.rearm` clears the debounce (scenario reset).
"""

from __future__ import annotations

import operator
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from . import catalog, topics

METRICS = ("spread_pct", "quote_age_s", "drift_vs_ref_pct")
OPS: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le,
    "gt": operator.gt, "ge": operator.ge, "lt": operator.lt, "le": operator.le,
}
WATCH_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def new_watch_id() -> str:
    return "w-" + uuid.uuid4().hex[:6]


@dataclass
class ProductState:
    since_ms: int | None = None
    last_value: float | None = None
    alerted: bool = False


@dataclass
class Watch:
    watch_id: str
    topic_filter: str
    metric: str
    op: str
    threshold: float
    hold_seconds: float
    ttl_minutes: float
    created_ms: int
    max_alerts: int = 1
    description: str = ""
    alerts_sent: int = 0
    status: str = "active"  # active | stopped | expired
    products: dict[str, ProductState] = field(default_factory=dict)

    @property
    def expires_ms(self) -> int:
        return self.created_ms + int(self.ttl_minutes * 60_000)

    def condition(self, value: float) -> bool:
        return OPS[self.op](value, self.threshold)

    def public(self) -> dict[str, Any]:
        return {
            "watch_id": self.watch_id, "topic_filter": self.topic_filter,
            "metric": self.metric, "op": self.op, "threshold": self.threshold,
            "hold_seconds": self.hold_seconds, "ttl_minutes": self.ttl_minutes,
            "max_alerts": self.max_alerts, "description": self.description,
            "created_ms": self.created_ms, "expires_ms": self.expires_ms,
            "alerts_sent": self.alerts_sent, "status": self.status,
            "breaching": sorted(i for i, s in self.products.items() if s.since_ms),
        }


class WatchError(ValueError):
    pass


def validate(cmd: dict[str, Any]) -> dict[str, Any]:
    """Normalise a watch command; raises WatchError with a reason."""
    try:
        w = {
            "watch_id": str(cmd.get("watch_id") or new_watch_id()),
            "topic_filter": str(cmd["topic_filter"]).strip(),
            "metric": str(cmd["metric"]).strip(),
            "op": str(cmd.get("op", ">")).strip(),
            "threshold": float(cmd["threshold"]),
            "hold_seconds": float(cmd.get("hold_seconds", 0)),
            "ttl_minutes": float(cmd.get("ttl_minutes", 30)),
            "max_alerts": int(cmd.get("max_alerts", 1)),
            "description": str(cmd.get("description", ""))[:300],
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise WatchError(f"invalid watch command: {exc}") from exc
    if not WATCH_ID_RE.match(w["watch_id"]):
        raise WatchError("watch_id must match [A-Za-z0-9_-]{1,40}")
    if not w["topic_filter"].startswith(topics.PREFIX + "/quotes/"):
        raise WatchError("topic_filter must start with bsg/quotes/")
    if w["metric"] not in METRICS:
        raise WatchError(f"metric must be one of {METRICS}")
    if w["op"] not in OPS:
        raise WatchError(f"op must be one of {sorted(OPS)}")
    if not 0 <= w["hold_seconds"] <= 3600:
        raise WatchError("hold_seconds must be 0..3600")
    if not 0 < w["ttl_minutes"] <= 24 * 60:
        raise WatchError("ttl_minutes must be >0 and <= 1440")
    if not 1 <= w["max_alerts"] <= 100:
        raise WatchError("max_alerts must be 1..100")
    return w


def product_topic(p: catalog.Product) -> str:
    return topics.QUOTES.format(issuer=p.issuer, product_class=p.product_class, isin=p.isin)


class WatchEngine:
    def __init__(self) -> None:
        self.watches: dict[str, Watch] = {}

    # -- commands ---------------------------------------------------------
    def create(self, cmd: dict[str, Any], now_ms: int) -> Watch:
        w = Watch(created_ms=now_ms, **validate(cmd))
        self.watches[w.watch_id] = w
        return w

    def stop(self, watch_id: str) -> Watch | None:
        w = self.watches.get(watch_id)
        if w and w.status == "active":
            w.status = "stopped"
        return w

    def clear(self) -> list[str]:
        ids = list(self.watches)
        self.watches.clear()
        return ids

    def rearm(self) -> None:
        for w in self.watches.values():
            w.alerts_sent = 0
            w.products.clear()

    def active(self) -> list[Watch]:
        return [w for w in self.watches.values() if w.status == "active"]

    # -- evaluation -------------------------------------------------------
    def _observe(self, w: Watch, isin: str, value: float, ts_ms: int,
                 context: Callable[[Watch, str], dict[str, Any]]) -> dict[str, Any] | None:
        st = w.products.setdefault(isin, ProductState())
        st.last_value = value
        if not w.condition(value):
            st.since_ms = None
            return None
        if st.since_ms is None:
            st.since_ms = ts_ms
        held = (ts_ms - st.since_ms) / 1000
        if held < w.hold_seconds or st.alerted or w.alerts_sent >= w.max_alerts:
            return None
        st.alerted = True
        w.alerts_sent += 1
        return self._alert(w, isin, value, ts_ms, held, context)

    def _alert(self, w: Watch, isin: str, value: float, ts_ms: int, held: float,
               context: Callable[[Watch, str], dict[str, Any]]) -> dict[str, Any]:
        p = catalog.BY_ISIN.get(isin)
        affected = [
            {"isin": i, "value": s.last_value,
             "breaching_since_ms": s.since_ms}
            for i, s in sorted(w.products.items()) if s.since_ms is not None
        ]
        alert = {
            "alert_id": f"a-{uuid.uuid4().hex[:8]}",
            "watch_id": w.watch_id,
            "watch": {k: v for k, v in w.public().items() if k != "breaching"},
            "issuer": p.issuer if p else None,
            "isin": isin,
            "product_class": p.product_class if p else None,
            "underlying": p.underlying if p else None,
            "metric": w.metric, "op": w.op, "threshold": w.threshold,
            "observed_value": value,
            "held_seconds": round(held, 1),
            "condition_since_ms": ts_ms - int(held * 1000),
            "triggered_ms": ts_ms,
            "affected_products": affected,
            "peer_issuers": catalog.peers(p.issuer) if p else [],
        }
        alert.update(context(w, isin))
        return alert

    def on_quote(self, topic: str, q: dict[str, Any], live_ref: float | None,
                 context: Callable[[Watch, str], dict[str, Any]]) -> list[dict[str, Any]]:
        alerts = []
        ts = int(q.get("ts_ms") or 0)
        for w in self.active():
            if w.metric == "quote_age_s" or not topics.matches(w.topic_filter, topic):
                continue
            if w.metric == "spread_pct":
                value = float(q["spread_pct"])
            else:  # drift_vs_ref_pct
                if not live_ref:
                    continue
                value = round(abs(float(q["ref_price"]) - live_ref) / live_ref * 100, 4)
            a = self._observe(w, q["isin"], value, ts, context)
            if a:
                alerts.append(a)
        return alerts

    def tick(self, now_ms: int, last_quote_ms: dict[str, int], started_ms: int,
             context: Callable[[Watch, str], dict[str, Any]]) -> tuple[list[dict], list[Watch]]:
        """1 s tick: quote_age_s evaluation and TTL expiry."""
        alerts: list[dict[str, Any]] = []
        expired: list[Watch] = []
        for w in self.active():
            if now_ms >= w.expires_ms:
                w.status = "expired"
                expired.append(w)
                continue
            if w.metric != "quote_age_s":
                continue
            for p in catalog.PRODUCTS:
                if not topics.matches(w.topic_filter, product_topic(p)):
                    continue
                last = last_quote_ms.get(p.isin, started_ms)
                age = round((now_ms - last) / 1000, 1)
                a = self._observe(w, p.isin, age, now_ms, context)
                if a:
                    alerts.append(a)
        return alerts, expired
