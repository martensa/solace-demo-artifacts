"""The engine's single parameter set ``policy/pricing-policy.yaml`` (UC1-BUILD-SPEC 6.6).

Numbers are read as ``Decimal(str(x))`` (never computed as ``float``). Only what the
engine uses is kept; a missing key raises ``PolicyError`` naming it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

REASONS = ("slow_seller", "season_end", "customer_behaviour")


class PolicyError(ValueError):
    """The policy file is missing a key or has an invalid value."""


@dataclass(frozen=True)
class SlowSellerRule:
    max_sell_through: Decimal
    min_weeks_of_supply: Decimal
    min_listed_days: int
    strong_sell_through: Decimal


@dataclass(frozen=True)
class SeasonEndRule:
    window_days: int
    min_leftover_share: Decimal


@dataclass(frozen=True)
class CustomerBehaviourRule:
    min_member_buys_8w: int
    min_overdue_factor: Decimal
    min_cardholder_drop_pct: Decimal
    min_prior_weekly: Decimal


@dataclass(frozen=True)
class SuggestedSteps:
    slow_seller_strong: int
    slow_seller_default: int
    season_end_ended: int
    season_end_within_7_days: int
    season_end_default: int
    customer_behaviour: int


@dataclass(frozen=True)
class Guardrails:
    steps_pct: tuple[int, ...]
    min_margin_pct: Decimal
    price_endings_cents: tuple[int, ...]
    action_days: int
    action_end_time: time


@dataclass(frozen=True)
class TextLimits:
    headline_max: int
    rationale_max: int
    facts_line_max: int


@dataclass(frozen=True)
class ReviewLimits:
    max_candidates_in_agent_input: int
    max_blocked_in_agent_input: int
    max_no_action_names: int
    agent_input_max_bytes: int
    facts_short_chars: int


@dataclass(frozen=True)
class Policy:
    version: str
    slow_seller: SlowSellerRule
    season_end: SeasonEndRule
    customer_behaviour: CustomerBehaviourRule
    on_plan_min_sell_through: Decimal
    steps: SuggestedSteps
    reason_priority: tuple[str, ...]
    guardrails: Guardrails
    texts: TextLimits
    review: ReviewLimits

    def priority(self, reason: str) -> int:
        """Rank of ``reason`` in ``reason_priority`` (0 = first)."""
        return self.reason_priority.index(reason)


def _get(obj: Mapping[str, Any], path: str) -> Any:
    value: Any = obj
    for key in path.split("."):
        if not isinstance(value, Mapping) or key not in value:
            raise PolicyError(f"policy: missing key {path!r}")
        value = value[key]
    return value


def _dec(obj: Mapping[str, Any], path: str) -> Decimal:
    value = _get(obj, path)
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise PolicyError(f"policy: {path} must be a number, got {value!r}")
    return Decimal(str(value))


def _int(obj: Mapping[str, Any], path: str) -> int:
    value = _get(obj, path)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PolicyError(f"policy: {path} must be an integer, got {value!r}")
    return value


def _ints(obj: Mapping[str, Any], path: str) -> tuple[int, ...]:
    value = _get(obj, path)
    if not isinstance(value, list) or not all(isinstance(v, int) for v in value):
        raise PolicyError(f"policy: {path} must be a list of integers")
    return tuple(value)


def _clock(obj: Mapping[str, Any], path: str) -> time:
    value = str(_get(obj, path))
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise PolicyError(f"policy: {path} must be HH:MM, got {value!r}") from exc


def parse_policy(raw: Mapping[str, Any]) -> Policy:
    """Build a :class:`Policy` from the parsed YAML document."""
    priority = tuple(str(r) for r in _get(raw, "reason_priority"))
    if sorted(priority) != sorted(REASONS):
        raise PolicyError(f"policy: reason_priority must list {REASONS}, got {priority}")
    steps = _ints(raw, "guardrails.steps_pct")
    if list(steps) != sorted(steps) or not steps or steps[0] <= 0:
        raise PolicyError("policy: guardrails.steps_pct must be ascending and positive")
    return Policy(
        version=str(_get(raw, "version")),
        slow_seller=SlowSellerRule(
            max_sell_through=_dec(raw, "signals.slow_seller.max_sell_through"),
            min_weeks_of_supply=_dec(raw, "signals.slow_seller.min_weeks_of_supply"),
            min_listed_days=_int(raw, "signals.slow_seller.min_listed_days"),
            strong_sell_through=_dec(raw, "signals.slow_seller.strong_sell_through")),
        season_end=SeasonEndRule(
            window_days=_int(raw, "signals.season_end.window_days"),
            min_leftover_share=_dec(raw, "signals.season_end.min_leftover_share")),
        customer_behaviour=CustomerBehaviourRule(
            min_member_buys_8w=_int(raw, "signals.customer_behaviour.min_member_buys_8w"),
            min_overdue_factor=_dec(raw, "signals.customer_behaviour.min_overdue_factor"),
            min_cardholder_drop_pct=_dec(
                raw, "signals.customer_behaviour.min_cardholder_drop_pct"),
            min_prior_weekly=_dec(raw, "signals.customer_behaviour.min_prior_weekly")),
        on_plan_min_sell_through=_dec(raw, "signals.on_plan.min_sell_through"),
        steps=SuggestedSteps(
            slow_seller_strong=_int(raw, "suggested_step.slow_seller.strong"),
            slow_seller_default=_int(raw, "suggested_step.slow_seller.default"),
            season_end_ended=_int(raw, "suggested_step.season_end.ended"),
            season_end_within_7_days=_int(raw, "suggested_step.season_end.within_7_days"),
            season_end_default=_int(raw, "suggested_step.season_end.default"),
            customer_behaviour=_int(raw, "suggested_step.customer_behaviour")),
        reason_priority=priority,
        guardrails=Guardrails(
            steps_pct=steps,
            min_margin_pct=_dec(raw, "guardrails.min_margin_pct"),
            price_endings_cents=tuple(sorted(_ints(raw, "guardrails.price_endings_cents"),
                                             reverse=True)),
            action_days=_int(raw, "guardrails.action_days"),
            action_end_time=_clock(raw, "guardrails.action_end_time")),
        texts=TextLimits(
            headline_max=_int(raw, "texts.headline_max"),
            rationale_max=_int(raw, "texts.rationale_max"),
            facts_line_max=_int(raw, "texts.facts_line_max")),
        review=ReviewLimits(
            max_candidates_in_agent_input=_int(raw, "review.max_candidates_in_agent_input"),
            max_blocked_in_agent_input=_int(raw, "review.max_blocked_in_agent_input"),
            max_no_action_names=_int(raw, "review.max_no_action_names"),
            agent_input_max_bytes=_int(raw, "review.agent_input_max_bytes"),
            facts_short_chars=_int(raw, "review.facts_short_chars")))


def load_policy(path: str | Path) -> Policy:
    """Read and validate the policy file (``POLICY_FILE``)."""
    with open(path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, Mapping):
        raise PolicyError(f"policy: {path} is not a mapping")
    return parse_policy(raw)
