"""``apply_price``: the only price-changing tool of the demo (UC1-BUILD-SPEC 8.3, 11.4).

One DB transaction with ``select … for update`` on proposal and approval:

1. ``apply_calls += 1``, ``first_apply_at`` set once;
2. unknown -> ``unknown``; ``superseded`` -> ``superseded``; ``expired`` -> ``expired``;
3. already ``approved`` with a price change -> ``already_applied`` (same ``action_id``),
   signal ``proposal/duplicate_request``;
4. status not ``pending`` -> ``blocked`` (also ``failed`` after an R4 error: an orphaned
   approval after an awe restart, G0-02 T9);
5. ``proposal_hash`` differs -> ``blocked``;
6. ``run_id`` given and not the approval run -> ``blocked``;
7. any number or label of the approval card differs from the stored proposal -> ``blocked``;
8. ``GATE_GUARD``: a call earlier than ``GATE_MIN_DELAY_S`` after ``checked_at`` is
   blocked (``block``), applied with a warning (``warn``), or additionally needs a
   valid ``approved_at`` (``f2``);
9. WWS ``RequestPriceChange``; a gRPC error -> ``blocked``, the proposal stays pending;
10. ``engine.price_change``, proposal ``approved``, event ``proposal/approved``.

The gate never sets ``rejected``/``expired``: that is ``record_outcome`` or the watchdog.
"""

from __future__ import annotations

import logging
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import grpc

from ...common.config import Settings
from ...common.db import Db
from ...common.fmt import eur, parse_price
from ...common.grpcutil import error_code
from .. import store
from ..clients import PriceChangeRequest, WwsClient
from ..models import ApplyResult
from ..records import ProposalRecord
from ..state import Emitter
from ..texts import de_num

log = logging.getLogger(__name__)

F2_FUTURE_TOLERANCE_S = 2.0
MSG_UNKNOWN = "Vorschlag unbekannt"
MSG_SUPERSEDED = "Vorschlag wurde zurückgesetzt"
MSG_EXPIRED = "Vorschlag ist abgelaufen"
MSG_ALREADY = "Preis ist bereits aktiv"
MSG_HASH = "Hash passt nicht"
MSG_FOREIGN_RUN = "Fremder Lauf"
MSG_CARD = "Freigabetext weicht ab"
MSG_TOO_FAST = "Freigabe schneller als möglich – Gate prüfen"
MSG_F2_TIME = "Freigabezeit fehlt oder passt nicht – Gate prüfen"
REASON_WARN = "Gate prüfen"


@dataclass(frozen=True)
class ApplyArgs:
    """Arguments of one ``apply_price`` call (as the approver copied them)."""

    proposal_id: str
    proposal_hash: str
    article_name: str
    old_price: str
    new_price: str
    pct_label: str
    reason_label: str
    valid_to_label: str
    run_id: str = ""
    approved_at: str = ""


@dataclass(frozen=True)
class Guard:
    action: str   # apply | warn | block
    message: str = ""


def _same_text(given: str, stored: str) -> bool:
    return unicodedata.normalize("NFC", given.strip()) == unicodedata.normalize("NFC", stored)


def _same_price(given: str, stored: Any) -> bool:
    try:
        return parse_price(given) == stored
    except ValueError:
        return False


def card_mismatch(p: ProposalRecord, args: ApplyArgs, zone: ZoneInfo) -> str:
    """Step 7: the first field of the approval card that differs from the proposal."""
    checks = (("old_price", _same_price(args.old_price, p.regular_price)),
              ("new_price", _same_price(args.new_price, p.new_price)),
              ("article_name", _same_text(args.article_name, p.article_name)),
              ("pct_label", _same_text(args.pct_label, p.pct_label_ascii)),
              ("reason_label", _same_text(args.reason_label, p.reason_label)),
              ("valid_to_label", _same_text(args.valid_to_label, p.valid_to_label(zone))))
    return next((name for name, ok in checks if not ok), "")


def _parse_aware(text: str) -> datetime | None:
    try:
        value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo is not None else None


def guard(mode: str, checked_at: datetime, now: datetime, min_delay_s: float,
          approved_at: str) -> Guard:
    """Step 8 (``GATE_GUARD`` ``block``|``warn``|``f2``)."""
    elapsed = (now - checked_at).total_seconds()
    early = elapsed < min_delay_s
    if mode == "warn":
        if early:
            shown = de_num(Decimal(str(round(elapsed, 1))))
            return Guard("warn", f"Gate prüfen: Aufruf nach {shown} s")
        return Guard("apply")
    if early:
        return Guard("block", MSG_TOO_FAST)
    if mode == "f2":
        at = _parse_aware(approved_at)
        earliest = checked_at + timedelta(seconds=min_delay_s)
        latest = now + timedelta(seconds=F2_FUTURE_TOLERANCE_S)
        if at is None or not earliest <= at <= latest:
            return Guard("block", MSG_F2_TIME)
    return Guard("apply")


class GateService:
    """Business method of ``gpos-gate``."""

    def __init__(self, settings: Settings, db: Db, wws: WwsClient, emitter: Emitter,
                 clock: Callable[[], datetime]):
        self.settings = settings
        self.db = db
        self.wws = wws
        self.emitter = emitter
        self.clock = clock

    def apply_price(self, proposal_id: str, proposal_hash: str, article_name: str,
                    old_price: str, new_price: str, pct_label: str, reason_label: str,
                    valid_to_label: str, run_id: str = "", approved_at: str = "") -> ApplyResult:
        args = ApplyArgs(proposal_id, proposal_hash, article_name, old_price, new_price,
                         pct_label, reason_label, valid_to_label, run_id, approved_at)
        with self.db.tx() as conn:
            p = store.proposal(conn, proposal_id, lock=True)
            approval = store.approval(conn, proposal_id, lock=True)
            now = self.clock()
            if approval is not None:
                conn.execute("update engine.approval set apply_calls = apply_calls + 1, "
                             "first_apply_at = coalesce(first_apply_at, %s) "
                             "where proposal_id = %s", (now, proposal_id))
            result, error = self._decide(conn, p, approval, args, now)
            if approval is not None:
                changes: dict[str, Any] = {"last_apply_status": result.status}
                if error:
                    changes["error"] = error
                store.set_approval(conn, proposal_id, **changes)
        log.info("apply_price %s: %s %s", proposal_id, result.status, result.message)
        return result

    def _decide(self, conn: store.Conn, p: ProposalRecord | None,
                approval: dict[str, Any] | None, args: ApplyArgs,
                now: datetime) -> tuple[ApplyResult, str]:
        """The result and the text for ``approval.error`` (``""``: none)."""
        pid = args.proposal_id
        if p is None:
            return ApplyResult(status="unknown", proposal_id=pid, message=MSG_UNKNOWN), ""
        if p.status in ("superseded", "expired"):
            message = MSG_SUPERSEDED if p.status == "superseded" else MSG_EXPIRED
            return ApplyResult(status=p.status, proposal_id=pid, message=message), ""
        change = store.price_change(conn, pid)
        if p.status == "approved" and change is not None:
            self.emitter.proposal_state(conn, p, args.run_id, state="duplicate_request",
                                        action_id=change["action_id"])
            return ApplyResult(status="already_applied", proposal_id=pid,
                               action_id=change["action_id"], new_price=p.new_label,
                               message=MSG_ALREADY), ""
        refusal = self._refusal(p, approval, args, now)
        if refusal.action == "block":
            return self._blocked(pid, refusal.message)
        assert approval is not None
        try:
            action_id, created = self.wws.request_price_change(PriceChangeRequest(
                proposal_id=pid, article_number=p.article_number, store_id=p.store_id,
                expected_regular_price=p.regular_price, new_price=p.new_price,
                pct_shown=p.pct_shown, ref30=p.ref30, valid_from=p.valid_from,
                valid_to=p.valid_to, reason=p.reason))
        except grpc.RpcError as err:
            code = error_code(err) or (err.code().name if isinstance(err, grpc.Call) else "")
            log.warning("apply_price %s: RequestPriceChange failed: %s", pid, err)
            return self._blocked(pid, f"Warenwirtschaft lehnt ab ({code or 'Fehler'})")
        conn.execute(
            "insert into engine.price_change (action_id, proposal_id, article_number, "
            "store_id, old_price, new_price, ref30, valid_to, run_id, applied_at) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (action_id, pid, p.article_number, p.store_id, p.regular_price, p.new_price,
             p.ref30, p.valid_to, args.run_id or None, now))
        approved = store.set_proposal(conn, pid, status="approved", decided_at=now,
                                      status_reason=REASON_WARN if refusal.message else None)
        self.emitter.proposal_state(conn, approved, args.run_id, action_id=action_id)
        log.info("apply_price %s: action %s (created=%s)", pid, action_id, created)
        return (ApplyResult(status="applied", proposal_id=pid, action_id=action_id,
                            new_price=p.new_label,
                            message=f"Neuer Preis {eur(p.new_price)} € aktiv"),
                refusal.message)

    def _refusal(self, p: ProposalRecord, approval: dict[str, Any] | None, args: ApplyArgs,
                 now: datetime) -> Guard:
        """Steps 4 to 8: ``block`` with the reason, ``warn`` or ``apply``."""
        if p.status != "pending" or approval is None:
            return Guard("block", f"Vorschlag ist nicht freigabebereit ({p.status})")
        if args.proposal_hash.strip() != p.proposal_hash:
            return Guard("block", MSG_HASH)
        if args.run_id and args.run_id != approval["run_id"]:
            return Guard("block", MSG_FOREIGN_RUN)
        field = card_mismatch(p, args, self.emitter.zone)
        if field:
            # The German text of 11.4 step 7 is what the notification shows (11.6); the
            # differing field is for the operator log only.
            log.warning("apply_price %s: approval card differs in %s", p.proposal_id, field)
            return Guard("block", MSG_CARD)
        return guard(self.settings.gate_guard, approval["checked_at"], now,
                     self.settings.gate_min_delay_s, args.approved_at)

    def _blocked(self, proposal_id: str, message: str) -> tuple[ApplyResult, str]:
        return ApplyResult(status="blocked", proposal_id=proposal_id, message=message), message
