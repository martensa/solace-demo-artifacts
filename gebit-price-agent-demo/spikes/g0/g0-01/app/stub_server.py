"""G0-01 MCP stub of gpos-booth-tools (plan 3.9), prefix gpos-spike-p01.

Only the tools the max cases need, with the signatures of plan 3.9:

  assess_event(raw, run_id)               -> AssessResult
  prepare_proposal(trigger_id, run_id)    -> PrepareResult  (TR2, two slots)
  get_offers(tx_id, member_ref, run_id)   -> OffersResult   (card, four offers)
  note_event(event_key, verdict, run_id)  -> StatusResult
  size_probe(struct_bytes, run_id)        -> ProbeResult    (spike only)

No GEBIT material: assess_event parses the raw event as plain JSON and
classifies it by '@type' and 'articleNumber'. Every call is remembered
in memory (GET /received) so the spike can compare what SAM delivered
with what was published.

TEXT_MODE sets the text content of every CallToolResult (the
structuredContent is the same in all modes):
  sdk      what the MCP SDK writes for a model return (JSON, indent=2)
  compact  compact JSON (separators , :), UTF-8, no ASCII escaping
  short    one line "<tool>: <verdict/status>"
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import time
from typing import Annotated, Any, Literal

import pydantic_core
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("gpos-spike-p01-stub")

MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_PORT", "8765"))
MCP_PATH = os.environ.get("MCP_PATH", "/mcp")
TEXT_MODE = os.environ.get("TEXT_MODE", "compact")
# plan = shapes of plan 3.9 / RL 2.9 as written; lean = trimmed (fallback
# "Felder kuerzen"). The spike measures both and deploys the one that fits.
SHAPE = os.environ.get("SHAPE", "plan")

mcp = MCPServer(
    name="gpos-spike-p01-tools",
    instructions="G0-01 stub of the deterministic tools of the EuroCIS "
                 "price agent demo. Fictional data only.")

_lock = threading.Lock()
_received: list[dict[str, Any]] = []


# --- result models (plan 3.9; RL 2.9) ---------------------------------------
class AssessResult(BaseModel):
    """Result of assess_event."""
    verdict: str = Field(description="none|price_trigger|member|tied_offer|"
                                     "guardrail|close|cancel|stale|duplicate|probe")
    event_key: str = Field(description="purchaseTransactionId:offset")
    event_type: str = Field(description="Event name from '@type'")
    tx_id: str = ""
    trigger_id: str = ""
    member_ref: str = ""
    kind: str = Field("", description="Trigger kind, e.g. overstock (TR2)")
    article: str = ""
    raw_bytes: int = Field(0, description="UTF-8 bytes of raw as received")
    raw_sha256: str = Field("", description="sha256 of the canonical JSON")
    raw_non_ascii: int = Field(0, description="Non-ASCII characters in raw")
    at_type_ok: bool = Field(False, description="'@type' present and intact")
    probe_bytes: int = 0


class PriceSlot(BaseModel):
    slot: Literal["A", "B"]
    label: str
    old_price: str
    new_price: str
    pct: int
    gain_eur: str
    margin_pct: str
    valid_to: str
    blocked_rule: str = ""


class PrepareResult(BaseModel):
    """Result of prepare_proposal."""
    candidate: Literal["yes", "no"]
    proposal_id: str
    trigger_id: str
    kind: str
    article: str
    recommended: str
    reason: str
    slots: list[PriceSlot] = []
    writer_input: str = Field(description="Compact JSON for the pricing "
                                          "agent, <= 600 B")


class OfferSlot(BaseModel):
    slot: str
    offer_id: str
    kind: Literal["PERSONAL_COUPON", "TIED_OFFER", "CHECKOUT_COUPON"]
    article: str
    price_before: float
    price_after: float
    pct: int
    valid_days: int
    why_facts: list[str] = []
    blocked_rule: str = ""


class OffersResult(BaseModel):
    """Result of get_offers."""
    member_ref: str = ""
    personalised: bool
    recommended: str
    salutation: str = "Sie"
    slots: list[OfferSlot] = []
    agent_input: str = Field(description="Compact JSON for the loyalty "
                                         "agent, <= 600 B")


class StatusResult(BaseModel):
    """Result of note_event."""
    status: str
    event_key: str = ""
    verdict: str = ""


class ProbeResult(BaseModel):
    """Result of size_probe (spike only)."""
    status: str
    struct_bytes: int
    filler: str


# --- helpers ------------------------------------------------------------------
def _text(tool: str, data: dict[str, Any], head: str, mode: str = "") -> str:
    mode = mode or TEXT_MODE
    if mode == "sdk":
        return pydantic_core.to_json(data, fallback=str, indent=2).decode()
    if mode == "short":
        return f"{tool}: {head}"
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _result(tool: str, model: BaseModel, head: str, mode: str = "") -> CallToolResult:
    data = model.model_dump(mode="json", by_alias=True)
    return CallToolResult(content=[TextContent(type="text",
                                               text=_text(tool, data, head, mode))],
                          structured_content=data)


def _cjson(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _remember(tool: str, run_id: str, **kw: Any) -> None:
    with _lock:
        _received.append({"t": round(time.time(), 3), "tool": tool, "run_id": run_id, **kw})
        del _received[:-2000]


# --- max cases ------------------------------------------------------------------
def _tr2(trigger_id: str) -> PrepareResult:
    slots = [
        PriceSlot(slot="A", label="Aktion bis Fr 19.02. 20:00 für alle Kunden",
                  old_price="4,99", new_price="3,99", pct=20, gain_eur="14,50",
                  margin_pct="21,8", valid_to="2027-02-19T20:00"),
        PriceSlot(slot="B", label="Mitglieder-Coupon-Kampagne, Karten mit Tag kaffee",
                  old_price="4,99", new_price="3,49", pct=30, gain_eur="11,20",
                  margin_pct="13,9", valid_to="2027-02-20T20:00"),
    ]
    writer = {
        "kind": "overstock", "article": "Kaffeepads Röstung „Würzig“ 36 Stück",
        "recommended": "A",
        "facts": ["Lieferavis 240 Stück, Bestand reicht 9,5 Tage (Ziel 3)",
                  "Abverkauf 0,41 des Plans", "Ref30 4,99 EUR"],
        "slots": [{"s": "A", "p": "4,99->3,99", "pct": 20, "gain": "14,50",
                   "to": "Fr 19.02. 20:00"},
                  {"s": "B", "p": "4,99->3,49 Coupon", "pct": 30, "gain": "11,20",
                   "who": "Tag kaffee"}],
        "notes": ["Kunden fragen nach größerer Packung – Regal übervoll"],
    }
    if SHAPE == "lean":
        slots = []
    return PrepareResult(candidate="yes", proposal_id=f"P-{trigger_id[-8:]}",
                         trigger_id=trigger_id, kind="overstock", article="article030",
                         recommended="A", reason="overstock_after_delivery",
                         slots=slots, writer_input=_cjson(writer))


def _offers(member_ref: str) -> OffersResult:
    plan_slots = [
        OfferSlot(slot="A", offer_id="OFF-CANTUCCINI-30", kind="PERSONAL_COUPON",
                  article="Cantuccini Mandel 200 g", price_before=2.29, price_after=1.60,
                  pct=30, valid_days=14,
                  why_facts=["Espresso im Korb", "kaffee: 7x in 8 Wochen"]),
        OfferSlot(slot="B", offer_id="OFF-KAFFEEPADS-20", kind="PERSONAL_COUPON",
                  article="Kaffeepads Röstung „Würzig“ 36 Stück", price_before=4.99,
                  price_after=3.99, pct=20, valid_days=7,
                  why_facts=["Tag kaffee", "Überbestand"]),
        OfferSlot(slot="C", offer_id="OFF-MILCHSCHAUM-15", kind="PERSONAL_COUPON",
                  article="Bio-Hafermilch Barista 1 l", price_before=2.19,
                  price_after=1.86, pct=15, valid_days=14,
                  why_facts=["Hafermilch: 3x in 8 Wochen"]),
        OfferSlot(slot="D", offer_id="OFF-PRALINEN-30", kind="CHECKOUT_COUPON",
                  article="Valentins-Pralinen 250 g", price_before=6.99, price_after=4.89,
                  pct=30, valid_days=3, why_facts=["Saisonende"],
                  blocked_rule="G03 Regalaktion läuft"),
    ]
    agent = {
        "salutation": "Sie", "persona": "Kaffeepause", "recommended": "A",
        "offers": [
            {"s": "A", "a": "Cantuccini Mandel 200 g", "p": "2,29->1,60", "pct": 30,
             "why": "Espresso im Korb; kaffee 7x/8 Wo."},
            {"s": "B", "a": "Kaffeepads Röstung „Würzig“", "p": "4,99->3,99", "pct": 20,
             "why": "Tag kaffee"},
            {"s": "C", "a": "Bio-Hafermilch Barista 1 l", "p": "2,19->1,86", "pct": 15,
             "why": "Hafermilch 3x/8 Wo."},
            {"s": "D", "a": "Valentins-Pralinen 250 g", "blocked": "G03 Regalaktion läuft"},
        ],
    }
    slots = plan_slots
    if SHAPE == "lean":
        slots = []
    return OffersResult(member_ref=member_ref, personalised=True, recommended="A",
                        salutation="Sie", slots=slots, agent_input=_cjson(agent))


# --- tools ------------------------------------------------------------------------
@mcp.tool()
def assess_event(
    raw: Annotated[str, Field(description="The raw GEBIT event (proto3 JSON with '@type').")],
    run_id: Annotated[str, Field(description="Workflow run id.")] = "",
) -> Annotated[CallToolResult, AssessResult]:
    """Ingest one raw GEBIT event idempotently and classify it."""
    raw_bytes = len(raw.encode("utf-8"))
    non_ascii = sum(1 for c in raw if ord(c) > 127)
    try:
        ev = json.loads(raw)
    except ValueError as exc:
        _remember("assess_event", run_id, raw_bytes=raw_bytes, parse_error=str(exc),
                  raw_head=raw[:200])
        res = AssessResult(verdict="none", event_key="", event_type="unparsable",
                           raw_bytes=raw_bytes, raw_non_ascii=non_ascii)
        return _result("assess_event", res, "unparsable")
    canon = json.dumps(ev, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    sha = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    at_type = ev.get("@type", "") if isinstance(ev, dict) else ""
    name = at_type.rsplit(".", 1)[-1] if at_type else ""
    tx_id = ev.get("purchaseTransactionId", "") if isinstance(ev, dict) else ""
    offset = (ev.get("metadata") or {}).get("offset", "") if isinstance(ev, dict) else ""
    verdict, trigger_id, member_ref, kind, article, probe = "none", "", "", "", "", 0
    if name == "PositionAdded":
        article = ev.get("articleNumber", "")
        if article == "article030":
            verdict, kind = "price_trigger", "overstock"
            trigger_id = f"TR2-{tx_id[:8]}-{offset}"
    elif name == "LoyaltyMembershipAssigned":
        verdict, member_ref = "member", "M-0001"
    elif name == "SizeProbe":
        verdict, probe = "probe", int(ev.get("structBytes", 0))
        kind = str(ev.get("textMode", ""))
    res = AssessResult(verdict=verdict, event_key=f"{tx_id}:{offset}", event_type=name,
                       tx_id=tx_id, trigger_id=trigger_id, member_ref=member_ref,
                       kind=kind, article=article, raw_bytes=raw_bytes, raw_sha256=sha,
                       raw_non_ascii=non_ascii,
                       at_type_ok=at_type.startswith("type.googleapis.com/"),
                       probe_bytes=probe)
    _remember("assess_event", run_id, raw_bytes=raw_bytes, raw_sha256=sha,
              at_type=at_type, verdict=verdict, event_key=res.event_key,
              non_ascii=non_ascii)
    log.info("assess_event run=%s %s %s %dB", run_id, name, verdict, raw_bytes)
    return _result("assess_event", res, verdict)


@mcp.tool()
def prepare_proposal(
    trigger_id: Annotated[str, Field(description="trigger_id from assess_event.")],
    run_id: Annotated[str, Field(description="Workflow run id.")] = "",
) -> Annotated[CallToolResult, PrepareResult]:
    """Prepare the checked price slots of one trigger (stub: TR2, two slots)."""
    res = _tr2(trigger_id or "TR2-unknown")
    _remember("prepare_proposal", run_id, trigger_id=trigger_id)
    return _result("prepare_proposal", res, res.candidate)


@mcp.tool()
def get_offers(
    tx_id: Annotated[str, Field(description="purchaseTransactionId.")],
    member_ref: Annotated[str, Field(description="Member reference, e.g. M-0001.")] = "",
    run_id: Annotated[str, Field(description="Workflow run id.")] = "",
) -> Annotated[CallToolResult, OffersResult]:
    """Ranked catalogue offers for a loyalty card (stub: four offers)."""
    res = _offers(member_ref or "M-0001")
    _remember("get_offers", run_id, tx_id=tx_id, member_ref=member_ref)
    return _result("get_offers", res, f"{len(res.slots)} slots")


@mcp.tool()
def note_event(
    event_key: Annotated[str, Field(description="event_key from assess_event.")],
    verdict: Annotated[str, Field(description="verdict from assess_event.")],
    run_id: Annotated[str, Field(description="Workflow run id.")] = "",
) -> Annotated[CallToolResult, StatusResult]:
    """Record an event that needs no action."""
    _remember("note_event", run_id, event_key=event_key, verdict=verdict)
    return _result("note_event", StatusResult(status="noted", event_key=event_key,
                                              verdict=verdict), "noted")


@mcp.tool()
def size_probe(
    struct_bytes: Annotated[int, Field(description="Target size of structuredContent.")],
    run_id: Annotated[str, Field(description="Workflow run id.")] = "",
    text_mode: Annotated[str, Field(description="sdk|compact|short; empty = server "
                                                "default.")] = "",
) -> Annotated[CallToolResult, ProbeResult]:
    """Spike only: a result whose structuredContent has about struct_bytes bytes."""
    base = ProbeResult(status="ok", struct_bytes=struct_bytes, filler="")
    pad = max(0, struct_bytes - len(_cjson(base.model_dump())))
    res = ProbeResult(status="ok", struct_bytes=struct_bytes, filler="x" * pad)
    out = _result("size_probe", res, "ok", text_mode)
    full = len(_cjson(out.model_dump(mode="json", by_alias=True, exclude_none=True)).encode())
    _remember("size_probe", run_id, struct_bytes=struct_bytes, text_mode=text_mode,
              full_bytes=full)
    return out


# --- HTTP side routes -----------------------------------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> Response:
    return JSONResponse({"status": "ok", "text_mode": TEXT_MODE, "shape": SHAPE})


@mcp.custom_route("/received", methods=["GET"])
async def received(_request: Request) -> Response:
    with _lock:
        return JSONResponse(list(_received))


def dump_tools() -> None:
    """Print tools/list as JSON (for gen_connector_manifest.py --tools-json)."""
    import asyncio

    async def _list() -> list[dict[str, Any]]:
        out = []
        for t in await mcp.list_tools():
            d = t.model_dump(by_alias=True, exclude_none=True)
            entry = {"name": d["name"], "description": d.get("description") or "",
                     "inputSchema": d.get("inputSchema") or {"type": "object"}}
            if d.get("outputSchema"):
                entry["outputSchema"] = d["outputSchema"]
            out.append(entry)
        return out

    print(json.dumps(asyncio.run(_list()), ensure_ascii=False, indent=1))


def main() -> None:
    log.info("MCP on http://%s:%d%s text_mode=%s shape=%s", MCP_HOST, MCP_PORT, MCP_PATH,
             TEXT_MODE, SHAPE)
    mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT,
            streamable_http_path=MCP_PATH, json_response=True, stateless_http=True,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=False))


if __name__ == "__main__":
    if "--dump-tools" in sys.argv:
        dump_tools()
    else:
        main()
