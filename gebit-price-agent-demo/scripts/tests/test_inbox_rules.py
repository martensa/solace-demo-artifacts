"""Inbox watcher rules (spec 12.6, 1.5) and inbox item parsing (A-6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opslib import (Decision, InboxItem, OpsError, decide, exclusive_lock, is_gpos, parse_item,
                    with_ref)

GP = "GP-270216-0003"


def item(item_id: str, created: str, ref: str | None = GP, agent: str | None = None
         ) -> InboxItem:
    return InboxItem(item_id, created, "pending", ref, agent)


def raw_hil(item_id: str, message: str, info: str) -> dict:
    return {"id": item_id, "createdAt": "2027-02-16T10:00:01Z", "promptState": "pending",
            "category": "hil", "body": message,
            "surface": {"components": [{"id": "info", "text": {"literalString": info}}]}}


def test_parse_item_finds_ref_and_agent() -> None:
    parsed = parse_item(raw_hil(
        "n1", "Preisänderung GEBIT Ente: 9,99 € auf 7,99 € (-20 %), Anlass Ladenhüter, "
              f"gültig bis Di 23.02. 20:00. Ref {GP}. Freigeben?",
        'Agent "gpos-price-approver" wants to run tool apply_price'))
    assert (parsed.id, parsed.ref, parsed.agent, parsed.prompt_state) == (
        "n1", GP, "gpos-price-approver", "pending")
    assert is_gpos(parsed)


def test_parse_item_fallback_and_foreign() -> None:
    f2 = parse_item(raw_hil("n2", "Preisvorschlag der Messekasse freigeben?",
                            'Agent "gpos-price-approver-f2" wants to run tool get_current_time'))
    assert (f2.ref, f2.agent) == (None, "gpos-price-approver-f2") and is_gpos(f2)
    foreign = parse_item(raw_hil("n3", "Spike G0-09 B1h: GEBIT Ente freigeben?",
                                 'Agent "gpos-spike-p09-approver-h" wants to run tool x'))
    assert not is_gpos(foreign)


def test_first_request_of_a_pending_proposal_stays() -> None:
    first_by_ref: dict[str, str] = {}
    pending = [item("a", "2027-02-16T10:00:01Z"), item("b", "2027-02-16T10:00:03Z")]
    decisions = decide(pending, {GP: {"proposal_id": GP, "state": "pending"}}, first_by_ref)
    assert [(d.item_id, d.action) for d in decisions] == [("a", "keep"), ("b", "cancel")]
    assert first_by_ref == {GP: "a"}
    # the first one stays the first, even when it is listed after a newer one
    again = decide([pending[1], pending[0]], {GP: {"state": "pending"}}, first_by_ref)
    assert {(d.item_id, d.action) for d in again} == {("a", "keep"), ("b", "cancel")}


def test_duplicate_after_approval_is_approved() -> None:
    decisions = decide([item("c", "2027-02-16T10:01:00Z")], {GP: {"state": "approved"}}, {})
    assert decisions == [Decision("c", GP, "approve",
                                  "duplicate request, price already active")]


@pytest.mark.parametrize("state", ["superseded", "expired", "failed", "rejected", "blocked"])
def test_requests_of_ended_proposals_are_cancelled(state: str) -> None:
    decisions = decide([item("d", "x")], {GP: {"state": state}}, {})
    assert [(d.action, d.reason) for d in decisions] == [("cancel", f"proposal {state}")]


def test_unknown_and_unreadable_proposals() -> None:
    assert [d.action for d in decide([item("e", "x")], {GP: None}, {})] == ["cancel"]
    assert decide([item("f", "x")], {}, {}) == []          # not readable: next round
    assert decide([item("g", "x", ref=None)], {GP: {"state": "pending"}}, {}) == []


def test_with_ref_fills_only_missing_refs() -> None:
    items = [item("h", "x", ref=None, agent="gpos-price-approver"), item("i", "x", ref="GP-1")]
    assert [i.ref for i in with_ref(items, GP)] == [GP, "GP-1"]
    assert with_ref(items, None) == items


def test_lock_keeps_watch_and_e2e_apart(tmp_path: Path) -> None:
    lock = tmp_path / "sam_inbox.lock"
    with exclusive_lock("sam_inbox.py watch", lock):
        with pytest.raises(OpsError, match="sam_inbox.py watch"):
            with exclusive_lock("e2e.py", lock):
                pass
    with exclusive_lock("e2e.py", lock):
        assert "e2e.py" in lock.read_text()
