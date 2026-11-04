"""feed-publisher: synthetic but realistic quote feed over MQTT.

Topics (all prefix bsg/):
  quotes/{issuer}/{product_class}/{isin}  every 250-500 ms per product
  reference/{underlying}                  every second
  news                                    benign items every 90-150 s,
                                          plus scenario news
  control/scenario        (in)  {"scenario": wide_spread|market_wide|
                                 stale|reset, "issuer", "duration_s"}
  control/scenario/state  (out) the active scenario, on every change

Prices are a random walk around the reference level of the
underlying; spreads are normally 0.10-0.30 %. The simulation itself
(:class:`FeedSim`) is pure and clock-driven so it can be unit tested.
"""

from __future__ import annotations

import logging
import math
import os
import random
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import catalog, topics
from .mqttio import Bus

log = logging.getLogger("feed-publisher")

WIDE_SPREAD_PCT = float(os.environ.get("WIDE_SPREAD_PCT", "0.8"))
MARKET_WIDE_SPREAD_PCT = float(os.environ.get("MARKET_WIDE_SPREAD_PCT", "0.9"))
MARKET_JUMP_PCT = {"dax": -3.0, "nasdaq100": -2.5, "eurostoxx50": -2.2}


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Scenario:
    name: str = "normal"
    issuer: str | None = None
    started: float = 0.0
    until: float = 0.0

    def active(self, t: float) -> bool:
        return self.name != "normal" and t < self.until

    def as_dict(self, t: float) -> dict[str, Any]:
        return {
            "scenario": self.name if self.active(t) else "normal",
            "issuer": self.issuer,
            "started": iso(self.started) if self.started else None,
            "until": iso(self.until) if self.until else None,
            "remaining_s": max(0, round(self.until - t)) if self.active(t) else 0,
        }


@dataclass
class FeedSim:
    rng: random.Random = field(default_factory=random.Random)
    refs: dict[str, float] = field(default_factory=lambda: {
        k: v[1] for k, v in catalog.UNDERLYINGS.items()})
    scenario: Scenario = field(default_factory=Scenario)
    next_due: dict[str, float] = field(default_factory=dict)
    news_seq: int = 0

    # -- scenarios --------------------------------------------------------
    def apply_scenario(self, cmd: dict[str, Any], t: float) -> list[tuple[str, Any]]:
        """Apply a control command; returns extra messages to publish."""
        name = str(cmd.get("scenario", "")).replace("-", "_")
        duration = float(cmd.get("duration_s", cmd.get("duration", 30)))
        out: list[tuple[str, Any]] = []
        if name == "reset":
            self.scenario = Scenario()
            self.refs = {k: v[1] for k, v in catalog.UNDERLYINGS.items()}
        elif name in ("wide_spread", "stale"):
            issuer = str(cmd.get("issuer", "alpha")).lower()
            if issuer not in catalog.ISSUERS:
                raise ValueError(f"unknown issuer {issuer!r}")
            self.scenario = Scenario(name, issuer, t, t + duration)
        elif name == "market_wide":
            self.scenario = Scenario(name, None, t, t + duration)
            for und, pct in MARKET_JUMP_PCT.items():
                self.refs[und] *= 1 + pct / 100
            out.append((topics.NEWS, self.news(
                t,
                headline="Synthetisch: Überraschender Zinsentscheid -- "
                         "Indizes fallen deutlich",
                body="Demo-Nachricht. Die Notenbank (fiktiv) hebt den Leitzins "
                     "überraschend an. DAX, NASDAQ-100 und EURO STOXX 50 "
                     "geben 2-3 % nach, die Volatilität steigt marktweit.",
                scope="market", impact="high",
                underlyings=list(catalog.UNDERLYINGS), issuers=[])))
        else:
            raise ValueError(f"unknown scenario {name!r}")
        return out

    # -- reference / news -------------------------------------------------
    def step_reference(self, dt: float, t: float) -> None:
        vol = 0.0012 if self.scenario.active(t) and \
            self.scenario.name == "market_wide" else 0.0003
        for und in self.refs:
            self.refs[und] *= math.exp(self.rng.gauss(0, vol * math.sqrt(max(dt, 1e-3))))

    def news(self, t: float, headline: str, body: str, scope: str, impact: str,
             underlyings: list[str], issuers: list[str]) -> dict[str, Any]:
        self.news_seq += 1
        return {
            "id": f"N{self.news_seq:05d}", "ts": iso(t), "ts_ms": int(t * 1000),
            "headline": headline, "body": body, "scope": scope, "impact": impact,
            "underlyings": underlyings, "issuers": issuers, "synthetic": True,
        }

    def background_news(self, t: float) -> dict[str, Any]:
        items = [
            ("Demo: Handelszeiten am Brückentag unverändert", "low"),
            ("Demo: Neue Turbo-Serie auf den DAX-Index angekündigt", "low"),
            ("Demo: Wochenausblick -- ruhiger Handel erwartet", "low"),
            ("Demo: Konjunkturdaten im Rahmen der Erwartungen", "low"),
        ]
        headline, impact = self.rng.choice(items)
        return self.news(t, headline, "Synthetische Routinenachricht ohne "
                         "Marktrelevanz.", "market", impact, [], [])

    # -- quotes -----------------------------------------------------------
    def spread_for(self, p: catalog.Product, t: float) -> float:
        sc = self.scenario
        if sc.active(t) and sc.name == "wide_spread" and sc.issuer == p.issuer:
            return round(WIDE_SPREAD_PCT * (1 + self.rng.uniform(-0.05, 0.05)), 3)
        if sc.active(t) and sc.name == "market_wide":
            return round(MARKET_WIDE_SPREAD_PCT * (1 + self.rng.uniform(-0.1, 0.1)), 3)
        s = p.base_spread_pct * (1 + self.rng.uniform(-0.2, 0.2))
        return round(min(max(s, 0.10), 0.30), 3)

    def quote(self, p: catalog.Product, t: float) -> dict[str, Any] | None:
        sc = self.scenario
        if sc.active(t) and sc.name == "stale" and sc.issuer == p.issuer:
            return None
        ref = self.refs[p.underlying]
        mid = catalog.fair_price(p, ref) * (1 + self.rng.gauss(0, 0.0004))
        spread = self.spread_for(p, t)
        half = mid * spread / 200
        wide = spread > 0.5
        size = self.rng.randrange(2, 8 if wide else 21) * 1000
        return {
            "issuer": p.issuer, "isin": p.isin, "product_class": p.product_class,
            "underlying": p.underlying,
            "bid": round(mid - half, 4), "ask": round(mid + half, 4),
            "spread_pct": spread, "size": size, "ref_price": round(ref, 2),
            "ts": iso(t), "ts_ms": int(t * 1000),
        }

    def due_quotes(self, t: float) -> list[tuple[str, dict[str, Any]]]:
        out = []
        for p in catalog.PRODUCTS:
            if t < self.next_due.get(p.isin, 0):
                continue
            self.next_due[p.isin] = t + self.rng.uniform(0.25, 0.5)
            q = self.quote(p, t)
            if q is not None:
                out.append((topics.QUOTES.format(issuer=p.issuer,
                                                 product_class=p.product_class,
                                                 isin=p.isin), q))
        return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sim = FeedSim()
    state = {"dirty": True}

    def on_msg(topic: str, payload: Any) -> None:
        if topic != topics.CONTROL_SCENARIO or not isinstance(payload, dict):
            return
        try:
            extra = sim.apply_scenario(payload, time.time())
        except ValueError as exc:
            log.warning("scenario rejected: %s", exc)
            return
        log.info("scenario: %s", payload)
        for t, m in extra:
            bus.publish(t, m)
        state["dirty"] = True

    bus = Bus("feed-publisher", [topics.CONTROL_SCENARIO], on_msg).start()
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))

    last_ref = time.time()
    next_news = time.time() + sim.rng.uniform(90, 150)
    was_active = False
    last_state = 0.0
    while not stop["flag"]:
        t = time.time()
        for topic, q in sim.due_quotes(t):
            bus.publish(topic, q)
        if t - last_ref >= 1.0:
            sim.step_reference(t - last_ref, t)
            last_ref = t
            for und, ref in sim.refs.items():
                bus.publish(topics.REFERENCE.format(underlying=und), {
                    "underlying": und, "name": catalog.UNDERLYINGS[und][0],
                    "price": round(ref, 2), "ts": iso(t), "ts_ms": int(t * 1000)})
        if t >= next_news:
            bus.publish(topics.NEWS, sim.background_news(t))
            next_news = t + sim.rng.uniform(90, 150)
        active = sim.scenario.active(t)
        if state["dirty"] or active != was_active or (active and t - last_state >= 1.0):
            bus.publish(topics.CONTROL_SCENARIO_STATE, sim.scenario.as_dict(t))
            state["dirty"] = False
            last_state = t
        was_active = active
        time.sleep(0.05)
    bus.stop()


if __name__ == "__main__":
    main()
