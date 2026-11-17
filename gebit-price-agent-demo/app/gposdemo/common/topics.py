"""Every topic string of UC1-BUILD-SPEC 7.1 comes from here.

Levels are validated: no empty level, no ``/`` inside a level and no wildcard
character in a published topic. ``{store}`` is ``101`` (booth) or ``199`` (probe and
test), ``{till}`` ``01`` (booth), ``98`` (probe) or ``99`` (test).
"""

from __future__ import annotations

GEBIT_ROOT = "gebit/rp/purchase/v2"
WWS_PRICE_ROOT = "showcase/wws/v1/price"
GPOS_ROOT = "gpos/v1"

GEBIT_CATEGORIES = (
    "purchase_transaction", "basket", "fiscal_transaction", "payment_session",
    "financial_transaction", "loyalty",
)
WWS_PRICE_EVENTS = ("PriceChangeApplied", "PriceChangeEnded")
REVIEW_STATES = (
    "requested", "prepared", "proposed", "no_action", "no_candidates", "only_blocked",
    "deferred", "blocked", "failed", "superseded",
)
PROPOSAL_STATES = (
    "ready", "pending", "approved", "rejected", "expired", "failed", "superseded", "blocked",
)
PROPOSAL_SIGNALS = ("duplicate_request",)
SAM_RULES = ("r1", "r3", "r4", "p1", "p3", "p4")

# Subscription filters of gpos-ui (all topics of 7.1, Direct).
ALL_GEBIT = f"{GEBIT_ROOT}/>"
ALL_WWS_PRICE = f"{WWS_PRICE_ROOT}/>"
ALL_GPOS = f"{GPOS_ROOT}/>"
UI_SUBSCRIPTIONS = (ALL_GEBIT, ALL_WWS_PRICE, ALL_GPOS)


def _level(name: str, value: str) -> str:
    value = str(value)
    if not value or "/" in value or "*" in value or ">" in value or value != value.strip():
        raise ValueError(f"invalid topic level {name}={value!r}")
    return value


def _one_of(name: str, value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ValueError(f"{name} must be one of {allowed}, got {value!r}")
    return value


def parse_location(location: str) -> tuple[str, str, str, str]:
    """``"Root.DE.999.101.01"`` -> ``("DE", "999", "101", "01")`` (country..till)."""
    parts = location.split(".")
    if len(parts) != 5 or parts[0] != "Root":
        raise ValueError(f"location must look like Root.DE.999.101.01, got {location!r}")
    country, company, store, till = (_level("location", p) for p in parts[1:])
    return country, company, store, till


def gebit_event(category: str, event: str, country: str, company: str, store: str,
                till: str, tx_id: str) -> str:
    """``gebit/rp/purchase/v2/{category}/{Event}/{country}/{company}/{store}/{till}/{txId}``"""
    levels = [_one_of("category", category, GEBIT_CATEGORIES), _level("event", event),
              _level("country", country), _level("company", company), _level("store", store),
              _level("till", till), _level("tx_id", tx_id)]
    return "/".join([GEBIT_ROOT, *levels])


def wws_price(event: str, country: str, company: str, store: str, article_number: str) -> str:
    """``showcase/wws/v1/price/{Event}/{country}/{company}/{store}/{articleNumber}``"""
    levels = [_one_of("event", event, WWS_PRICE_EVENTS), _level("country", country),
              _level("company", company), _level("store", store),
              _level("article_number", article_number)]
    return "/".join([WWS_PRICE_ROOT, *levels])


def insight(store: str, till: str, tx_id: str) -> str:
    """``gpos/v1/insight/scan/{store}/{till}/{txId}``"""
    return "/".join([GPOS_ROOT, "insight", "scan", _level("store", store), _level("till", till),
                     _level("tx_id", tx_id)])


def review_request(store: str, till: str, review_id: str) -> str:
    """``gpos/v1/review/request/{store}/{till}/{reviewId}`` (SAM input R3)."""
    return "/".join([GPOS_ROOT, "review", "request", _level("store", store),
                     _level("till", till), _level("review_id", review_id)])


def review_request_filter(store: str, till: str) -> str:
    """``gpos/v1/review/request/{store}/{till}/>`` (subscription of R3 / p3)."""
    return "/".join([GPOS_ROOT, "review", "request", _level("store", store),
                     _level("till", till), ">"])


def review_state(state: str, store: str, till: str, review_id: str) -> str:
    """``gpos/v1/review/state/{state}/{store}/{till}/{reviewId}``"""
    return "/".join([GPOS_ROOT, "review", "state", _one_of("state", state, REVIEW_STATES),
                     _level("store", store), _level("till", till),
                     _level("review_id", review_id)])


def proposal(state: str, store: str, till: str, proposal_id: str) -> str:
    """``gpos/v1/proposal/{state}/{store}/{till}/{proposalId}`` (states and the signal
    ``duplicate_request``)."""
    allowed = PROPOSAL_STATES + PROPOSAL_SIGNALS
    return "/".join([GPOS_ROOT, "proposal", _one_of("state", state, allowed),
                     _level("store", store), _level("till", till),
                     _level("proposal_id", proposal_id)])


def approval_request(store: str, till: str, proposal_id: str) -> str:
    """``gpos/v1/approval/request/{store}/{till}/{proposalId}`` (SAM input R4)."""
    return "/".join([GPOS_ROOT, "approval", "request", _level("store", store),
                     _level("till", till), _level("proposal_id", proposal_id)])


def approval_request_filter(store: str, till: str) -> str:
    """``gpos/v1/approval/request/{store}/{till}/>`` (subscription of R4 / p4)."""
    return "/".join([GPOS_ROOT, "approval", "request", _level("store", store),
                     _level("till", till), ">"])


def telemetry_tool(service: str, tool: str) -> str:
    """``gpos/v1/telemetry/tool/{service}/{tool}``"""
    return "/".join([GPOS_ROOT, "telemetry", "tool", _level("service", service),
                     _level("tool", tool)])


def sam_done(rule: str) -> str:
    """``gpos/v1/sam/done/{rule}`` (SAM ``successOutput``)."""
    return "/".join([GPOS_ROOT, "sam", "done", _one_of("rule", rule, SAM_RULES)])


def sam_error(rule: str) -> str:
    """``gpos/v1/sam/error/{rule}`` (SAM ``errorOutput``)."""
    return "/".join([GPOS_ROOT, "sam", "error", _one_of("rule", rule, SAM_RULES)])

