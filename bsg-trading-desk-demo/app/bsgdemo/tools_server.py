"""bsg-tools: MCP server with the deterministic tools of the demo.

SAM v2 (Go edition) has no in-process Python tools, so every
deterministic data access of the agents and the workflow runs through
this server, attached to SAM as the MCP connector "bsg-desk-tools"
(mcp/remote, streamable-http, auth none, in-cluster URL
http://bsg-tools.bsg-demo.svc:8765/mcp).

Tools
  watch_feed(issuer, product_class, metric, op, threshold,
             hold_seconds, ttl_minutes)   -> creates a watch (bsg-desk-assistant)
  list_watches()                          -> active watches
  stop_watch(watch_id)                    -> stops one watch
  enrich_alert(alert)                     -> 15-min quotes (issuer + peers),
                                             reference prices, news and
                                             deterministic statistics
  publish_desk_note(...)                  -> bsg/desk/notes/{watch_id}
  report_progress(watch_id, node, phase)  -> bsg/desk/progress/{watch_id}

enrich_alert returns a SMALL JSON summary (schema, row counts,
statistics) as text and the data sets as MCP embedded resources
(text/csv, application/json). Whether SAM 2.493.0 turns embedded
resources into artifacts is a Gate 0 check (README "Open points");
ENRICH_EMBED=false returns the summary only.

Robustness contract: the consumer is an LLM, so every failure comes
back as JSON {"error", "hint"}, never as a stack trace.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

import httpx
from pydantic import BaseModel, Field

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _ServerClass
    _MCP_V2 = True
except ModuleNotFoundError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _ServerClass
    _MCP_V2 = False
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import catalog, topics
from .mqttio import Bus
from .watch_engine import METRICS, OPS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bsg-tools")

WATCHER_URL = os.environ.get("WATCHER_URL", "http://feed-watcher.bsg-demo.svc:8080")
MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_PORT", "8765"))
MCP_PATH = os.environ.get("MCP_PATH", "/mcp")
ENRICH_MINUTES = float(os.environ.get("ENRICH_MINUTES", "15"))
ENRICH_RESAMPLE_S = float(os.environ.get("ENRICH_RESAMPLE_S", "5"))
ENRICH_EMBED = os.environ.get("ENRICH_EMBED", "true").lower() == "true"

INSTRUCTIONS = (
    "Deterministic tools of the BSG trading desk demo (fictional issuers "
    "alpha, beta, gamma). Watches are evaluated by a deterministic watcher, "
    "never by the LLM. Data tools return statistics and schemas; the raw "
    "data sets come as attachments and must not be pasted into answers."
)

bus = Bus("bsg-tools")
http = httpx.Client(base_url=WATCHER_URL, timeout=10.0)


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _err(msg: str, hint: str) -> str:
    return _dump({"error": msg, "hint": hint})


def _progress(watch_id: str, node: str, phase: str, **extra: Any) -> None:
    bus.publish(topics.DESK_PROGRESS.format(watch_id=watch_id or "unknown"),
                {"watch_id": watch_id, "node": node, "phase": phase, "ts": _iso(), **extra})


def _server():
    sec = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    if _MCP_V2:
        return _ServerClass(name="bsg-desk-tools", instructions=INSTRUCTIONS)
    return _ServerClass(name="bsg-desk-tools", instructions=INSTRUCTIONS, host=MCP_HOST,
                        port=MCP_PORT, streamable_http_path=MCP_PATH, json_response=True,
                        stateless_http=True, transport_security=sec)


mcp = _server()

Issuer = Annotated[str, Field(description="Issuer: alpha, beta or gamma (fictional).")]
ProductClass = Annotated[str, Field(
    description="Product class: dax-turbo, nasdaq-knockout, discount-cert, or * for all.")]


# --- watches ----------------------------------------------------------------
def create_watch(issuer: str, product_class: str, metric: str, op: str, threshold: float,
                 hold_seconds: float, ttl_minutes: float, wait_s: float = 5.0) -> dict[str, Any]:
    issuer = issuer.strip().lower()
    product_class = product_class.strip().lower() or "*"
    if issuer not in catalog.ISSUERS:
        return {"error": f"unknown issuer {issuer!r}", "hint": f"one of {catalog.ISSUERS}"}
    if product_class != "*" and product_class not in catalog.PRODUCT_CLASSES:
        return {"error": f"unknown product_class {product_class!r}",
                "hint": f"one of {catalog.PRODUCT_CLASSES} or *"}
    if metric not in METRICS:
        return {"error": f"unknown metric {metric!r}", "hint": f"one of {METRICS}"}
    if op not in OPS:
        return {"error": f"unknown op {op!r}", "hint": "one of > >= < <="}
    watch_id = "w-" + uuid.uuid4().hex[:6]
    topic_filter = f"bsg/quotes/{issuer}/{product_class}/>"
    cmd = {"cmd": "create", "watch_id": watch_id, "topic_filter": topic_filter,
           "metric": metric, "op": op, "threshold": float(threshold),
           "hold_seconds": float(hold_seconds), "ttl_minutes": float(ttl_minutes),
           "description": f"{metric} {op} {threshold} for {hold_seconds}s on {topic_filter}"}
    bus.publish(topics.CONTROL_WATCH, cmd, qos=1)
    deadline = time.time() + wait_s
    while time.time() < deadline:  # confirm against the watcher, not against hope
        try:
            r = http.get(f"/watches/{watch_id}")
            if r.status_code == 200:
                return {"status": "created", "watch": r.json(),
                        "alert_topic": topics.ALERT.format(watch_id=watch_id)}
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    return {"error": "watch not confirmed by the watcher within 5 s",
            "hint": "the command was published; check list_watches", "watch_id": watch_id,
            "request": cmd}


@mcp.tool()
def watch_feed(
    issuer: Issuer,
    product_class: ProductClass,
    metric: Annotated[str, Field(description="spread_pct (percent), quote_age_s (seconds "
                                             "without a quote) or drift_vs_ref_pct (percent).")],
    op: Annotated[str, Field(description="Comparison: >, >=, < or <=.")],
    threshold: Annotated[float, Field(description="Threshold in the unit of the metric, "
                                                  "e.g. 0.5 for 0.5 % spread.")],
    hold_seconds: Annotated[float, Field(description="How long the condition must hold "
                                                     "continuously before one alert fires.")],
    ttl_minutes: Annotated[float, Field(description="Lifetime of the watch in minutes.")] = 30,
) -> str:
    """Create a deterministic watch on the live quote feed. The watcher
    publishes exactly one alert on bsg/alerts/{watch_id} when the
    condition holds for hold_seconds. Returns watch_id, topic filter and
    the normalised condition -- confirm all three to the trader."""
    return _dump(create_watch(issuer, product_class, metric, op, threshold,
                              hold_seconds, ttl_minutes))


@mcp.tool()
def list_watches() -> str:
    """List the active watches (id, topic filter, condition, alerts sent)."""
    try:
        return _dump(http.get("/watches", params={"status": "active"}).json())
    except httpx.HTTPError as exc:
        return _err(f"watcher unreachable: {exc}", "retry in a few seconds")


@mcp.tool()
def stop_watch(watch_id: Annotated[str, Field(description="The watch id, e.g. w-1a2b3c.")]) -> str:
    """Stop one watch by id."""
    bus.publish(topics.CONTROL_WATCH, {"cmd": "stop", "watch_id": watch_id}, qos=1)
    time.sleep(0.5)
    try:
        r = http.get(f"/watches/{watch_id}")
        return _dump(r.json() if r.status_code == 200 else {"error": "unknown watch_id"})
    except httpx.HTTPError as exc:
        return _err(f"watcher unreachable: {exc}", "retry in a few seconds")


# --- workflow tools ------------------------------------------------------------
def _parse_alert(alert: Any) -> dict[str, Any]:
    if isinstance(alert, dict):
        a = alert
    else:
        a = json.loads(str(alert))
    if isinstance(a, dict) and "text" in a and "watch_id" not in a:
        a = json.loads(a["text"])  # event path wraps the payload as {"text": ...}
    if not isinstance(a, dict) or "watch_id" not in a:
        raise ValueError("alert has no watch_id")
    return a


class EnrichResult(BaseModel):
    """Result of enrich_alert.

    It is a model, not a plain dict, on purpose: the MCP SDK only emits
    an output schema and `structured_content` for a tool whose return
    type is a model. Without that, SAM's workflow sees the raw envelope
    (`mcp_tool_output`, `message_to_llm`, `status`) and no field of the
    response resolves -- the consuming node then fails with
    "field ... not found in node output; that value has 3 fields".
    """

    watch_id: str = ""
    issuer: str = ""
    peer_issuers: list[str] = Field(default_factory=list)
    primary_underlying: str = ""
    window_minutes: float = 0.0
    statistics: dict[str, Any] = Field(default_factory=dict)
    # detail=true only
    alert: dict[str, Any] | None = None
    affected_products: list[Any] | None = None
    datasets: dict[str, Any] | None = None
    attachments: list[Any] | None = None
    # failure path
    error: str | None = None
    hint: str | None = None


class PublishResult(BaseModel):
    """Result of publish_desk_note -- a model for the same reason."""

    status: str = ""
    topic: str = ""
    lines: int = 0
    error: str | None = None


def enrich(alert: Any, detail: bool = True) -> tuple[dict[str, Any], dict[str, str]]:
    """Deterministic enrichment; returns (summary, {filename: content}).

    With ``detail`` the summary also describes the data sets. The
    workflow leaves it off, because SAM saves an MCP response over
    ``mcp_tool_response_save_threshold_bytes`` (2048 by default) as an
    artifact and replaces the node's structured output with a digest --
    at which point `{{enrich.output.statistics}}` no longer resolves and
    the consuming node fails with "field not found in node output".
    Keeping the workflow's response small is what keeps the numbers
    addressable."""
    a = _parse_alert(alert)
    issuer, pclass = a["issuer"], a.get("product_class") or "*"
    und = a.get("underlying") or catalog.CLASS_UNDERLYING.get(pclass, "dax")
    issuers = ",".join([issuer, *catalog.peers(issuer)])
    common = {"minutes": ENRICH_MINUTES}
    quotes_csv = http.get("/recent", params={**common, "issuer": issuers, "product_class": pclass,
                                             "format": "csv", "resample_s": ENRICH_RESAMPLE_S}).text
    ref_csv = http.get("/reference", params={**common, "format": "csv",
                                             "resample_s": ENRICH_RESAMPLE_S}).text
    news = http.get("/news", params=common).json()
    # since_ms isolates the anomaly: the 60 s mean mixes it with normal
    # quotes and the 15 min window can still hold the previous run.
    stats_params = {**common, "issuer": issuers, "product_class": pclass}
    if a.get("condition_since_ms"):
        stats_params["since_ms"] = int(a["condition_since_ms"])
    stats = http.get("/stats", params=stats_params).json()
    wid = a["watch_id"]
    files = {
        f"bsg_quotes_{wid}.csv": quotes_csv,
        f"bsg_reference_{wid}.csv": ref_csv,
        f"bsg_news_{wid}.json": _dump(news),
    }
    # high_impact_news carries whole items and can grow without bound;
    # the decision rule only needs the count, which stats already has.
    stats.pop("high_impact_news", None)
    stats.pop("as_of", None)
    summary: dict[str, Any] = {
        "watch_id": wid,
        "issuer": issuer,
        "peer_issuers": catalog.peers(issuer),
        "primary_underlying": und,
        "window_minutes": ENRICH_MINUTES,
        "statistics": stats,
    }
    if detail:
        summary["alert"] = {
            k: a.get(k) for k in ("alert_id", "watch_id", "issuer", "isin", "product_class",
                                  "underlying", "metric", "op", "threshold",
                                  "observed_value", "held_seconds", "triggered_at")}
        summary["affected_products"] = a.get("affected_products", [])
        summary["datasets"] = {
            f"bsg_quotes_{wid}.csv": {
                "rows": max(quotes_csv.count("\n") - 1, 0),
                "columns": quotes_csv.split("\n", 1)[0].split(","),
                "content": f"quotes of {issuers} in {pclass}, resampled to "
                           f"{ENRICH_RESAMPLE_S:g}s per product"},
            f"bsg_reference_{wid}.csv": {
                "rows": max(ref_csv.count("\n") - 1, 0),
                "columns": ref_csv.split("\n", 1)[0].split(","),
                "content": "reference index levels (all underlyings)"},
            f"bsg_news_{wid}.json": {"items": len(news), "content": "news items, newest last"},
        }
    return summary, files


@mcp.tool()
def enrich_alert(
    alert: Annotated[str, Field(description="The whole alert payload as JSON. Give "
                                            "this OR the single fields below.")] = "",
    watch_id: Annotated[str, Field(description="watch_id of the alert.")] = "",
    issuer: Annotated[str, Field(description="Issuer of the alert (alpha, beta, gamma).")] = "",
    product_class: Annotated[str, Field(description="Product class of the alert, "
                                                    "or * for all.")] = "",
    condition_since_ms: Annotated[int, Field(description="Epoch ms at which the alert's "
                                                         "condition started.")] = 0,
    alert_id: Annotated[str, Field(description="alert_id of the alert.")] = "",
    underlying: Annotated[str, Field(description="Underlying of the alert, optional.")] = "",
    observed_value: Annotated[float, Field(description="Observed metric value, optional.")] = 0.0,
    detail: Annotated[bool, Field(description="Also describe the data sets and echo the "
                                              "alert. Leave false in a workflow: a response "
                                              "over 2048 bytes is stored as an artifact and "
                                              "its fields stop resolving.")] = False,
) -> EnrichResult:
    """Workflow step 'Alert anreichern': fetch the last 15 minutes of
    quotes (alerting issuer plus the two peers as comparison), the
    reference prices and the news from the watcher, and return a compact
    summary with deterministic spread / reference statistics -- including
    the mean spread of every issuer over exactly the seconds the alert's
    condition has held, which is the number that separates an issuer
    specific anomaly from a market wide one.

    A workflow tool node passes the single fields; a caller holding the
    whole payload passes `alert` instead."""
    wid = watch_id or "unknown"
    try:
        payload: Any = alert or {
            "watch_id": watch_id, "issuer": issuer, "product_class": product_class,
            "condition_since_ms": condition_since_ms, "alert_id": alert_id,
            "underlying": underlying, "observed_value": observed_value,
        }
        a = _parse_alert(payload)
        wid = a["watch_id"]
        _progress(wid, "enrich", "started")
        summary, files = enrich(a, detail=detail)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        _progress(wid, "enrich", "failed", error=str(exc))
        return EnrichResult(
            error=f"bad alert payload: {exc}",
            hint="pass the alert JSON unchanged, or watch_id plus issuer")
    except httpx.HTTPError as exc:
        _progress(wid, "enrich", "failed", error=str(exc))
        return EnrichResult(error=f"watcher unreachable: {exc}", hint="retry once")
    _progress(wid, "enrich", "finished", datasets=list(files))
    if ENRICH_EMBED and detail:
        # Kept for the local smoke test and for a client that can take
        # embedded resources. Whether SAM turns these into artifacts is
        # unverified, so nothing in the workflow depends on them.
        summary["attachments"] = [
            {"uri": f"bsg://enrich/{wid}/{name}",
             "mimeType": "text/csv" if name.endswith(".csv") else "application/json",
             "bytes": len(content)}
            for name, content in files.items()
        ]
    return EnrichResult(**summary)


@mcp.tool()
def publish_desk_note(
    watch_id: Annotated[str, Field(description="watch_id of the alert.")],
    note: Annotated[str, Field(description="The desk note (German, max. 8 lines).")],
    branch: Annotated[str, Field(description="Branch taken: issuer_specific or market_wide.")],
    issuer: Annotated[str, Field(description="Issuer of the alert.")] = "",
    alert_id: Annotated[str, Field(description="alert_id of the alert.")] = "",
    chart_ref: Annotated[str, Field(description="Artifact name or URI of the chart.")] = "",
    workflow_run_id: Annotated[str, Field(description="Workflow run / task id.")] = "",
) -> PublishResult:
    """Workflow step 'Desk-Note publizieren': publish the final desk note
    on bsg/desk/notes/{watch_id} for the trading desk UI."""
    lines = [ln for ln in note.strip().splitlines() if ln.strip()]
    if len(lines) > 8:
        lines = lines[:8]
    msg = {"watch_id": watch_id, "alert_id": alert_id, "issuer": issuer, "branch": branch,
           "note": "\n".join(lines), "chart_ref": chart_ref,
           "workflow_run_id": workflow_run_id, "ts": _iso()}
    bus.publish(topics.DESK_NOTE.format(watch_id=watch_id), msg, qos=1)
    _progress(watch_id, "publish", "finished", branch=branch)
    # A dict, so the MCP response carries structuredContent and a
    # workflow can address the fields.
    return PublishResult(status="published",
                         topic=topics.DESK_NOTE.format(watch_id=watch_id),
                         lines=len(lines))


@mcp.tool()
def report_progress(
    watch_id: Annotated[str, Field(description="watch_id of the alert.")],
    node: Annotated[str, Field(description="Workflow node id.")],
    phase: Annotated[str, Field(description="started, finished or failed.")],
    detail: Annotated[str, Field(description="Optional short detail.")] = "",
) -> str:
    """Publish a progress event for the trading desk UI."""
    _progress(watch_id, node, phase, detail=detail)
    return _dump({"status": "ok"})


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    ok = True
    try:
        ok = httpx.get(f"{WATCHER_URL}/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        ok = False
    return JSONResponse({"status": "ok" if ok else "degraded", "watcher": ok,
                         "mqtt": bus.connected.is_set(), "mcp_path": MCP_PATH})


def main() -> None:
    bus.start()
    log.info("bsg-tools MCP on http://%s:%d%s (watcher %s)", MCP_HOST, MCP_PORT, MCP_PATH,
             WATCHER_URL)
    if _MCP_V2:
        mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT,
                streamable_http_path=MCP_PATH, json_response=True, stateless_http=True,
                transport_security=TransportSecuritySettings(
                    enable_dns_rebinding_protection=False))
    else:
        mcp.run(transport="streamable-http")


def dump_tools() -> None:
    """Print the tools/list result as JSON, without starting a server.

    Lets scripts/gen_connector_manifest.py regenerate the connector's
    tool manifest from inside the cluster, with no port-forward:

        kubectl -n bsg-demo exec deploy/bsg-tools -- \
            python -m bsgdemo.tools_server --dump-tools > tools.json
    """
    import asyncio

    async def _list() -> list[dict[str, Any]]:
        tools = await mcp.list_tools()
        out = []
        for t in tools:
            d = t.model_dump(exclude_none=True) if hasattr(t, "model_dump") else dict(t)
            entry = {"name": d.get("name"),
                     "description": d.get("description") or "",
                     "inputSchema": (d.get("inputSchema") or d.get("input_schema")
                                     or {"type": "object"})}
            schema = d.get("outputSchema") or d.get("output_schema")
            if schema:
                entry["outputSchema"] = schema
            out.append(entry)
        return out

    print(json.dumps(asyncio.run(_list()), indent=1))


if __name__ == "__main__":
    if "--dump-tools" in sys.argv:
        dump_tools()
    else:
        main()
