"""gRPC ``de.showcase.loyalty.v1.service.LoyaltyService`` of gpos-loyalty (UC1-BUILD-SPEC 4.4).

Implemented in UC1: ``ResolveMembership``, ``GetMemberProfile``, ``GetPurchaseBehaviour``,
``ReportPurchase``, ``ChangeConsent``, ``ResetDemoState``. Every other RPC of the
service answers ``UNIMPLEMENTED`` (``grpcutil.serve``).

Messages come from the runtime Showcase pool (no generated code). Errors (4.1, 4.5):
``LOY-002`` -> ``NOT_FOUND`` with ``gpos-error-code``; a malformed request (also a
``ChangeConsent`` without flags) -> ``INVALID_ARGUMENT`` without a code. An unknown or
blocked card is no error here: the resolution carries status ``UNKNOWN`` / ``BLOCKED``
and the POS answers ``LOY-001``.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from decimal import Decimal
from typing import Any, NoReturn, TypeVar

import grpc
from google.protobuf import json_format
from google.protobuf.message import Message

from gposdemo.common import grpcutil
from gposdemo.common.clock import from_ts, offset_ts_json
from gposdemo.common.descriptors import Types
from gposdemo.common.money import from_money, to_bdecimal

from .service import (
    DEFAULT_ACTOR,
    LOY_UNKNOWN_MEMBER,
    ConsentChange,
    InvalidRequest,
    LoyaltyError,
    LoyaltyService,
    MemberProfile,
    PurchaseBehaviour,
    PurchaseReport,
    ReportLine,
    Resolution,
)

DATATYPE = "de.showcase.loyalty.v1.datatype"
EMPTY = "google.protobuf.Empty"
DROP_SCALE = 1
MONEY_SCALE = 2

_STATUS = {LOY_UNKNOWN_MEMBER: grpc.StatusCode.NOT_FOUND}

Ctx = grpc.ServicerContext
Handler = TypeVar("Handler", bound=Callable[..., Message])


def _abort(context: Ctx, err: LoyaltyError) -> NoReturn:
    if err.code:
        grpcutil.abort(context, _STATUS[err.code], err.code, err.text)
    context.abort(grpc.StatusCode.INVALID_ARGUMENT, err.text)


def _guarded(fn: Handler) -> Handler:
    """Map a refused request (:class:`LoyaltyError`) to its gRPC status."""

    @functools.wraps(fn)
    def wrapper(self: LoyaltyGrpc, request: Any, context: Ctx) -> Message:
        try:
            return fn(self, request, context)
        except LoyaltyError as err:
            _abort(context, err)

    return wrapper  # type: ignore[return-value]


def _transaction_type(purchase: Message) -> str:
    """``TRANSACTION_TYPE_SALE`` -> ``SALE`` (``UNSPECIFIED`` stays, the service refuses it)."""
    field = purchase.DESCRIPTOR.fields_by_name["transaction_type"]
    value = field.enum_type.values_by_number.get(purchase.transaction_type)
    return value.name.removeprefix("TRANSACTION_TYPE_") if value else ""


# --------------------------------------------------------------------------- requests
def report_from_message(purchase: Message) -> PurchaseReport:
    """``datatype.PurchaseSummary`` -> :class:`PurchaseReport`.

    proto3 cannot tell an unset ``effectual`` from ``false``: when no line sets it, the
    POS did not use the flag and sent only the non-voided lines (4.4), so all count.
    """
    flag_used = any(line.effectual for line in purchase.lines)
    lines = [ReportLine(position_id=line.position_id, article_number=line.article_number,
                        category=line.category, item_count=line.item_count,
                        value=from_money(line.effective_value),
                        effectual=line.effectual or not flag_used)
             for line in purchase.lines]
    return PurchaseReport(
        purchase_transaction_id=purchase.purchase_transaction_id,
        receipt_number=purchase.receipt_number, location=purchase.location,
        transaction_type=_transaction_type(purchase),
        closed_at=from_ts(purchase.closed_at) if purchase.HasField("closed_at") else None,
        membership_id=purchase.membership_id, lines=lines,
        total=from_money(purchase.total) if purchase.HasField("total") else Decimal("0.00"),
        referenced_purchase_transaction_id=purchase.referenced_purchase_transaction_id)


def consent_change_from_message(consent: Message) -> ConsentChange:
    """``datatype.ConsentFlags`` -> :class:`ConsentChange` (``changed_at`` is ours)."""
    return ConsentChange(offers=consent.offers, profiling=consent.profiling,
                         digital_receipt=consent.digital_receipt,
                         policy_version=consent.policy_version)


def _actor(command: Message) -> str:
    """Originator of a command header (``DEFAULT_ACTOR`` when empty), for the audit."""
    return command.header.originator.identity_id.strip() or DEFAULT_ACTOR


# --------------------------------------------------------------------------- responses
def resolution_json(r: Resolution) -> dict[str, Any]:
    """proto3 JSON of ``datatype.MembershipResolution``."""
    out: dict[str, Any] = {"membership_identification_value": r.card_value,
                           "verified": r.verified,
                           "status": f"MEMBERSHIP_STATUS_{r.status}"}
    if not r.verified:
        return out
    out.update({
        "membership_id": r.membership_id, "program_id": r.program_id,
        "program_name": r.program_name, "anonymous": r.anonymous,
        "accounts": [{"account_id": a.account_id, "account_type": a.account_type,
                      "account_currency_name": a.currency_name,
                      "account_balance": to_bdecimal(a.balance, MONEY_SCALE)}
                     for a in r.accounts],
        "membership_preferences": [{"key": "digitalReceipt",
                                    "typed_value": {"bool_value": r.digital_receipt}}],
    })
    if r.customer_id:
        out["customer_id"] = r.customer_id
    return out


def profile_json(p: MemberProfile) -> dict[str, Any]:
    """proto3 JSON of ``datatype.MemberProfile``."""
    consent: dict[str, Any] = {"offers": p.consent.offers, "profiling": p.consent.profiling,
                               "digital_receipt": p.consent.digital_receipt,
                               "policy_version": p.consent.policy_version}
    if p.consent.changed_at is not None:
        consent["changed_at"] = offset_ts_json(p.consent.changed_at)
    return {"membership_id": p.membership_id, "persona_label": p.persona_label,
            "salutation": f"SALUTATION_{p.salutation}", "preference_tags": list(p.tags),
            "consent": consent, "points_balance": to_bdecimal(p.points_balance, MONEY_SCALE),
            "history": [{"category": c.category, "purchases_8w": c.purchases_8w,
                         "days_since_last": c.days_since_last} for c in p.history],
            "open_coupons": p.open_coupons, "history_used": p.history_used,
            "segment_label": p.segment_label}


def behaviour_json(b: PurchaseBehaviour) -> dict[str, Any]:
    """proto3 JSON of ``datatype.PurchaseBehaviour`` (drop with scale 1, e.g. 46.7)."""
    return {"membership_id": b.membership_id, "article_number": b.article_number,
            "consent_profiling": b.consent_profiling, "persona_label": b.persona_label,
            "segment_label": b.segment_label, "member_purchases_8w": b.member_purchases_8w,
            "member_purchases_12w": b.member_purchases_12w,
            "days_since_last": b.days_since_last,
            "median_interval_days": b.median_interval_days,
            "cardholder_weekly": list(b.cardholder_weekly),
            "cardholder_drop_pct": to_bdecimal(b.cardholder_drop_pct, DROP_SCALE)}


class LoyaltyGrpc:
    """``impl`` of 2.4: one method per implemented RPC, named like the RPC."""

    def __init__(self, service: LoyaltyService, types: Types):
        self.service = service
        self.types = types

    def _message(self, type_name: str, body: dict[str, Any]) -> Message:
        msg = self.types.new(f"{DATATYPE}.{type_name}")
        return json_format.ParseDict(body, msg, descriptor_pool=self.types.pool)

    def _empty(self) -> Message:
        return self.types.new(EMPTY)

    @_guarded
    def ResolveMembership(self, request: Any, context: Ctx) -> Message:  # noqa: N802
        resolution = self.service.resolve_membership(request.membership_identification_value)
        return self._message("MembershipResolution", resolution_json(resolution))

    @_guarded
    def GetMemberProfile(self, request: Any, context: Ctx) -> Message:  # noqa: N802
        profile = self.service.member_profile(request.membership_id)
        return self._message("MemberProfile", profile_json(profile))

    @_guarded
    def GetPurchaseBehaviour(self, request: Any, context: Ctx) -> Message:  # noqa: N802
        result = self.service.purchase_behaviour(request.membership_id, request.article_number)
        return self._message("PurchaseBehaviour", behaviour_json(result))

    @_guarded
    def ReportPurchase(self, request: Any, context: Ctx) -> Message:  # noqa: N802
        self.service.report_purchase(report_from_message(request.purchase))
        return self._empty()

    @_guarded
    def ChangeConsent(self, request: Any, context: Ctx) -> Message:  # noqa: N802
        if not request.HasField("consent"):  # proto3 default would revoke every consent
            raise InvalidRequest("consent fehlt")
        self.service.change_consent(request.membership_id,
                                    consent_change_from_message(request.consent),
                                    _actor(request))
        return self._empty()

    @_guarded
    def ResetDemoState(self, request: Any, context: Ctx) -> Message:  # noqa: N802
        self.service.reset_demo_state(request.visit_id, request.full_day_reset,
                                      _actor(request))
        return self._empty()
