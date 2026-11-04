"""Unit tests: topic matching, watch engine, feed simulation, store."""

import random
import time

import pytest

from bsgdemo import catalog, topics
from bsgdemo.publisher import FeedSim
from bsgdemo.watch_engine import WatchEngine, WatchError, validate
from bsgdemo.watcher import Store, ref_stats, resample, spread_stats, to_csv, QUOTE_COLS

NOCTX = lambda w, isin: {}  # noqa: E731


# --- topics -------------------------------------------------------------------
@pytest.mark.parametrize("flt,topic,ok", [
    ("bsg/quotes/alpha/dax-turbo/>", "bsg/quotes/alpha/dax-turbo/DE000DEMO0001", True),
    ("bsg/quotes/alpha/dax-turbo/>", "bsg/quotes/beta/dax-turbo/DE000DEMO0006", False),
    ("bsg/quotes/alpha/*/>", "bsg/quotes/alpha/discount-cert/DE000DEMO0005", True),
    ("bsg/quotes/alpha/dax*/>", "bsg/quotes/alpha/dax-turbo/X", True),
    ("bsg/quotes/alpha/dax*/>", "bsg/quotes/alpha/nasdaq-knockout/X", False),
    ("bsg/quotes/alpha/dax-turbo/>", "bsg/quotes/alpha/dax-turbo", False),
    ("bsg/news", "bsg/news", True),
])
def test_matches(flt, topic, ok):
    assert topics.matches(flt, topic) is ok


def test_to_mqtt():
    assert topics.to_mqtt("bsg/quotes/alpha/*/>") == "bsg/quotes/alpha/+/#"


# --- catalog ------------------------------------------------------------------
def test_catalog_shape():
    assert len(catalog.PRODUCTS) == 15
    assert len({p.isin for p in catalog.PRODUCTS}) == 15
    assert all(p.isin.startswith("DE000DEMO") for p in catalog.PRODUCTS)
    for i in catalog.ISSUERS:
        mine = [p for p in catalog.PRODUCTS if p.issuer == i]
        assert 4 <= len(mine) <= 6
        assert len({p.product_class for p in mine}) == 3


# --- watch engine -------------------------------------------------------------
def watch_cmd(**kw):
    base = {"watch_id": "w-test", "topic_filter": "bsg/quotes/alpha/dax-turbo/>",
            "metric": "spread_pct", "op": ">", "threshold": 0.5, "hold_seconds": 10,
            "ttl_minutes": 30}
    base.update(kw)
    return base


def q(isin, spread, ts_ms, issuer="alpha", pclass="dax-turbo", ref=19000.0):
    return {"issuer": issuer, "isin": isin, "product_class": pclass, "underlying": "dax",
            "bid": 1, "ask": 1.01, "spread_pct": spread, "size": 1000, "ref_price": ref,
            "ts_ms": ts_ms}


def topic_of(isin):
    p = catalog.BY_ISIN[isin]
    return topics.QUOTES.format(issuer=p.issuer, product_class=p.product_class, isin=isin)


ALPHA_DAX = [p.isin for p in catalog.PRODUCTS if p.issuer == "alpha" and p.product_class == "dax-turbo"]


def test_validate_rejects_bad_metric():
    with pytest.raises(WatchError):
        validate(watch_cmd(metric="price"))
    with pytest.raises(WatchError):
        validate(watch_cmd(topic_filter="other/>"))


def test_hold_then_exactly_one_alert_for_whole_watch():
    eng = WatchEngine()
    eng.create(watch_cmd(), 0)
    alerts = []
    for step in range(0, 30_000, 300):  # 30 s of wide spreads, both alpha dax products
        for isin in ALPHA_DAX:
            alerts += eng.on_quote(topic_of(isin), q(isin, 0.8, step), 19000, NOCTX)
    assert len(alerts) == 1
    a = alerts[0]
    assert a["held_seconds"] >= 10
    assert a["triggered_ms"] >= 10_000
    assert a["watch_id"] == "w-test" and a["issuer"] == "alpha"
    assert {x["isin"] for x in a["affected_products"]} == set(ALPHA_DAX)
    assert a["peer_issuers"] == ["beta", "gamma"]


def test_no_alert_when_condition_breaks_before_hold():
    eng = WatchEngine()
    eng.create(watch_cmd(), 0)
    isin = ALPHA_DAX[0]
    alerts = []
    for step in range(0, 9_000, 300):
        alerts += eng.on_quote(topic_of(isin), q(isin, 0.8, step), 19000, NOCTX)
    alerts += eng.on_quote(topic_of(isin), q(isin, 0.2, 9_300), 19000, NOCTX)  # resets hold
    for step in range(9_600, 18_000, 300):
        alerts += eng.on_quote(topic_of(isin), q(isin, 0.8, step), 19000, NOCTX)
    assert alerts == []


def test_other_issuers_do_not_match():
    eng = WatchEngine()
    eng.create(watch_cmd(), 0)
    beta = [p.isin for p in catalog.PRODUCTS if p.issuer == "beta" and p.product_class == "dax-turbo"][0]
    alerts = []
    for step in range(0, 30_000, 300):
        alerts += eng.on_quote(topic_of(beta), q(beta, 0.9, step, issuer="beta"), 19000, NOCTX)
    assert alerts == []


def test_rearm_allows_second_alert_and_max_alerts_per_product():
    eng = WatchEngine()
    eng.create(watch_cmd(max_alerts=5), 0)
    isin = ALPHA_DAX[0]
    alerts = []
    for step in range(0, 30_000, 300):
        alerts += eng.on_quote(topic_of(isin), q(isin, 0.8, step), 19000, NOCTX)
    assert len(alerts) == 1  # debounce per watch and product
    eng.rearm()
    for step in range(40_000, 60_000, 300):
        alerts += eng.on_quote(topic_of(isin), q(isin, 0.8, step), 19000, NOCTX)
    assert len(alerts) == 2


def test_quote_age_and_ttl():
    eng = WatchEngine()
    eng.create(watch_cmd(watch_id="w-stale", topic_filter="bsg/quotes/beta/>",
                         metric="quote_age_s", threshold=5, hold_seconds=2, ttl_minutes=1), 0)
    last = {p.isin: 0 for p in catalog.PRODUCTS}
    alerts = []
    for now in range(0, 10_000, 1000):
        a, _ = eng.tick(now, last, 0, NOCTX)
        alerts += a
    assert len(alerts) == 1 and alerts[0]["issuer"] == "beta"
    _, expired = eng.tick(61_000, last, 0, NOCTX)
    assert [w.watch_id for w in expired] == ["w-stale"]


def test_drift_metric():
    eng = WatchEngine()
    eng.create(watch_cmd(metric="drift_vs_ref_pct", threshold=1.0, hold_seconds=0), 0)
    isin = ALPHA_DAX[0]
    assert eng.on_quote(topic_of(isin), q(isin, 0.2, 0, ref=19000), 19000, NOCTX) == []
    a = eng.on_quote(topic_of(isin), q(isin, 0.2, 100, ref=19000), 18500, NOCTX)
    assert len(a) == 1 and a[0]["observed_value"] > 2.5


# --- feed simulation ----------------------------------------------------------
def run_sim(sim, t0, seconds):
    out = []
    t = t0
    while t < t0 + seconds:
        out += sim.due_quotes(t)
        t += 0.05
    return out


def test_normal_spreads_and_rate():
    sim = FeedSim(rng=random.Random(1))
    quotes = run_sim(sim, 1000.0, 10)
    spreads = [qq["spread_pct"] for _, qq in quotes]
    assert min(spreads) >= 0.10 and max(spreads) <= 0.30
    per_product = len(quotes) / 15 / 10
    assert 2.0 <= per_product <= 4.0  # every 250-500 ms
    for topic, qq in quotes:
        assert topic == f"bsg/quotes/{qq['issuer']}/{qq['product_class']}/{qq['isin']}"
        assert qq["bid"] < qq["ask"]
        assert set(qq) >= {"issuer", "isin", "product_class", "underlying", "bid", "ask",
                           "spread_pct", "size", "ref_price", "ts"}


def test_wide_spread_scenario_only_alpha():
    sim = FeedSim(rng=random.Random(2))
    sim.apply_scenario({"scenario": "wide_spread", "issuer": "alpha", "duration_s": 30}, 1000.0)
    quotes = run_sim(sim, 1000.0, 5)
    alpha = [qq["spread_pct"] for _, qq in quotes if qq["issuer"] == "alpha"]
    other = [qq["spread_pct"] for _, qq in quotes if qq["issuer"] != "alpha"]
    assert min(alpha) > 0.7 and max(other) <= 0.30
    after = run_sim(sim, 1031.0, 2)
    assert max(qq["spread_pct"] for _, qq in after) <= 0.30


def test_market_wide_jumps_reference_and_emits_news():
    sim = FeedSim(rng=random.Random(3))
    dax0 = sim.refs["dax"]
    extra = sim.apply_scenario({"scenario": "market-wide", "duration_s": 30}, 1000.0)
    assert sim.refs["dax"] < dax0 * 0.98
    assert extra and extra[0][0] == "bsg/news" and extra[0][1]["impact"] == "high"
    quotes = run_sim(sim, 1000.0, 3)
    assert min(qq["spread_pct"] for _, qq in quotes) > 0.7
    sim.apply_scenario({"scenario": "reset"}, 1005.0)
    assert sim.refs["dax"] == dax0


def test_stale_scenario_silences_issuer():
    sim = FeedSim(rng=random.Random(4))
    sim.apply_scenario({"scenario": "stale", "issuer": "beta", "duration_s": 20}, 1000.0)
    quotes = run_sim(sim, 1000.0, 3)
    assert not [qq for _, qq in quotes if qq["issuer"] == "beta"]


# --- store --------------------------------------------------------------------
def test_store_recent_resample_csv_and_stats():
    st = Store(":memory:")
    now = int(time.time() * 1000)
    for k in range(100):
        for isin, issuer, sp in (("DE000DEMO0001", "alpha", 0.8), ("DE000DEMO0006", "beta", 0.2)):
            st.add_quote({**q(isin, sp, now - 50_000 + k * 500, issuer=issuer), "ts": "x"})
        st.add_ref({"ts_ms": now - 50_000 + k * 500, "ts": "x", "underlying": "dax",
                    "price": 19000 - k})
    rows = st.recent("alpha,beta", None, "dax-turbo", 15, 0)
    assert len(rows) == 200
    assert len(st.recent("alpha", None, "*", 15, 0)) == 100
    rs = resample(rows, "isin", 5)
    assert 18 <= len(rs) <= 24
    csv_text = to_csv(rs, QUOTE_COLS)
    assert csv_text.splitlines()[0] == ",".join(QUOTE_COLS)
    stats = spread_stats(rows, now)
    assert stats["alpha"]["mean_spread_pct_window"] == pytest.approx(0.8)
    assert stats["beta"]["mean_spread_pct_window"] == pytest.approx(0.2)
    refs = ref_stats(st.reference("dax", 15, 0), now)
    assert refs["dax"]["change_pct_window"] < 0
