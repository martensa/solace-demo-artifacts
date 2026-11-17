"""Smoke test of the gpos demo against the lab WITHOUT SAM (spec 13.3).

Runs INSIDE deploy/gpos-ui (cluster DNS, broker Secret, the gposdemo package):
  kubectl -n gpos-demo exec -i deploy/gpos-ui -- python - < scripts/smoke.py
  ... python - --reset-store 199 < scripts/smoke.py   (only the store reset; e2e.py)

Test till 99 of store 199 (GPOS_TEST_LOCATION): no SAM rule subscribes to it, booth
prices stay untouched. Steps:
  1 health of all six services, gRPC health of pos/wws/loyalty, reflection on pos
  2 Postgres (via /health) and SMF (test message on gpos/v1/telemetry/tool/smoke/ping)
  3 agent tools without outputSchema, workflow tools with outputSchema (tools/list)
  4 sizes: workflow tools <= 1800 B result and <= 1500 B text, agent tools text <= 1200 B
  5 flow I1 over the real interfaces (BFF facade ?till=99, MCP JSON-RPC to engine
    and gate as the workflows call them), new price checked in store 199; the engine
    HTTP API (11.8, also through the BFF); a card basket (S3 without the agent:
    AssignLoyaltyMembership, customer_behaviour from loyalty, close); the monitor SSE
    stream (10.2) carries every step of both baskets, none of them marked to_sam;
    then WWS ResetDemoState{store_id:"199"} and engine reset of store 199
  6 READY / NOT READY with the first error
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

import grpc
import httpx
from grpc_health.v1 import health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc

from gposdemo.common.bus import make_bus
from gposdemo.common.config import load_settings
from gposdemo.common.descriptors import load_pool
from gposdemo.common.grpcutil import Client

MCP_URLS = {"pos": "http://gpos-pos:8771", "wws": "http://gpos-wws:8773",
            "loyalty": "http://gpos-loyalty:8772", "engine": "http://gpos-engine:8765",
            "gate": "http://gpos-gate:8766"}
UI_URL = "http://127.0.0.1:8090"
AGENT_SERVICES = ("pos", "wws", "loyalty")
WORKFLOW_SERVICES = ("engine", "gate")
PURCHASE_SERVICE = "de.gebit.rp.purchase.purchase.v2.service.PurchaseTransactionService"
WWS_SERVICE = "de.showcase.wws.v1.service.MerchandiseService"
WORKFLOW_RESULT_MAX, WORKFLOW_TEXT_MAX, AGENT_TEXT_MAX = 1800, 1500, 1200
EAN_DUCK, EAN_BANANAS, EAN_MILK = "2099100000018", "2099100000049", "2099100000100"
EAN_ESPRESSO, EAN_CROISSANTS = "2099100000124", "2099100000179"
CARD, CARD_MEMBER, CARD_PERSONA = "CLUB-1001", "M-1001", "Kaffeepause"  # 6.4, S3
DUCK_INSIGHT = ("Ladenhüter: 9 von 35 geplanten Stück verkauft (7 Tage), Reichweite 6,5 "
                "Wochen, Bestand 96")  # 6.6 facts text (1.4/7.2 show it without Bestand)
ESPRESSO_FACTS = ("Stammartikel der Karte: zuletzt vor 35 Tagen (sonst alle 14 Tage); "
                  "Kartenkunden kaufen 47 % seltener")
R1_EVENTS = ("PositionAdded", "ArticlePositionVoided", "LoyaltyMembershipAssigned",
             "PurchaseTransactionClosed", "PurchaseTransactionCancelled")
STAGE_TEXT = {
    "headline": "GEBIT Ente: Abverkauf ankurbeln",
    "rationale": "Nur 9 von 35 geplanten Enten in 7 Tagen verkauft; "
                 "der Bestand reicht 6,5 Wochen.",
    "facts_line": "9/35 verkauft (7 Tage) · Bestand 96 · Reichweite 6,5 Wo.",
}


class SmokeFailure(RuntimeError):
    """The first failed check; its text is the NOT READY reason."""


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def compact(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def canonical(text: str) -> str:
    """SAM re-serialises event JSON compact with sorted keys (G0-01 finding 3)."""
    return json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


# ------------------------------------------------------------------- MCP client


class Mcp:
    """Stateless streamable-HTTP JSON-RPC, as SAM's str calls the servers."""

    _ids = itertools.count(1)

    def __init__(self, http: httpx.Client, base: str):
        self.http, self.url = http, f"{base}/mcp"
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "gpos-smoke", "version": "1"}})

    def rpc(self, method: str, params: dict) -> dict:
        response = self.http.post(self.url, json={"jsonrpc": "2.0", "id": next(self._ids),
                                                  "method": method, "params": params},
                                  headers={"Accept": "application/json, text/event-stream"})
        expect(response.status_code == 200, f"{self.url} {method}: HTTP {response.status_code}")
        body = response.text
        for line in body.splitlines():          # SSE framing, if any
            if line.startswith("data: "):
                body = line[6:]
        message = json.loads(body)
        expect("error" not in message, f"{self.url} {method}: {message.get('error')}")
        return message["result"]

    def tools(self) -> list[dict]:
        return self.rpc("tools/list", {})["tools"]

    def call(self, tool: str, **args: str) -> dict:
        result = self.rpc("tools/call", {"name": tool, "arguments": args})
        expect(not result.get("isError"), f"{tool}: isError {text_of(result)[:160]}")
        return result


def event_name(topic: str) -> str:
    """gebit/rp/purchase/v2/{category}/{Event}/DE/999/{store}/{till}/{txId} -> Event."""
    parts = topic.split("/")
    return parts[5] if len(parts) > 5 else ""


def text_of(result: dict) -> str:
    return "".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))


class Sizes:
    """Collects (tool, case, result bytes, text bytes) and checks the 8.1 limits."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, int, int]] = []

    def workflow(self, tool: str, case: str, result: dict) -> dict:
        full, text = len(compact(result).encode()), len(text_of(result).encode())
        self.rows.append((tool, case, full, text))
        expect(full <= WORKFLOW_RESULT_MAX and text <= WORKFLOW_TEXT_MAX,
               f"size {tool} ({case}): result {full} B / text {text} B over 1800/1500")
        expect("\n" not in text_of(result), f"{tool}: text content is not one line")
        return result.get("structuredContent") or {}

    def agent(self, tool: str, case: str, result: dict) -> dict:
        text = text_of(result)
        size = len(text.encode())
        self.rows.append((tool, case, len(compact(result).encode()), size))
        expect(size <= AGENT_TEXT_MAX, f"size {tool} ({case}): text {size} B over 1200")
        expect("structuredContent" not in result or not result["structuredContent"],
               f"{tool}: agent tool returns structuredContent")
        return json.loads(text)

    def report(self) -> None:
        for tool, case, full, text in self.rows:
            print(f"   size {tool:24} {case:28} result {full:5d} B  text {text:5d} B")


class SseReader:
    """The monitor's stream ``GET /api/events`` (10.2), read in a daemon thread."""

    def __init__(self, url: str):
        self.url = url
        self.http = httpx.Client(timeout=httpx.Timeout(5.0, read=None))
        self.events: list[tuple[str, dict]] = []
        self.lock = threading.Lock()
        self.error = ""
        self.closed = False

    def start(self) -> dict:
        """Connect; returns the ``hello`` snapshot."""
        threading.Thread(target=self._read, name="smoke-sse", daemon=True).start()
        return self.wait("hello", lambda _d: True, timeout=5)

    def _read(self) -> None:
        kind, data = "", []
        try:
            with self.http.stream("GET", self.url) as response:
                for line in response.iter_lines():
                    if self.closed:
                        return
                    if line.startswith("event: "):
                        kind = line[7:]
                    elif line.startswith("data: "):
                        data.append(line[6:])
                    elif not line and kind:
                        with self.lock:
                            self.events.append((kind, json.loads("\n".join(data))))
                        kind, data = "", []
        except (httpx.HTTPError, ValueError) as exc:
            if not self.closed:
                self.error = f"{type(exc).__name__}: {str(exc)[:160]}"

    def of(self, kind: str, match: Callable[[dict], bool]) -> list[dict]:
        with self.lock:
            return [d for k, d in self.events if k == kind and match(d)]

    def wait(self, kind: str, match: Callable[[dict], bool], timeout: float = 8) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            hits = self.of(kind, match)
            if hits:
                return hits[0]
            expect(not self.error, f"SSE /api/events: {self.error}")
            time.sleep(0.1)
        seen = self.of(kind, lambda _d: True)
        last = f"; last of {len(seen)}: {compact(seen[-1])[:240]}" if seen else ""
        raise SmokeFailure(f"SSE {kind}: no matching event within {timeout:.0f} s{last}")

    def close(self) -> None:
        self.closed = True
        self.http.close()


# ------------------------------------------------------------------ the checks


class Smoke:
    def __init__(self) -> None:
        self.s = load_settings("ui")
        self.http = httpx.Client(timeout=15)
        self.mcp: dict[str, Mcp] = {}
        self.sizes = Sizes()
        self.run_id = f"smoke-{uuid.uuid4().hex[:12]}"
        self.events: list[tuple[str, bytes]] = []
        self.lock = threading.Lock()
        self.bus = None
        self.sse = SseReader(f"{UI_URL}/api/events")
        self.i1: dict[str, str] = {}      # tx_id, review_id, proposal_id, action_id, next_tx
        self.card: dict[str, str] = {}    # tx_id, review_id
        self.booth_counters: dict[str, Any] = {}

    # helpers --------------------------------------------------------------
    def server(self, svc: str) -> Mcp:
        if svc not in self.mcp:
            self.mcp[svc] = Mcp(self.http, MCP_URLS[svc])
        return self.mcp[svc]

    def facade(self, method: str, body: dict) -> dict:
        response = self.http.post(f"{UI_URL}/api/pos/{method}?till=99", json=body)
        data = response.json()
        expect(response.status_code == 200 and data.get("ok"),
               f"facade {method}: HTTP {response.status_code} {data.get('code', '')} "
               f"{data.get('message', '')}".rstrip())
        return data.get("result") or {}

    def on_event(self, topic: str, payload: bytes, _props: dict[str, str]) -> None:
        with self.lock:
            self.events.append((topic, payload))

    def wait_event(self, tx_id: str, event: str, count: int = 1,
                   timeout: float = 8) -> list[dict]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                hits = [json.loads(p) for t, p in self.events
                        if event_name(t) == event and t.endswith(f"/{tx_id}")]
            if len(hits) >= count:
                return hits
            time.sleep(0.1)
        raise SmokeFailure(f"{event} of {tx_id} not received within {timeout:.0f} s")

    def r1_payloads(self, tx_id: str) -> list[tuple[str, str]]:
        with self.lock:
            return [(event_name(t), p.decode("utf-8")) for t, p in self.events
                    if t.endswith(f"/{tx_id}") and event_name(t) in R1_EVENTS]

    def clear_test_till(self) -> None:
        """Cancel a basket left open on till 99 by an aborted earlier run."""
        till = self.s.test_location.split(".")[4]
        state = self.http.get(f"{self.s.pos_admin_url}/admin/till/{till}").json()
        open_tx = state.get("open_tx") if isinstance(state, dict) else None
        tx_id = (open_tx or {}).get("tx_id") if isinstance(open_tx, dict) else open_tx
        if tx_id:
            self.cancel(str(tx_id))

    def catalog(self) -> dict[str, dict]:
        articles = self.http.get(f"{UI_URL}/api/catalog").json()["articles"]
        return {a["gtin"]: a for a in articles}

    def new_basket(self) -> str:
        result = self.facade("CreatePurchaseTransaction", {})
        tx_id = result.get("purchaseTransactionId") or result.get("value") or ""
        expect(bool(tx_id), f"CreatePurchaseTransaction: no id in {compact(result)[:120]}")
        return str(tx_id)

    def scan(self, tx_id: str, article: dict) -> None:
        self.facade("AddArticle", {
            "purchaseTransactionId": tx_id, "articleId": article["article_id"], "itemCount": 1,
            "capturingInformation": {"inputMethod": "SCANNER", "inputType": "EAN13",
                                     "inputValue": article["gtin"]}})

    def pay_cash(self, tx_id: str, total: Decimal) -> None:
        cents = max(5, math.ceil(total / 5) * 5) * 100
        self.facade("StartPaymentProcess", {"purchaseTransactionId": tx_id})
        self.facade("CreateCashPayment", {
            "purchaseTransactionId": tx_id, "clientId": "kasse-99",
            "clientTransactionId": str(uuid.uuid4()),
            "amount": {"currency": "EUR", "amount": {"scale": 2, "intVal": str(cents)}}})

    def cancel(self, tx_id: str) -> None:
        self.facade("CancelPurchaseTransaction", {
            "purchaseTransactionId": tx_id, "cancellationReason": "smoke",
            "cancellationReasonCode": "ABANDONED"})

    # steps ----------------------------------------------------------------
    def step_health(self) -> None:
        for svc, base in {**MCP_URLS, "ui": UI_URL}.items():
            response = self.http.get(f"{base}/health")
            expect(response.status_code == 200, f"/health {svc}: HTTP {response.status_code}")
            body = response.json()
            expect(body.get("status") == "ok", f"/health {svc}: {compact(body)[:120]}")
            if svc in ("pos", "wws", "loyalty", "engine", "gate"):
                expect(body.get("db") is True, f"/health {svc}: db not reachable (A-9)")
            expect(body.get("bus", True) is True, f"/health {svc}: bus not connected (A-8)")
        for svc, target in (("pos", self.s.pos_grpc), ("wws", self.s.wws_grpc),
                            ("loyalty", self.s.loyalty_grpc)):
            with grpc.insecure_channel(target) as channel:
                status = health_pb2_grpc.HealthStub(channel).Check(
                    health_pb2.HealthCheckRequest(service=""), timeout=5).status
                expect(status == health_pb2.HealthCheckResponse.SERVING,
                       f"gRPC health {svc}: {status}")
        with grpc.insecure_channel(self.s.pos_grpc) as channel:
            stub = reflection_pb2_grpc.ServerReflectionStub(channel)
            answers = stub.ServerReflectionInfo(
                iter([reflection_pb2.ServerReflectionRequest(list_services="")]), timeout=5)
            names = {s.name for a in answers for s in a.list_services_response.service}
            expect(PURCHASE_SERVICE in names, "reflection on gpos-pos: no "
                                              "PurchaseTransactionService")

    def step_bus(self) -> None:
        self.bus = make_bus(self.s, f"gpos-smoke-{uuid.uuid4().hex[:8]}")
        ping: list[bytes] = []
        self.bus.subscribe("gpos/v1/telemetry/tool/smoke/ping",
                           lambda _t, payload, _p: ping.append(payload))
        self.bus.subscribe("gebit/rp/purchase/v2/>", self.on_event)
        time.sleep(0.5)
        marker = uuid.uuid4().hex
        self.bus.publish("gpos/v1/telemetry/tool/smoke/ping",
                         compact({"schema_version": "1", "type": "smoke", "id": marker}))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not any(marker.encode() in p for p in ping):
            time.sleep(0.1)
        expect(any(marker.encode() in p for p in ping), "SMF: smoke ping not received")

    def step_tools(self) -> None:
        for svc in AGENT_SERVICES:
            for tool in self.server(svc).tools():
                expect(not tool.get("outputSchema"),
                       f"{svc}.{tool['name']}: agent tool with outputSchema (spec 8.1)")
        for svc in WORKFLOW_SERVICES:
            for tool in self.server(svc).tools():
                expect(bool(tool.get("outputSchema")),
                       f"{svc}.{tool['name']}: workflow tool without outputSchema")

    def step_agent_sizes(self, catalog: dict[str, dict]) -> None:
        """Every agent tool with maximal arguments. ``ref`` is a basket of till 99 that
        the BFF has already seen, so the booth counter of agent API queries (10.2) leaves
        these calls out."""
        wws, loyalty, pos = self.server("wws"), self.server("loyalty"), self.server("pos")
        longest = sorted(catalog.values(), key=lambda a: len(a["name"]), reverse=True)[:9]
        ref = self.new_basket()
        for article in longest:
            self.scan(ref, article)
        self.wait_event(ref, "PositionAdded", count=len(longest))
        self.sse.wait("pos_event", lambda d: d.get("tx_id") == ref)
        for number in ("100001", "100012"):
            self.sizes.agent("get_article", number,
                             wws.call("get_article", article_number=number, ref=ref))
        self.sizes.agent("get_sales_performance", "100001",
                         wws.call("get_sales_performance", article_number="100001", ref=ref))
        for number in ("100008", "100009"):
            self.sizes.agent("get_season_info", number,
                             wws.call("get_season_info", article_number=number, ref=ref))
        self.sizes.agent("get_member_profile", CARD_MEMBER,
                         loyalty.call("get_member_profile", membership_id=CARD_MEMBER, ref=ref))
        self.sizes.agent("get_purchase_behaviour", f"{CARD_MEMBER}/100012",
                         loyalty.call("get_purchase_behaviour", membership_id=CARD_MEMBER,
                                      article_number="100012", ref=ref))
        self.sizes.agent("get_till_status", "booth", pos.call("get_till_status", ref=ref))
        data = self.sizes.agent("get_transaction", "9 long lines",
                                pos.call("get_transaction", tx_id=ref, ref=ref))
        expect(len(data.get("lines", [])) <= 8 and data.get("more") == 1,
               "get_transaction: expected 8 lines and more=1 for 9 lines")
        self.cancel(ref)

    def play(self, basket: list[dict], card: str = "") -> str:
        """New basket on till 99, optional card, scans, cash payment until Closed."""
        tx_id = self.new_basket()
        if card:
            self.facade("AssignLoyaltyMembership", {"purchaseTransactionId": tx_id,
                                                    "membershipIdentificationValue": card})
        for article in basket:
            self.scan(tx_id, article)
        self.pay_cash(tx_id, sum(Decimal(a["price"].replace(",", ".")) for a in basket))
        self.wait_event(tx_id, "PurchaseTransactionClosed")
        return tx_id

    def assess_basket(self, tx_id: str, case: str) -> list[tuple[str, str, str, str]]:
        """``assess_event`` for every R1 event of the basket, as the R1 workflow calls it."""
        verdicts = []
        for event, payload in self.r1_payloads(tx_id):
            sc = self.sizes.workflow("assess_event", f"{case} {event}", self.server(
                "engine").call("assess_event", raw=canonical(payload), run_id=self.run_id))
            verdicts.append((event, sc.get("verdict"), sc.get("article_number"),
                             sc.get("insight_code")))
        return verdicts

    def prepare(self, tx_id: str, case: str) -> dict:
        """``raise_basket_review`` and ``prepare_review``: exactly one free candidate."""
        engine = self.server("engine")
        trig = self.sizes.workflow("raise_basket_review", case, engine.call(
            "raise_basket_review", tx_id=tx_id, run_id=self.run_id))
        expect(trig.get("status") == "requested", f"raise_basket_review ({case}): {trig}")
        prep = self.sizes.workflow("prepare_review", case, engine.call(
            "prepare_review", review_id=trig["review_id"], run_id=self.run_id))
        expect(prep.get("candidate") == "yes" and prep.get("candidates") == 1,
               f"prepare_review ({case}): candidate {prep.get('candidate')} / "
               f"{prep.get('candidates')}")
        agent_input = prep.get("agent_input", "")
        expect(len(agent_input.encode()) <= 1000 and tx_id in agent_input,
               f"prepare_review ({case}): agent_input over 1000 B or without tx_id")
        return prep

    def step_i1(self, catalog: dict[str, dict]) -> None:
        engine, gate = self.server("engine"), self.server("gate")
        tx_id = self.play([catalog[EAN_DUCK], catalog[EAN_BANANAS], catalog[EAN_MILK]])
        verdicts = self.assess_basket(tx_id, "I1")
        expect([v[1] for v in verdicts] == ["scan", "scan", "scan", "close"],
               f"assess_event verdicts {[v[1] for v in verdicts]}")
        expect(("PositionAdded", "scan", "100001", "slow_seller") in verdicts,
               "assess_event: GEBIT Ente is not slow_seller")
        review_id = self.prepare(tx_id, "I1")["review_id"]
        # 8.2.2 step 5: the evidence of the fast agent, numbers at the 160-character
        # maximum (NUMBERS_MAX since image 0.1.3, UC1-32); it ends in "x", so an image
        # that still cuts at 120 (stale pull, wrong tag) fails here
        numbers = ("trend=falling; sold_7d=9; plan_7d=35; weeks_of_supply=6.5; "
                   "weekly_first=34; weekly_last=9; " + "x" * 80)[:160]
        evidence = self.sizes.workflow("note_evidence", "I1 max", engine.call(
            "note_evidence", review_id=review_id, model="fast", tx_status="closed",
            c1_article="100001", c1_reason="slow_seller", c1_holds="yes",
            c1_numbers=numbers, c1_tools="get_sales_performance", c2_article="none",
            c2_reason="none", c2_holds="unknown", c2_numbers="none", c2_tools="none",
            run_id=self.run_id))
        expect((evidence.get("status"), evidence.get("checked"), evidence.get("holding"))
               == ("noted", 1, 1), f"note_evidence: {evidence}")
        kept = json.loads(evidence.get("evidence") or "{}").get("items") or [{}]
        expect(len(numbers) == 160 and kept[0].get("numbers") == numbers,
               f"note_evidence: numbers not kept at 160 characters "
               f"({len(kept[0].get('numbers') or '')})")
        stage = self.sizes.workflow("stage_proposal", "I1", engine.call(
            "stage_proposal", review_id=review_id, article_number="100001",
            reason="slow_seller", step_pct="20", run_id=self.run_id, model="planning",
            **STAGE_TEXT))
        expect((stage.get("status"), stage.get("old_price"), stage.get("new_price"),
                stage.get("pct_label"), stage.get("step_pct"))
               == ("ready", "9,99", "7,99", "-20 %", 20), f"stage_proposal: {stage}")
        proposal_id = stage["proposal_id"]
        check = self.sizes.workflow("check_proposal", "I1", engine.call(
            "check_proposal", proposal_id=proposal_id, run_id=self.run_id))
        expect(check.get("status") == "awaiting_approval", f"check_proposal: {check}")
        time.sleep(self.s.gate_min_delay_s + 1)
        labels = {k: check[k] for k in ("proposal_hash", "article_name", "old_price",
                                        "new_price", "pct_label", "reason_label",
                                        "valid_to_label")}
        applied = self.sizes.workflow("apply_price", "I1", gate.call(
            "apply_price", proposal_id=proposal_id, run_id=self.run_id, approved_at="",
            **labels))
        expect(applied.get("status") == "applied", f"apply_price: {applied}")
        outcome = self.sizes.workflow("record_outcome", "I1", engine.call(
            "record_outcome", proposal_id=proposal_id, run_id=self.run_id,
            agent_status="applied", action_id=applied.get("action_id", ""), error=""))
        expect(outcome.get("outcome") == "approved" and outcome.get("notify") == "yes",
               f"record_outcome: {outcome}")
        self.sizes.workflow("note_event", "max key", engine.call(
            "note_event", event_key=f"{tx_id}:{'9' * 6}", verdict="ignore", run_id=self.run_id))
        self.i1 = {"tx_id": tx_id, "review_id": review_id, "proposal_id": proposal_id,
                   "action_id": applied.get("action_id", ""),
                   "next_tx": self.check_new_price(catalog[EAN_DUCK])}

    def check_new_price(self, duck: dict) -> str:
        """WWS answers 7,99 BOOTH_ACTION in store 199 and the next scan carries it."""
        test_store = self.s.test_location.split(".")[3]
        pool = load_pool([self.s.showcase_descriptor_set])
        price = Client(pool, WWS_SERVICE, self.s.wws_grpc).call_json(
            "GetEffectivePrice", {"articleNumber": "100001", "storeId": test_store})
        amount = (price.get("price") or {}).get("amount") or {}
        expect((amount.get("intVal"), price.get("source"))
               == ("799", "PRICE_SOURCE_BOOTH_ACTION"),
               f"GetEffectivePrice 100001/{test_store}: {compact(price)[:160]}")
        tx_id = self.new_basket()
        self.scan(tx_id, duck)
        added = self.wait_event(tx_id, "PositionAdded")[0]
        props = {p.get("key"): (p.get("typedValue") or {}).get("stringValue")
                 for p in added.get("extensionProperties", [])}
        expect(props.get("showcase.priceSource") == "BOOTH_ACTION",
               f"next scan: priceSource {props.get('showcase.priceSource')}")
        self.cancel(tx_id)
        return tx_id

    def get_json(self, url: str) -> dict:
        response = self.http.get(url)
        expect(response.status_code == 200, f"GET {url}: HTTP {response.status_code}")
        return response.json()

    def step_engine_api(self) -> None:
        """11.8 on the I1 basket: proposal with its approval row (one clock, the
        engine's), review, till state; the BFF forwards /api/proposals/{id} unchanged."""
        pid, rid, engine_url = self.i1["proposal_id"], self.i1["review_id"], self.s.engine_url
        proposal = self.get_json(f"{engine_url}/api/proposals/{pid}")
        approval = proposal.get("approval") or {}
        expect((proposal.get("state"), proposal.get("action_id"), approval.get("apply_calls"))
               == ("approved", self.i1["action_id"], 1),
               f"engine /api/proposals/{pid}: {compact(proposal)[:200]}")
        gap = (datetime.fromisoformat(approval["first_apply_at"])
               - datetime.fromisoformat(approval["checked_at"])).total_seconds()
        expect(gap >= self.s.gate_min_delay_s,
               f"engine /api/proposals/{pid}: first_apply_at - checked_at = {gap:.2f} s")
        review = self.get_json(f"{engine_url}/api/reviews/{rid}")
        expect((review.get("state"), review.get("proposal_id"), review.get("tx_id"))
               == ("proposed", pid, self.i1["tx_id"]),
               f"engine /api/reviews/{rid}: {compact(review)[:200]}")
        store, till = self.s.test_location.split(".")[3:5]
        state = self.get_json(f"{engine_url}/api/state?store={store}&till={till}")
        expect(((state.get("review") or {}).get("review_id"),
                (state.get("proposal") or {}).get("proposal_id")) == (rid, pid)
               and state["counts"]["approved"] >= 1,
               f"engine /api/state {store}/{till}: {compact(state)[:200]}")
        via_bff = self.get_json(f"{UI_URL}/api/proposals/{pid}")
        expect((via_bff.get("state"), (via_bff.get("approval") or {}).get("apply_calls"))
               == ("approved", 1), f"BFF /api/proposals/{pid}: {compact(via_bff)[:200]}")

    def step_card(self, catalog: dict[str, dict]) -> None:
        """S3 without the agent: card with profiling consent; Espresso becomes the
        customer_behaviour candidate from loyalty (6.8: 35 days, interval 14, -46,7 %)."""
        tx_id = self.play([catalog[EAN_ESPRESSO], catalog[EAN_CROISSANTS]], card=CARD)
        verdicts = self.assess_basket(tx_id, "card")
        expect([v[1] for v in verdicts] == ["member", "scan", "scan", "close"],
               f"assess_event verdicts (card) {[v[1] for v in verdicts]}")
        expect(("PositionAdded", "scan", "100012", "customer_behaviour") in verdicts,
               "assess_event: Espresso with card is not customer_behaviour")
        prep = self.prepare(tx_id, "card")
        agent_input = json.loads(prep["agent_input"])
        candidate = agent_input["candidates"][0]
        expect(prep.get("membership_id") == CARD_MEMBER and agent_input.get("card") == {
            "membership_id": CARD_MEMBER, "persona": CARD_PERSONA, "consent_profiling": True},
               f"prepare_review (card): card {agent_input.get('card')}")
        expect((candidate.get("a"), candidate.get("signals"), candidate.get("facts"),
                candidate.get("suggested_step_pct"))
               == ("100012", ["customer_behaviour"], ESPRESSO_FACTS, 10),
               f"prepare_review (card): candidate {compact(candidate)[:200]}")
        self.card = {"tx_id": tx_id, "review_id": prep["review_id"]}

    def step_sse_connect(self) -> None:
        hello = self.sse.start()
        expect(hello.get("booth") == {"store": "101", "till": "01"} and "counters" in hello,
               f"SSE hello: {compact(hello)[:160]}")
        self.booth_counters = hello["counters"]

    def step_booth_counters(self) -> None:
        """Test till traffic never counts on the booth monitor (10.2, only 101/01)."""
        now = self.get_json(f"{UI_URL}/api/state")["counters"]
        expect(now == self.booth_counters,
               f"booth counters changed during the smoke (till 99 counted, or the booth "
               f"till was in use): {self.booth_counters.get('line')} -> {now.get('line')}")

    def step_monitor_stream(self) -> None:
        """Every step of both baskets reached /api/events; nothing was marked for SAM."""
        sse, i1, card = self.sse, self.i1, self.card
        for tx_id in (i1["tx_id"], i1["next_tx"], card["tx_id"]):
            seen = sse.of("pos_event", lambda d, t=tx_id: d.get("tx_id") == t)
            expect(bool(seen) and all(d["till"] == "99" and d["to_sam"] is False for d in seen),
                   f"SSE pos_event of {tx_id}: missing, not till 99 or marked to_sam")
        for tx_id in (i1["tx_id"], card["tx_id"]):
            sse.wait("pos_event", lambda d, t=tx_id: d.get("tx_id") == t
                     and d.get("event") == "PurchaseTransactionClosed")
        sse.wait("pos_event", lambda d: d.get("tx_id") == card["tx_id"]
                 and d.get("event") == "LoyaltyMembershipAssigned" and d.get("card") == CARD)
        sse.wait("insight", lambda d: d.get("tx_id") == i1["tx_id"]
                 and (d.get("article_number"), d.get("code"), d.get("text"))
                 == ("100001", "slow_seller", DUCK_INSIGHT))
        sse.wait("insight", lambda d: d.get("tx_id") == card["tx_id"]
                 and (d.get("article_number"), d.get("code")) == ("100012", "customer_behaviour"))
        states = {d.get("state") for d in sse.of(
            "review", lambda d: d.get("review_id") == i1["review_id"])}
        expect({"prepared", "proposed"} <= states,
               f"SSE review {i1['review_id']}: states {sorted(map(str, states))}")
        sse.wait("review", lambda d: d.get("review_id") == card["review_id"]
                 and d.get("state") == "prepared"
                 and (d.get("membership") or {}).get("membership_id") == CARD_MEMBER)
        approved = sse.wait("proposal", lambda d: d.get("proposal_id") == i1["proposal_id"]
                            and d.get("state") == "approved")
        expect((approved.get("old_price"), approved.get("new_price"), approved.get("pct_label"),
                approved.get("action_id")) == ("9,99", "7,99", "\u221220 %", i1["action_id"]),
               f"SSE proposal approved: {compact(approved)[:200]}")
        change = sse.wait("price_change", lambda d: d.get("proposal_id") == i1["proposal_id"])
        expect((change.get("event"), change.get("store"), change.get("old"), change.get("new"))
               == ("PriceChangeApplied", "199", "9,99", "7,99"),
               f"SSE price_change: {compact(change)[:200]}")
        sse.wait("pos_event", lambda d: d.get("tx_id") == i1["next_tx"]
                 and (d.get("event"), d.get("price"), d.get("price_source"))
                 == ("PositionAdded", "7,99", "BOOTH_ACTION"))
        tools = {d.get("tool") for d in sse.of("tool_call",
                                                lambda d: d.get("run_id") == self.run_id)}
        expect({"assess_event", "prepare_review", "note_evidence", "stage_proposal",
                "apply_price", "record_outcome"} <= tools,
               f"SSE tool_call of {self.run_id}: {sorted(tools)}")

def reset_store(s: Any, store: str, http: httpx.Client) -> None:
    """Store reset of the probe/test store: engine (open reviews and proposals
    superseded) and WWS ResetDemoState{store_id} (booth actions ended)."""
    response = http.post(f"{s.engine_url}/api/reset", json={"scope": "booth", "store_id": store})
    expect(response.status_code == 200, f"engine reset {store}: HTTP {response.status_code}")
    pool = load_pool([s.showcase_descriptor_set])
    Client(pool, WWS_SERVICE, s.wws_grpc).call_json("ResetDemoState",
                                                    {"storeId": store, "full": False})


def run(steps: list[tuple[str, Callable[[], None]]]) -> bool:
    for name, fn in steps:
        started = time.monotonic()
        try:
            fn()
        except SmokeFailure as exc:
            print(f"NOT READY: {name}: {exc}")
            return False
        except Exception as exc:  # noqa: BLE001 -- report any first error, never a trace
            print(f"NOT READY: {name}: {type(exc).__name__}: {str(exc)[:200]}")
            return False
        print(f"ok {name} ({(time.monotonic() - started) * 1000:.0f} ms)", flush=True)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset-store", metavar="STORE", help="only reset this store (199)")
    args = ap.parse_args()
    if args.reset_store:
        expect(args.reset_store != "101", "--reset-store 101: use scripts/reset.sh")
        reset_store(load_settings("ui"), args.reset_store, httpx.Client(timeout=15))
        print(f"store {args.reset_store} reset")
        return 0
    smoke = Smoke()
    catalog: dict[str, dict] = {}
    test_store = smoke.s.test_location.split(".")[3]
    ok = run([
        ("1 health", smoke.step_health),
        ("2 smf", smoke.step_bus),
        ("3 tools/list", smoke.step_tools),
        ("4 catalog", lambda: catalog.update(smoke.catalog())),
        ("4 till 99 free", smoke.clear_test_till),
    ])
    if ok:  # from here on store 199 changes: always end with its reset
        ok = run([("4 monitor SSE connected", smoke.step_sse_connect),
                  ("4 agent tool sizes", lambda: smoke.step_agent_sizes(catalog)),
                  ("5 flow I1 on till 99", lambda: smoke.step_i1(catalog)),
                  ("5 engine HTTP API", smoke.step_engine_api),
                  ("5 card basket on till 99", lambda: smoke.step_card(catalog)),
                  ("5 monitor SSE stream", smoke.step_monitor_stream),
                  ("5 booth counters untouched", smoke.step_booth_counters)])
        ok = run([("5 till 99 free", smoke.clear_test_till),
                  ("5 reset store 199", lambda: reset_store(smoke.s, test_store, smoke.http))
                  ]) and ok
    smoke.sizes.report()
    smoke.sse.close()
    if smoke.bus is not None:
        smoke.bus.close()
    print("READY" if ok else "smoke: NOT READY")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
