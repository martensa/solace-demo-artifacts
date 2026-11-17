"""Price actions over real gRPC on the seeded scratch DB (4.3, 4.5, 5.4, 7, 11.7).

Booth actions start at business date 00:00, are idempotent per ``proposal_id``, write
one outbox row per change (aggregate ``<article>:<store>``) and never touch
``price_history``, ``stock`` or ``sales_daily``.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import grpc
import pytest
from google.protobuf import any_pb2, json_format
from google.protobuf.descriptor_pool import DescriptorPool

from gposdemo.common import grpcutil
from gposdemo.common.bus import MemoryBus
from gposdemo.common.clock import from_ts, offset_ts_json
from gposdemo.common.config import Settings
from gposdemo.common.db import Db
from gposdemo.common.descriptors import WWS_SVC, Types
from gposdemo.common.jsonutil import parse_strict
from gposdemo.common.money import from_bdecimal, from_money
from gposdemo.wws import WwsApp, create
from gposdemo.wws.service import WwsService, command_from_request

from .bodies import D0, TZ, VALID_TO, change

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_wws")]

ACTION_ID = re.compile(r"^PA-270216-\d{4}$")
APPLIED = "showcase/wws/v1/price/PriceChangeApplied/DE/999"
ENDED = "showcase/wws/v1/price/PriceChangeEnded/DE/999"


def price(client: grpcutil.Client, article: str = "100001", store: str = "199",
          at: datetime | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"articleNumber": article, "storeId": store}
    if at is not None:
        body["at"] = offset_ts_json(at)
    return client.call_json("GetEffectivePrice", body)


def outbox(admin: Db) -> list[dict[str, Any]]:
    return admin.fetch("select aggregate_id, aggregate_offset, event_type, topic, payload_text, "
                       "delivery_class, user_props, app_message_id, published_at "
                       "from wws.event_outbox order by id")


def rejected(client: grpcutil.Client, method: str, body: dict[str, Any]) -> tuple[str, Any]:
    with pytest.raises(grpc.RpcError) as caught:
        client.call(method, body)
    return grpcutil.error_code(caught.value), caught.value.code()


def unpack(payload: str, pool: DescriptorPool, name: str) -> Any:
    types = Types(pool)
    wrapped = parse_strict(payload, any_pb2.Any(), pool)
    msg = types.new(f"de.showcase.wws.v1.event.{name}")
    assert wrapped.Unpack(msg)
    return msg


def snapshot(admin: Db) -> list[Any]:
    """Seed tables a booth sale or a price action must never change."""
    return [admin.fetch(q) for q in (
        "select * from wws.stock order by article_number, store_id",
        "select * from wws.sales_daily order by article_number, store_id, day",
        "select * from wws.price_history order by article_number, store_id, valid_from",
        "select * from wws.sales_plan order by article_number, store_id")]


# ------------------------------------------------------------------- RequestPriceChange
def test_request_starts_a_booth_action(client: grpcutil.Client, admin_db: Db, wws_app: WwsApp,
                                       wws_bus: MemoryBus, showcase_pool: DescriptorPool
                                       ) -> None:
    got = client.call_json("RequestPriceChange", change("GP-270216-0901"))
    assert ACTION_ID.match(got["actionId"]) and got["created"] is True
    action_id = got["actionId"]
    [row] = admin_db.fetch("select * from wws.price_action where action_id = %s", (action_id,))
    assert (row["kind"], row["article_number"], row["store_id"]) == ("BOOTH", "100001", "199")
    assert (row["regular_price"], row["action_price"], row["pct_shown"], row["ref30"]) == (
        Decimal("9.99"), Decimal("7.99"), 20, Decimal("9.99"))
    assert (row["valid_from"], row["valid_to"]) == (D0, VALID_TO)
    assert (row["proposal_id"], row["reason_code"], row["originator"], row["approver"]) == (
        "GP-270216-0901", "REASON_CODE_SLOW_SELLER", "gpos-engine", "role:marktleitung")
    assert row["ended_at"] is None

    [event] = outbox(admin_db)
    assert (event["aggregate_id"], event["aggregate_offset"], event["app_message_id"]) == (
        "100001:199", 1, "100001:199:1")
    assert event["event_type"] == "de.showcase.wws.v1.event.PriceChangeApplied"
    assert (event["topic"], event["delivery_class"]) == (f"{APPLIED}/199/100001", "business")
    assert event["user_props"] == {"eventType": "de.showcase.wws.v1.event.PriceChangeApplied",
                                   "source": "gpos-wws", "apiVersion": "wws-v1",
                                   "traceId": "GP-270216-0901"}
    msg = unpack(event["payload_text"], showcase_pool, "PriceChangeApplied")
    assert (msg.action_id, msg.article_name, msg.metadata.offset) == (
        action_id, "GEBIT Ente (Quietscheente gelb)", 1)
    assert from_ts(msg.valid_from) == D0 and msg.valid_from.offset == 60

    assert wws_app.relay.drain() == 1
    [sent] = wws_bus.messages(f"{APPLIED}/>")
    assert (sent.text(), sent.app_message_id, sent.persistent) == (
        event["payload_text"], "100001:199:1", False)
    assert outbox(admin_db)[0]["published_at"] is not None

    effective = price(client)
    assert (effective["source"], effective["actionId"], effective["pctShown"]) == (
        "PRICE_SOURCE_BOOTH_ACTION", action_id, 20)
    assert (from_money(effective["price"]), from_money(effective["regularPrice"]),
            from_money(effective["ref30"])) == (Decimal("7.99"), Decimal("9.99"), Decimal("9.99"))
    assert from_ts(effective["validTo"]) == VALID_TO
    article = client.call_json("GetArticle", {"storeId": "199", "articleNumber": "100001"})
    assert from_bdecimal(article["marginPercent"]) == Decimal("22.6")  # 6.8
    assert price(client, store="101")["source"] == "PRICE_SOURCE_REGULAR"  # booth store
    [audit] = admin_db.fetch("select actor, action, ref from wws.audit")
    assert audit == {"actor": "role:marktleitung", "action": "price_action.created",
                     "ref": action_id}


def test_action_without_valid_from_starts_at_business_date_midnight(
        client: grpcutil.Client, admin_db: Db) -> None:
    action_id = client.call_json("RequestPriceChange",
                                 change("GP-270216-0902", valid_from=None))["actionId"]
    [row] = admin_db.fetch("select valid_from from wws.price_action where action_id = %s",
                           (action_id,))
    assert row["valid_from"] == D0
    assert price(client, at=D0)["source"] == "PRICE_SOURCE_BOOTH_ACTION"
    assert price(client, at=D0 - timedelta(minutes=1))["source"] == "PRICE_SOURCE_REGULAR"
    assert price(client, at=VALID_TO)["source"] == "PRICE_SOURCE_REGULAR"


def test_request_is_idempotent_per_proposal(client: grpcutil.Client, admin_db: Db) -> None:
    first = client.call_json("RequestPriceChange", change("GP-270216-0903"))
    again = client.call_json("RequestPriceChange", change("GP-270216-0903"))
    assert again == {"actionId": first["actionId"]}  # created=false is the proto3 default
    assert len(outbox(admin_db)) == 1
    assert admin_db.fetch("select count(*) as n from wws.price_action where kind = 'BOOTH'"
                          ) == [{"n": 1}]
    code, status = rejected(client, "RequestPriceChange",
                            change("GP-270216-0903", article="100008", regular="7.99",
                                   new="5.49", pct=31, ref30="7.99"))
    assert (code, status) == ("WWS-002", grpc.StatusCode.INVALID_ARGUMENT)


def test_concurrent_repeats_create_one_action(wws_app: WwsApp, admin_db: Db,
                                              showcase_pool: DescriptorPool) -> None:
    clients = [grpcutil.Client(showcase_pool, WWS_SVC, f"localhost:{wws_app.grpc_port}")
               for _ in range(4)]
    results: list[dict[str, Any]] = []
    barrier = threading.Barrier(len(clients))

    def call(c: grpcutil.Client) -> None:
        barrier.wait()
        results.append(c.call_json("RequestPriceChange", change("GP-270216-0904")))

    threads = [threading.Thread(target=call, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    for c in clients:
        c.close()
    assert len(results) == 4 and len({r["actionId"] for r in results}) == 1
    assert sorted(r.get("created", False) for r in results) == [False, False, False, True]
    assert len(outbox(admin_db)) == 1


@pytest.mark.parametrize(("body", "expected"), [
    (change("GP-E-1", article="999999"), ("WWS-001", grpc.StatusCode.NOT_FOUND)),
    (change("GP-E-2", store="555"), ("WWS-001", grpc.StatusCode.NOT_FOUND)),
    (change("GP-E-3", new="9.99", pct=0), ("WWS-010", grpc.StatusCode.INVALID_ARGUMENT)),
    (change("GP-E-4", new="10.49", pct=0), ("WWS-010", grpc.StatusCode.INVALID_ARGUMENT)),
    (change("GP-E-5", article="100009", regular="3.49", new="2.79", pct=6, ref30="2.99"),
     ("WWS-011", grpc.StatusCode.FAILED_PRECONDITION)),
    (change("GP-E-6", article="100028", regular="24.00", new="19.99", pct=16, ref30="24.00"),
     ("WWS-012", grpc.StatusCode.FAILED_PRECONDITION)),
    (change("GP-E-7", regular="8.99"), ("WWS-020", grpc.StatusCode.ABORTED)),
    (change("GP-E-8", valid_from=D0 - timedelta(days=8), valid_to=D0 - timedelta(hours=4)),
     ("WWS-002", grpc.StatusCode.INVALID_ARGUMENT)),
    (change("GP-E-9", reason="REASON_CODE_UNSPECIFIED"),
     ("WWS-002", grpc.StatusCode.INVALID_ARGUMENT)),
])
def test_request_error_codes(client: grpcutil.Client, admin_db: Db, body: dict[str, Any],
                             expected: tuple[str, grpc.StatusCode]) -> None:
    assert rejected(client, "RequestPriceChange", body) == expected
    assert outbox(admin_db) == []
    assert admin_db.fetch("select count(*) as n from wws.price_action where kind = 'BOOTH'"
                          ) == [{"n": 0}]


@pytest.mark.parametrize(("field", "amount"), [
    ("newPrice", {"scale": 3, "intVal": "9985"}),        # 9,985 < 9,99 but no cent value
    ("ref30", {"scale": 2, "intVal": "99999999999"}),    # overflows numeric(8,2)
])
def test_prices_the_table_cannot_store_are_wws_002(client: grpcutil.Client, admin_db: Db,
                                                   field: str, amount: dict[str, Any]) -> None:
    """Formerly gRPC UNKNOWN with the raw Postgres error in the status text."""
    body = change("GP-270216-0920")
    body[field] = {"currency": "EUR", "amount": amount}
    with pytest.raises(grpc.RpcError) as caught:
        client.call("RequestPriceChange", body)
    err = caught.value
    assert (grpcutil.error_code(err), err.code()) == ("WWS-002",
                                                      grpc.StatusCode.INVALID_ARGUMENT)
    assert err.details().startswith("WWS-002: ") and "constraint" not in err.details()
    assert outbox(admin_db) == []
    assert admin_db.fetch("select count(*) as n from wws.price_action where kind = 'BOOTH'"
                          ) == [{"n": 0}]


def test_second_proposal_for_a_running_action_is_wws_011(client: grpcutil.Client) -> None:
    first = client.call_json("RequestPriceChange", change("GP-270216-0905"))["actionId"]
    with pytest.raises(grpc.RpcError) as caught:
        client.call("RequestPriceChange", change("GP-270216-0906", new="6.99", pct=30))
    assert grpcutil.error_code(caught.value) == "WWS-011"
    assert caught.value.details() == (f"WWS-011: Für Artikel 100001 läuft die Aktion {first} "
                                      f"bis Di 23.02. 20:00")


def test_due_actions_expire_before_a_request(client: grpcutil.Client, admin_db: Db,
                                             wws_app: WwsApp, wws_bus: MemoryBus) -> None:
    ended_at = D0 - timedelta(hours=4)  # 2027-02-15 20:00, before demo_now()
    admin_db.fetch(
        "insert into wws.price_action (action_id, article_number, store_id, kind, "
        "regular_price, action_price, pct_shown, ref30, valid_from, valid_to, proposal_id, "
        "reason_code, originator, approver) values ('PA-270208-0001', '100004', '199', "
        "'BOOTH', 1.99, 1.79, 10, 1.99, %s, %s, 'GP-270208-0001', 'REASON_CODE_SLOW_SELLER', "
        "'gpos-engine', 'role:marktleitung')", (D0 - timedelta(days=8), ended_at))
    assert price(client, article="100004")["source"] == "PRICE_SOURCE_REGULAR"  # not effective
    client.call_json("RequestPriceChange", change("GP-270216-0907"))
    [row] = admin_db.fetch("select ended_at, end_reason from wws.price_action "
                           "where action_id = 'PA-270208-0001'")
    assert row == {"ended_at": ended_at, "end_reason": "expired"}
    assert [e["aggregate_id"] for e in outbox(admin_db)] == ["100004:199", "100001:199"]
    wws_app.relay.drain()
    [ended] = wws_bus.messages(f"{ENDED}/199/100004")
    body = ended.json()
    assert (body["reason"], body["actionId"]) == ("expired", "PA-270208-0001")
    assert from_ts(body["endedAt"]) == ended_at


# ---------------------------------------------------------- EndPriceChange and reset
def test_end_price_change(client: grpcutil.Client, admin_db: Db, wws_app: WwsApp,
                          wws_bus: MemoryBus) -> None:
    action_id = client.call_json("RequestPriceChange", change("GP-270216-0908"))["actionId"]
    end = {"header": {"traceId": "end-1"}, "actionId": action_id, "reason": "manual"}
    assert client.call_json("EndPriceChange", end) == {}
    assert price(client)["source"] == "PRICE_SOURCE_REGULAR"
    assert client.call_json("EndPriceChange", end) == {}  # idempotent, no second event
    events = outbox(admin_db)
    assert [(e["aggregate_id"], e["aggregate_offset"], e["event_type"].rsplit(".", 1)[1])
            for e in events] == [("100001:199", 1, "PriceChangeApplied"),
                                 ("100001:199", 2, "PriceChangeEnded")]
    wws_app.relay.drain()
    [ended] = wws_bus.messages(f"{ENDED}/199/100001")
    body = ended.json()
    assert (body["reason"], body["metadata"]["offset"], body["metadata"]["traceId"]) == (
        "manual", "2", "end-1")
    assert from_ts(body["endedAt"]).date() == D0.date()  # business time
    assert rejected(client, "EndPriceChange", {"actionId": "PA-270216-9999"}) == (
        "WWS-003", grpc.StatusCode.NOT_FOUND)


def test_reset_ends_booth_actions_of_one_store(client: grpcutil.Client, admin_db: Db,
                                               wws_app: WwsApp, wws_bus: MemoryBus) -> None:
    ente = client.call_json("RequestPriceChange", change("GP-270216-0909"))["actionId"]
    pralinen = client.call_json("RequestPriceChange", change(
        "GP-270216-0910", article="100008", regular="7.99", new="5.49", pct=31,
        ref30="7.99", reason="REASON_CODE_SEASON_END"))["actionId"]
    booth = client.call_json("RequestPriceChange", change("GP-270216-0911", store="101"))
    wws_app.relay.drain()
    wws_bus.clear()

    assert client.call_json("ResetDemoState", {"header": {"traceId": "reset-booth"},
                                               "storeId": "199"}) == {}
    rows = {r["action_id"]: r for r in admin_db.fetch(
        "select action_id, ended_at, end_reason from wws.price_action where kind = 'BOOTH'")}
    assert {rows[ente]["end_reason"], rows[pralinen]["end_reason"]} == {"reset"}
    assert rows[booth["actionId"]]["ended_at"] is None  # store 101 untouched
    assert price(client)["source"] == "PRICE_SOURCE_REGULAR"
    assert price(client, store="101")["source"] == "PRICE_SOURCE_BOOTH_ACTION"
    assert price(client, article="100009")["source"] == "PRICE_SOURCE_CENTRAL_ACTION"
    wws_app.relay.drain()
    ended = wws_bus.messages(f"{ENDED}/199/>")
    assert sorted(m.json()["actionId"] for m in ended) == sorted([ente, pralinen])
    assert {m.props["traceId"] for m in ended} == {"reset-booth"}
    assert {m.json()["reason"] for m in ended} == {"reset"}
    assert wws_bus.messages(f"{APPLIED}/>") == []
    assert rejected(client, "ResetDemoState", {"storeId": ""}) == (
        "WWS-002", grpc.StatusCode.INVALID_ARGUMENT)


def _in_background(call: Callable[[], Any]) -> tuple[threading.Thread, list[Any]]:
    """Run ``call`` in a thread; its result (or exception) lands in the returned list."""
    out: list[Any] = []

    def run() -> None:
        try:
            out.append(call())
        except Exception as exc:  # noqa: BLE001 - handed to the test for its assertion
            out.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, out


def test_reset_waits_for_a_request_in_flight(client: grpcutil.Client, admin_db: Db) -> None:
    """A request holds the store lock shared until it commits; the reset (exclusive)
    waits and then ends the action that request created, instead of missing it and
    leaving a booth price active after the reset (11.7 step 2)."""
    with admin_db.tx() as conn:
        conn.execute("select pg_advisory_xact_lock_shared(hashtext('wws:store:199'))")
        conn.execute(
            "insert into wws.price_action (action_id, article_number, store_id, kind, "
            "regular_price, action_price, pct_shown, ref30, valid_from, valid_to, "
            "proposal_id, reason_code, originator, approver) values ('PA-270216-0950', "
            "'100004', '199', 'BOOTH', 1.99, 1.79, 10, 1.99, %s, %s, 'GP-270216-0950', "
            "'REASON_CODE_SLOW_SELLER', 'gpos-engine', 'role:marktleitung')", (D0, VALID_TO))
        reset, done = _in_background(lambda: client.call_json(
            "ResetDemoState", {"header": {"traceId": "reset-booth"}, "storeId": "199"}))
        reset.join(0.5)
        assert reset.is_alive() and done == []  # blocked behind the request in flight
    reset.join(10)
    assert done == [{}]
    [row] = admin_db.fetch("select end_reason from wws.price_action "
                           "where action_id = 'PA-270216-0950'")
    assert row == {"end_reason": "reset"}
    assert price(client, article="100004")["source"] == "PRICE_SOURCE_REGULAR"


def test_request_waits_for_a_reset_in_flight(client: grpcutil.Client, admin_db: Db) -> None:
    """The other direction: while a reset of the store runs, a request does not insert."""
    with admin_db.tx() as conn:
        conn.execute("select pg_advisory_xact_lock(hashtext('wws:store:199'))")
        request, done = _in_background(lambda: client.call_json(
            "RequestPriceChange", change("GP-270216-0951")))
        request.join(0.5)
        assert request.is_alive() and done == []
        assert admin_db.fetch("select count(*) as n from wws.price_action "
                              "where kind = 'BOOTH'") == [{"n": 0}]
    request.join(10)
    assert done[0]["created"] is True
    assert price(client)["source"] == "PRICE_SOURCE_BOOTH_ACTION"


def test_full_reset_restores_the_central_action(client: grpcutil.Client, admin_db: Db,
                                                wws_app: WwsApp, wws_bus: MemoryBus) -> None:
    client.call_json("EndPriceChange", {"actionId": "PA-SEED-100009-199", "reason": "test"})
    assert from_money(price(client, article="100009")["price"]) == Decimal("3.49")
    client.call_json("ResetDemoState", {"header": {"traceId": "reset-day"}, "storeId": "199",
                                        "full": True})
    restored = price(client, article="100009")
    assert (restored["actionId"], from_money(restored["price"])) == ("PA-SEED-100009-199",
                                                                     Decimal("2.99"))
    wws_app.relay.drain()
    [applied] = wws_bus.messages(f"{APPLIED}/199/100009")
    body = applied.json()
    assert (body["kind"], body["originator"], body["articleName"]) == (
        "PRICE_ACTION_KIND_CENTRAL", {"identityId": "zentrale"}, "Glühwein rot")
    wws_bus.clear()
    client.call_json("ResetDemoState", {"storeId": "199", "full": True})  # nothing to do
    wws_app.relay.drain()
    assert wws_bus.messages(">") == []
    assert price(client, article="100009", store="101")["actionId"] == "PA-SEED-100009"


def test_price_actions_never_change_stock_sales_or_history(
        client: grpcutil.Client, admin_db: Db, wws_app: WwsApp) -> None:
    before = snapshot(admin_db)
    action_id = client.call_json("RequestPriceChange", change("GP-270216-0912"))["actionId"]
    for method in ("GetSalesPerformance", "GetSeasonInfo", "GetEffectivePrice"):
        client.call_json(method, {"articleNumber": "100001", "storeId": "199"})
    client.call_json("ListArticles", {"storeId": "199"})
    wws_app.service.get_article("100001")
    wws_app.service.get_sales_performance("100001")
    client.call_json("EndPriceChange", {"actionId": action_id})
    client.call_json("ResetDemoState", {"storeId": "199", "full": True})
    assert snapshot(admin_db) == before
    sales = client.call_json("GetSalesPerformance", {"articleNumber": "100001",
                                                     "storeId": "199"})
    assert (sales["sold7d"], sales["stockOnHand"]) == (9, 96)  # seed state all day (5.4)


def test_started_app_publishes_through_its_relay(
        make_settings: Callable[..., Settings], scratch_db: Any, admin_db: Db,
        showcase_pool: DescriptorPool) -> None:
    bus = MemoryBus()
    db = scratch_db.db("wws", max_size=3)
    app = create(make_settings("wws", GPOS_DSN=scratch_db.dsn("wws"), GRPC_PORT="0"), bus, db)
    app.start()
    try:
        client = grpcutil.Client(showcase_pool, WWS_SVC, f"localhost:{app.grpc_port}")
        client.call_json("RequestPriceChange", change("GP-270216-0913"))
        [sent] = bus.wait_for(f"{APPLIED}/199/100001", timeout=5.0)
        assert sent.app_message_id == "100001:199:1"
        client.close()
    finally:
        app.stop()
        db.close()
        bus.close()
    assert admin_db.fetch("select count(*) as n from wws.event_outbox "
                          "where published_at is null") == [{"n": 0}]


def test_actions_expire_on_a_later_business_date(client: grpcutil.Client, admin_db: Db,
                                                  wws_settings: Settings, wws_db: Db,
                                                  showcase_pool: DescriptorPool) -> None:
    """Business date 2027-02-24: the booth action (to 23.02. 20:00) and the central action
    (to 21.02. 20:00) are no longer effective and end as ``expired`` with the next request;
    a full reset does not bring back an expired central action."""
    booth = client.call_json("RequestPriceChange", change("GP-270216-0914"))["actionId"]
    types = Types(showcase_pool)
    later = WwsService(wws_settings, wws_db, types,
                       clock=lambda: datetime(2027, 2, 24, 10, 0, tzinfo=TZ))
    effective = json_format.MessageToDict(later.effective_price("100001", "199"))
    assert effective["source"] == "PRICE_SOURCE_REGULAR"
    request = json_format.ParseDict(
        change("GP-270224-0001", article="100004", regular="1.99", new="1.79", pct=10,
               ref30="1.99", valid_from=datetime(2027, 2, 24, tzinfo=TZ),
               valid_to=datetime(2027, 3, 3, 20, tzinfo=TZ)),
        types.new("de.showcase.wws.v1.command.RequestPriceChange"))
    created = later.request_price_change(command_from_request(request))
    assert re.match(r"^PA-270224-\d{4}$", created.action_id) and created.created
    rows = {r["action_id"]: r for r in admin_db.fetch(
        "select action_id, ended_at, end_reason from wws.price_action")}
    assert rows[booth] == {"action_id": booth, "ended_at": VALID_TO, "end_reason": "expired"}
    for central in ("PA-SEED-100009", "PA-SEED-100009-199"):
        assert rows[central]["end_reason"] == "expired"
        assert rows[central]["ended_at"] == datetime(2027, 2, 21, 20, tzinfo=TZ)
    assert rows[created.action_id]["ended_at"] is None
    assert later.reset_demo_state("199", True, "reset-day").restored == []
