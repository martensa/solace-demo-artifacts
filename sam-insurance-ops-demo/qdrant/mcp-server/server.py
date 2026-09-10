#!/usr/bin/env python3
"""Acme Claims Knowledge -- MCP server in front of the Qdrant knowledge
base of the insurance demo (sam-insurance-ops-demo/qdrant).

SAM has no native Qdrant connector, so the platform reaches the
knowledge base through this server: connector "Acme Claims Knowledge"
(mcp/remote, connection_type streamable-http,
server_url http://host.docker.internal:8765/mcp, auth_type none).

Tools (one search per document type + one lookup):

  search_policy_wordings(query, top_k)    doc_type policy_wordings
  search_claims_guidelines(query, top_k)  doc_type claims_guidelines
  search_partner_contracts(query, top_k)  doc_type partner_contracts
  search_storm_playbooks(query, top_k)    doc_type storm_playbooks
  get_knowledge_document(doc_id)          full payload of one document

Every search embeds the query with the same fastembed model the seed
job used (BAAI/bge-small-en-v1.5, 384 dims, cosine), filters the
collection by doc_type and returns a JSON list of
{doc_id, title, section, score, text}. GET /health answers HTTP 200
with a small JSON status for preflight.sh and the compose healthcheck.

Robustness contract (the consumer is an LLM, never a stack trace):
  - top_k outside 1..20 is clamped, never rejected; an over-long
    query is truncated to MAX_QUERY_CHARS.
  - an empty query, an unknown doc_id, an unseeded collection and a
    Qdrant/model failure all answer with JSON {error|results, hint}.
  - the embedding model is loaded once, lazily, under a lock (the
    tools run in worker threads); a failed load is retried on the
    next call.
  - /health never raises: it uses a separate 3 s client and reports
    "degraded" (still HTTP 200) when Qdrant cannot be counted.

SDK note (verified 2026-09 against the official python SDK): mcp 2.x
renamed FastMCP to MCPServer, removed the mcp.server.fastmcp module
and moved host/port/path/json_response/stateless_http/
transport_security from the constructor to run(). mcp 1.10-1.30 keep
them on the constructor. Both majors are handled below, so the pin
"mcp[cli]>=1.10" works whichever one pip resolves. The transport name
"streamable-http" and the @custom_route decorator are identical in
both. DNS-rebinding protection is switched OFF explicitly: the SDK
auto-enables it for loopback hosts and would answer 421 to the Host
header SAM pods send (host.docker.internal:8765).

Configuration (environment, defaults match docker-compose.yaml):
  QDRANT_URL            http://acme-knowledge-qdrant:6333
  COLLECTION            acme_knowledge
  EMBEDDING_MODEL       BAAI/bge-small-en-v1.5
  FASTEMBED_CACHE_DIR   /app/models   (model cache volume)
  MCP_HOST / MCP_PORT   0.0.0.0 / 8765
  MCP_PATH              /mcp
"""

import json
import logging
import os
import threading
from typing import Annotated, Any

import anyio
from fastembed import TextEmbedding
from pydantic import Field
from qdrant_client import QdrantClient, models
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

try:  # mcp >= 2.0: FastMCP was renamed to MCPServer
    from mcp.server.mcpserver import MCPServer as _ServerClass

    _MCP_V2 = True
except ModuleNotFoundError:  # mcp 1.10 .. 1.30
    from mcp.server.fastmcp import FastMCP as _ServerClass

    _MCP_V2 = False

# Present in every supported release (1.10+); guarded anyway so an
# SDK without the module (and therefore without the protection) runs.
try:
    from mcp.server.transport_security import TransportSecuritySettings
except ImportError:  # pragma: no cover
    TransportSecuritySettings = None  # type: ignore[assignment,misc]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("acme-knowledge-mcp")

# --- Configuration -------------------------------------------------------
QDRANT_URL = os.environ.get("QDRANT_URL", "http://acme-knowledge-qdrant:6333")
COLLECTION = os.environ.get("COLLECTION", "acme_knowledge")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
MODEL_CACHE_DIR = os.environ.get("FASTEMBED_CACHE_DIR", "/app/models")
MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_PORT", "8765"))
MCP_PATH = os.environ.get("MCP_PATH", "/mcp")

SERVER_NAME = "acme-claims-knowledge"
SERVER_INSTRUCTIONS = (
    "Knowledge base of Acme Insurance (fictional P&C carrier): policy "
    "wordings, claims handling guidelines, partner contracts and storm "
    "(NatCat) playbooks. Use the search tool that matches the document "
    "type of the question, cite doc_id and title, quote the decisive "
    "sentence, and fetch the full document with get_knowledge_document "
    "before quoting at length."
)

DOC_TYPE_POLICY = "policy_wordings"
DOC_TYPE_GUIDELINES = "claims_guidelines"
DOC_TYPE_CONTRACTS = "partner_contracts"
DOC_TYPE_PLAYBOOKS = "storm_playbooks"

DEFAULT_TOP_K = 5
MAX_TOP_K = 20
MAX_QUERY_CHARS = 2000  # bge-small reads 512 tokens; the head carries the ask
HEALTH_TIMEOUT_S = 3  # preflight.sh / compose probe allow 5 s in total

# --- Clients -------------------------------------------------------------
# The Qdrant REST client is cheap to construct and does not connect
# until the first call. The embedding model is loaded LAZILY on the
# first search (spec 3.3): container start stays fast and /health is
# reachable while the ~67 MB model is still being read from the cache.
# check_compatibility=False: the client otherwise logs "client version
# X is incompatible with server version 1.15.4" whenever pip resolves a
# newer minor than the pinned server image (requirements.txt keeps the
# two adjacent; this switch keeps the log clean either way).
qdrant = QdrantClient(url=QDRANT_URL, timeout=30, check_compatibility=False)
# Separate short-timeout client for /health only: a down Qdrant must
# turn into "degraded" within the probe budget instead of blocking the
# probe for the 30 s search timeout.
qdrant_health = QdrantClient(
    url=QDRANT_URL, timeout=HEALTH_TIMEOUT_S, check_compatibility=False
)

_embedder: TextEmbedding | None = None
_embedder_lock = threading.Lock()


def _get_embedder() -> TextEmbedding:
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                log.info(
                    "loading embedding model %s (cache %s)",
                    EMBEDDING_MODEL,
                    MODEL_CACHE_DIR,
                )
                _embedder = TextEmbedding(
                    model_name=EMBEDDING_MODEL, cache_dir=MODEL_CACHE_DIR
                )
                log.info("embedding model ready")
    return _embedder


def _embed_query(text: str) -> list[float]:
    # embed() is a generator of numpy arrays; one query -> one vector.
    # bge-small needs no query/passage prefix, so embed() is used on
    # both the seed and the query side (identical vector space).
    vector = next(iter(_get_embedder().embed([text])))
    return vector.tolist()


def _transport_security():
    # The SDK auto-enables DNS-rebinding protection (allowed hosts
    # 127.0.0.1/localhost only) whenever the bind host is loopback and
    # answers 421 Misdirected Request to any other Host header -- SAM
    # pods send host.docker.internal:8765. Switch it off explicitly:
    # this is unauthenticated demo infrastructure on host ports.
    if TransportSecuritySettings is None:
        return None
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _hit(point: models.ScoredPoint) -> dict[str, Any]:
    payload = point.payload or {}
    return {
        "doc_id": payload.get("doc_id"),
        "title": payload.get("title"),
        "section": payload.get("section"),
        "score": round(float(point.score), 4),
        "text": payload.get("text"),
    }


# --- Blocking workers (run in a thread from the async tools) -----------
def _search_sync(doc_type: str, query: str, top_k: int) -> str:
    query = str(query or "").strip()
    if not query:
        return _dump(
            {
                "error": "empty query",
                "hint": "Describe the question in a few words, e.g. "
                "'slot not offered within five working days'.",
            }
        )
    if len(query) > MAX_QUERY_CHARS:
        # A pasted report as query only costs embedding time; the
        # model truncates at 512 tokens anyway.
        query = query[:MAX_QUERY_CHARS]
    # Clamp instead of reject: an LLM asking for top_k=50 gets 20 hits
    # and no wasted round trip (the SDK validates the type, not the
    # range -- see TopKArg).
    try:
        k = int(top_k) if top_k is not None else DEFAULT_TOP_K
    except (TypeError, ValueError):
        k = DEFAULT_TOP_K
    k = max(1, min(k, MAX_TOP_K))
    try:
        vector = _embed_query(query)
        result = qdrant.query_points(
            collection_name=COLLECTION,
            query=vector,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="doc_type", match=models.MatchValue(value=doc_type)
                    )
                ]
            ),
            limit=k,
            with_payload=True,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the LLM as data
        log.exception("search failed (%s, %r)", doc_type, query)
        return _dump(
            {
                "error": f"knowledge base unavailable: {exc}",
                "hint": "Is acme-knowledge-qdrant up and seeded, and the "
                "embedding model cached under FASTEMBED_CACHE_DIR? "
                "See sam-insurance-ops-demo/preflight.sh.",
            }
        )
    hits = [_hit(p) for p in result.points]
    if not hits:
        # Cosine search has no score cut-off, so an empty list means
        # the collection holds no document of this doc_type at all
        # (seed job not run) -- say so instead of returning "[]".
        log.warning("%s q=%r -> no documents (collection unseeded?)", doc_type, query)
        return _dump(
            {
                "results": [],
                "doc_type": doc_type,
                "hint": f"collection {COLLECTION} holds no {doc_type} "
                "documents; the one-shot seed job acme-knowledge-seed "
                "has probably not run -- see "
                "sam-insurance-ops-demo/preflight.sh (auto-fix reseeds).",
            }
        )
    log.info(
        "%s q=%r top_k=%d -> %s",
        doc_type,
        query,
        k,
        [h["doc_id"] for h in hits],
    )
    return _dump(hits)


def _get_document_sync(doc_id: str) -> str:
    # Tolerate quoted or lower-case ids ("pw-rn-3"): doc_ids are
    # upper-case in the corpus and the payload index matches exactly.
    doc_id = str(doc_id or "").strip().strip("\"'`").strip().upper()
    if not doc_id:
        return _dump({"error": "empty doc_id", "hint": "e.g. PW-RN-3"})
    try:
        records, _next = qdrant.scroll(
            collection_name=COLLECTION,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="doc_id", match=models.MatchValue(value=doc_id)
                    )
                ]
            ),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("get_knowledge_document failed (%s)", doc_id)
        return _dump({"error": f"knowledge base unavailable: {exc}"})
    if not records:
        return _dump(
            {
                "error": f"no document with doc_id {doc_id}",
                "hint": "doc_ids look like PW-HC-7, CG-FR-5, "
                "PC-DELLENDOC-2024, SP-NATCAT-4; use a search tool "
                "to find the id first.",
            }
        )
    payload = dict(records[0].payload or {})
    log.info("get_knowledge_document %s -> %s", doc_id, payload.get("title"))
    return _dump(
        {
            "doc_id": payload.get("doc_id"),
            "doc_type": payload.get("doc_type"),
            "title": payload.get("title"),
            "section": payload.get("section"),
            "effective_from": payload.get("effective_from"),
            "tags": payload.get("tags", []),
            "text": payload.get("text"),
        }
    )


def _health_sync() -> dict[str, Any]:
    info: dict[str, Any] = {
        "status": "ok",
        "service": SERVER_NAME,
        "mcp_path": MCP_PATH,
        "qdrant_url": QDRANT_URL,
        "collection": COLLECTION,
        "embedding_model": EMBEDDING_MODEL,
        "model_loaded": _embedder is not None,
    }
    try:
        info["points"] = qdrant_health.count(
            collection_name=COLLECTION, exact=True
        ).count
        info["qdrant"] = "ok"
    except Exception as exc:  # noqa: BLE001
        info["points"] = None
        info["qdrant"] = f"unreachable or collection missing: {exc}"
        info["status"] = "degraded"
    return info


# --- MCP server ----------------------------------------------------------
def _build_server():
    if _MCP_V2:
        # mcp 2.x: transport settings are passed to run() (see main()).
        return _ServerClass(name=SERVER_NAME, instructions=SERVER_INSTRUCTIONS)
    # mcp 1.x: transport settings live on the FastMCP constructor.
    return _ServerClass(
        name=SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        host=MCP_HOST,
        port=MCP_PORT,
        streamable_http_path=MCP_PATH,
        json_response=True,
        stateless_http=True,
        transport_security=_transport_security(),
    )


mcp = _build_server()

QueryArg = Annotated[
    str,
    Field(
        description="Natural-language question or key phrase; include "
        "clause ids, partner ids or domain words when known (e.g. "
        "'RN-3 no slot within five working days')."
    ),
]
# No ge/le on purpose: a range violation would be rejected by the SDK
# before the tool runs (one wasted LLM round trip); _search_sync clamps.
TopKArg = Annotated[
    int,
    Field(
        description="Number of documents to return, 1-20 (values outside "
        "are clamped). 3 for one precise clause, 5 default, 8-10 for a "
        "survey question."
    ),
]
DocIdArg = Annotated[
    str,
    Field(
        description="Exact document id from a search result, e.g. "
        "PW-RN-3, CG-BAFIN-30, PC-IC-2, SP-NATCAT-4 (case-insensitive)."
    ),
]


@mcp.tool()
async def search_policy_wordings(query: QueryArg, top_k: TopKArg = 5) -> str:
    """Semantic search over Acme POLICY WORDINGS (doc_type
    policy_wordings): what the CUSTOMER is entitled to under the
    motor and property policy conditions.

    Use this tool for questions about cover and clauses: hail cover
    HC-7, the deductible (once per event, glass without deductible via
    the partner network), the repair network steering clause RN-3 and
    its five-working-day slot rule, the total loss definition TL-1
    (70 percent of replacement value, or glass shattered + roof
    deformed + more than 150 dents), glass handling, replacement
    vehicle benefit, policyholder duties, exclusions and pre-existing
    damage, fleet policies, replacement value.

    Do NOT use it for how Acme processes a claim (use
    search_claims_guidelines), partner capacities and contract terms
    (search_partner_contracts) or storm planning
    (search_storm_playbooks).

    Returns a JSON list of {doc_id, title, section, score, text}
    sorted by cosine similarity (1.0 = identical). Cite doc_id and
    title and quote the decisive sentence.
    """
    return await anyio.to_thread.run_sync(
        _search_sync, DOC_TYPE_POLICY, query, top_k
    )


@mcp.tool()
async def search_claims_guidelines(query: QueryArg, top_k: TopKArg = 5) -> str:
    """Semantic search over Acme CLAIMS HANDLING GUIDELINES (doc_type
    claims_guidelines): how ACME processes a claim internally.

    Use this tool for questions about the claims process and its
    rules: Fast Lane criteria CG-FL-1 (MINOR, estimate below EUR 1,000,
    auto-confirm, drive-in slot, no adjuster), the Total Loss Fastlane
    CG-TL-2 (pick-up, remote valuation, 5 working days), the BaFin
    processing-time rule CG-BAFIN-30 (decision within 30 days, day-20
    escalation), the fraud indicators guideline CG-FR-5 (EXIF before
    the event, same VIN via two channels, estimates above contracted
    rates, identical line items, scanner mismatch; a single indicator
    proves nothing, a human decides), repeat contacts and complaints
    CG-CX-3, severity bands, the status model and the 4-hour stall
    threshold, reserves, holds, payment run rules, AI oversight,
    scanner results, estimate review, photo data protection.

    Do NOT use it for policy entitlements (search_policy_wordings),
    partner terms (search_partner_contracts) or storm planning
    (search_storm_playbooks).

    Returns a JSON list of {doc_id, title, section, score, text}.
    """
    return await anyio.to_thread.run_sync(
        _search_sync, DOC_TYPE_GUIDELINES, query, top_k
    )


@mcp.tool()
async def search_partner_contracts(query: QueryArg, top_k: TopKArg = 5) -> str:
    """Semantic search over Acme PARTNER CONTRACTS (doc_type
    partner_contracts): what a repair, assistance or rental PARTNER
    owes Acme and what Acme may activate.

    Use this tool for questions about a named partner or a contract
    lever: drive-in capacity and second-shift option (P-BRAENDLE, 120
    scans/day, +60 on 24 h notice, overflow clause), the INACTIVE
    fallback partner P-DELLENDOC (since 2026-01-01, unsigned
    parts-channel clause PC-4) and the interim contract template
    IC-2 (48 h activation under old terms for NatCat events), the
    assistance partner P-ROADASSIST (pick-up + remote valuation, 200
    vehicles/day), rental pre-booking with P-RENTAFLEET (24 h, up to
    150 cars), the rate card PC-RATES-2026 (hourly 118, paint 96 EUR,
    25 percent deviation review threshold), body shops incl.
    P-KAROSSERIE-SCHNELL (workshop W-0471), the Ludwigsburg drive-ins
    P-HAGELPOINT-LB and P-DELLENFIX-LB, network service levels, the
    mobile scanner unit framework.

    Contract figures are CONTRACTED values; the current load of a
    partner (assignments waiting) lives in the Acme Insurance DB, not
    here. Returns a JSON list of {doc_id, title, section, score, text}.
    """
    return await anyio.to_thread.run_sync(
        _search_sync, DOC_TYPE_CONTRACTS, query, top_k
    )


@mcp.tool()
async def search_storm_playbooks(query: QueryArg, top_k: TopKArg = 5) -> str:
    """Semantic search over Acme STORM (NatCat) PLAYBOOKS and event
    reviews (doc_type storm_playbooks): how to PLAN for a forecast hail
    cell and what earlier cells taught.

    Use this tool for readiness and capacity questions: the NatCat
    hail playbook SP-NATCAT-4 (planning conversion 30 percent of
    no-garage vehicles, property 18 percent of exposed buildings,
    options a-d: mobile scanner units from the Stuttgart hub with 90
    scans/day each and 24 h lead, rental pre-booking, warning SMS
    with human release, pre-staged Total Loss Fastlane, capacity
    math), lessons learned from HZ-0907 (conversion 0.28 on a 2 cm
    cell; 3 cm+ cells convert far higher) and the Reutlingen cell of
    2023 (3.5 cm, conversion 0.58, rental shortage), the warning SMS
    procedure, the capacity worksheet, readiness stages by lead time,
    first-contact triage, communications, post-event review.

    Do NOT use it for policy clauses, claims process rules or contract
    terms (use the other search tools). Returns a JSON list of
    {doc_id, title, section, score, text}.
    """
    return await anyio.to_thread.run_sync(
        _search_sync, DOC_TYPE_PLAYBOOKS, query, top_k
    )


@mcp.tool()
async def get_knowledge_document(doc_id: DocIdArg) -> str:
    """Fetch ONE knowledge document in full by its doc_id.

    Use this tool after a search hit to quote the decisive sentence
    completely and in context, when the user names a document id
    (e.g. "what does PC-IC-2 say?"), or to confirm effective_from and
    tags. Ids look like PW-HC-7 (policy wordings), CG-FR-5 (claims
    guidelines), PC-DELLENDOC-2024 (partner contracts),
    SP-NATCAT-4 (storm playbooks).

    Returns a JSON object {doc_id, doc_type, title, section,
    effective_from, tags, text} or {error, hint} when the id is
    unknown -- then use a search tool to find the right id.
    """
    return await anyio.to_thread.run_sync(_get_document_sync, doc_id)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    # Always HTTP 200 while the process is up (preflight.sh contract);
    # "status" is "degraded" and "qdrant" carries the reason when the
    # collection cannot be counted. Nothing here may raise -- an
    # exception would become a 500 and fail the probe.
    try:
        info = await anyio.to_thread.run_sync(_health_sync)
    except Exception as exc:  # noqa: BLE001 - last line of defence
        log.exception("/health failed")
        info = {
            "status": "degraded",
            "service": SERVER_NAME,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return JSONResponse(info)


def main() -> None:
    log.info(
        "Acme Claims Knowledge MCP server (mcp %s) on http://%s:%d%s "
        "-- qdrant %s, collection %s, model %s",
        "2.x" if _MCP_V2 else "1.x",
        MCP_HOST,
        MCP_PORT,
        MCP_PATH,
        QDRANT_URL,
        COLLECTION,
        EMBEDDING_MODEL,
    )
    # json_response + stateless_http: every request is self-contained
    # (plain JSON reply, no session bookkeeping), the most robust mode
    # for a gateway client that may reconnect after pod restarts.
    if _MCP_V2:
        mcp.run(
            transport="streamable-http",
            host=MCP_HOST,
            port=MCP_PORT,
            streamable_http_path=MCP_PATH,
            json_response=True,
            stateless_http=True,
            transport_security=_transport_security(),
        )
    else:
        mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
