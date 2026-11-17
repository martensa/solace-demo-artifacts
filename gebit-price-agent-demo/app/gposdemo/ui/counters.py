"""Booth counters of the monitor footer (UC1-BUILD-SPEC 10.2).

Since the last reset, only store/till of the booth (101/01), probe rules ``p*`` never:

* ``pos_events``: every GEBIT event of the booth till
* ``sam_runs``: ``done`` + ``error`` of ``r1``/``r3``/``r4`` (also per rule)
* ``agent_runs`` (also per model alias in ``agent_runs_by_model``, model rule of
  :func:`~gposdemo.ui.texts.model_of`: missing or unknown = ``fast``):

  - evidence run: a review event with an ``evidence`` object, once per review, as
    ``evidence.model`` (the pricing agent, ``fast``, gathered the evidence);
  - recommendation run: a review ``proposed``/``no_action``/``blocked`` with a
    ``decision`` object, once per review, as ``decision.model`` (``planning``; a
    legacy review without model counts once as ``fast``);
  - approver run: the proposal outcomes ``approved``/``rejected``/``expired``/
    ``blocked``, once per proposal, as ``fast`` (``approved`` arrives from the gate and
    again from ``record_outcome``).

  ``failed``, ``superseded`` and reviews without AI count nothing; S1 gives 3 runs
  (fast 2, planning 1).
* ``agent_tool_calls``: ``tool_call`` with ``caller`` ``agent`` on one of the three API
  families ``pos``/``wws``/``loyalty`` (10.4); the approver's gated ``apply_price`` (also
  ``caller`` ``agent``, 8.3) is no API query: S1 gives the 2 of 1.4. Refs known to belong
  to another till are left out.
* ``approvals`` / ``rejections``: proposals ``approved`` / ``rejected``, once each
* ``price_changes``: ``PriceChangeApplied`` of the booth store
"""

from __future__ import annotations

import threading
from typing import Any

from .texts import API_FAMILIES, MODELS, counters_line, model_of

BOOTH_RULES = ("r1", "r3", "r4")
API_SERVICES = tuple(API_FAMILIES)  # pos, wws, loyalty
RECOMMENDATION_STATES = ("proposed", "no_action", "blocked")
APPROVER_OUTCOMES = ("approved", "rejected", "expired", "blocked")
FIELDS = ("pos_events", "sam_runs", "agent_runs", "agent_tool_calls", "approvals",
          "rejections", "price_changes")


class Counters:
    """Thread-safe counters; ``version`` grows with every change (for throttling)."""

    def __init__(self, booth_store: str, booth_till: str):
        self.booth = (booth_store, booth_till)
        self._lock = threading.Lock()
        self.version = 0
        self._reset_locked()

    def _reset_locked(self) -> None:
        self._values = dict.fromkeys(FIELDS, 0)
        self._by_rule = dict.fromkeys(BOOTH_RULES, 0)
        self._by_model = dict.fromkeys(MODELS, 0)
        self._counted: set[tuple[str, str]] = set()
        self._foreign_refs: set[str] = set()

    def reset(self) -> None:
        """Back to zero (step 5 of the reset chain)."""
        with self._lock:
            self._reset_locked()
            self.version += 1

    def _is_booth(self, data: dict[str, Any]) -> bool:
        return (str(data.get("store", "")), str(data.get("till", ""))) == self.booth

    def _remember_foreign(self, data: dict[str, Any]) -> None:
        for key in ("tx_id", "review_id", "proposal_id"):
            if data.get(key):
                self._foreign_refs.add(str(data[key]))

    def _once(self, kind: str, key: str) -> bool:
        if (kind, key) in self._counted:
            return False
        self._counted.add((kind, key))
        return True

    def _add(self, field: str) -> bool:
        self._values[field] += 1
        return True

    def _add_run(self, model: Any) -> bool:
        """One agent run, also under its model alias (model rule)."""
        self._by_model[model_of(model)] += 1
        return self._add("agent_runs")

    def _on_review(self, data: dict[str, Any]) -> bool:
        rid = str(data.get("review_id"))
        changed = False
        evidence = data.get("evidence")
        if isinstance(evidence, dict) and self._once("evidence", rid):
            changed = self._add_run(evidence.get("model"))
        decision = data.get("decision")
        if (data.get("state") in RECOMMENDATION_STATES and isinstance(decision, dict)
                and self._once("review", rid)):
            changed = self._add_run(decision.get("model"))
        return changed

    def _on_proposal(self, data: dict[str, Any]) -> bool:
        state, pid = data.get("state"), str(data.get("proposal_id"))
        if data.get("signal") or state not in APPROVER_OUTCOMES or not self._once("outcome", pid):
            return False
        self._add_run("fast")
        if state == "approved":
            self._add("approvals")
        elif state == "rejected":
            self._add("rejections")
        return True

    def _on_sam_run(self, data: dict[str, Any]) -> bool:
        rule = data.get("rule")
        if rule not in BOOTH_RULES:
            return False
        self._by_rule[rule] += 1
        return self._add("sam_runs")

    def _apply(self, kind: str, data: dict[str, Any]) -> bool:
        if kind == "sam_run":
            return self._on_sam_run(data)
        if kind == "tool_call":
            return (data.get("caller") == "agent" and data.get("service") in API_SERVICES
                    and str(data.get("ref", "")) not in self._foreign_refs
                    and self._add("agent_tool_calls"))
        if kind == "price_change":
            return (data.get("event") == "PriceChangeApplied"
                    and str(data.get("store", "")) == self.booth[0]
                    and self._add("price_changes"))
        if kind not in ("pos_event", "review", "proposal"):
            return False
        if not self._is_booth(data):
            self._remember_foreign(data)
            return False
        if kind == "pos_event":
            return self._add("pos_events")
        return self._on_review(data) if kind == "review" else self._on_proposal(data)

    def on_event(self, kind: str, data: dict[str, Any]) -> bool:
        """Count one SSE event; True when a counter changed."""
        with self._lock:
            changed = self._apply(kind, data)
            if changed:
                self.version += 1
            return changed

    def to_dict(self) -> dict[str, Any]:
        """The ``counters`` SSE payload, with ``agent_runs_by_model`` and the footer
        ``line`` of 10.2."""
        with self._lock:
            values: dict[str, Any] = dict(self._values)
            values["sam_runs_by_rule"] = dict(self._by_rule)
            values["agent_runs_by_model"] = dict(self._by_model)
        values["line"] = counters_line(values)
        return values
