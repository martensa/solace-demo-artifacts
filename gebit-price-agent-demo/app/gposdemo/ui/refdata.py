"""Reference data of the BFF from ``DATA_DIR`` (UC1-BUILD-SPEC 1.3, 6.1, 6.4, 10.1).

* cards: ``data/personas.yaml`` -> ``[{"card", "persona", "consent_profiling"}]``
* scenarios: ``data/scenarios.yaml`` (S1-S8, S1b), steps validated against the four ops
* category order of 6.1 for the tabs of /kasse
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CATEGORY_ORDER = (
    "obst_gemuese", "molkerei_fruehstueck", "kaffee_tee", "suesswaren_snacks", "getraenke",
    "drogerie_haushalt", "spielwaren_geschenke", "buch",
)
SCENARIO_OPS = ("new", "card", "scan", "pay")
OPS_WITH_VALUE = ("card", "scan")


@dataclass(frozen=True)
class Card:
    """One loyalty card of 6.4 (fictional)."""

    card: str
    member_id: str
    persona: str
    consent_profiling: bool

    def public(self) -> dict[str, Any]:
        """The fields of ``GET /api/cards`` (and nothing else)."""
        return {"card": self.card, "persona": self.persona,
                "consent_profiling": self.consent_profiling}


@dataclass(frozen=True)
class RefData:
    """Cards and scenarios, loaded once at start."""

    cards: tuple[Card, ...]
    scenarios: tuple[dict[str, Any], ...]

    def card(self, key: str) -> Card | None:
        """Card by card number (``CLUB-1001``) or member id (``M-1001``)."""
        for card in self.cards:
            if key in (card.card, card.member_id):
                return card
        return None


def _load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_cards(path: Path) -> tuple[Card, ...]:
    """Cards of ``personas.yaml`` in file order."""
    doc = _load_yaml(path)
    members = doc.get("members") if isinstance(doc, dict) else None
    if not isinstance(members, list):
        raise ValueError(f"{path}: no members list")
    cards = []
    for member in members:
        consent = member.get("consent") or {}
        cards.append(Card(card=str(member["card"]), member_id=str(member["id"]),
                          persona=str(member["persona"]),
                          consent_profiling=bool(consent.get("profiling", False))))
    return tuple(cards)


def _step(scenario_id: str, raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict) or raw.get("op") not in SCENARIO_OPS:
        raise ValueError(f"scenario {scenario_id}: invalid step {raw!r}")
    op = raw["op"]
    if op in OPS_WITH_VALUE:
        value = raw.get("value")
        if not isinstance(value, str) or not value:
            raise ValueError(f"scenario {scenario_id}: step {op} needs a string value")
        return {"op": op, "value": value}
    if "value" in raw:
        raise ValueError(f"scenario {scenario_id}: step {op} takes no value")
    return {"op": op}


def load_scenarios(path: Path) -> tuple[dict[str, Any], ...]:
    """Scenarios of ``scenarios.yaml``: ``{"id", "label", "steps": [{"op", "value"?}]}``."""
    doc = _load_yaml(path)
    if not isinstance(doc, list):
        raise ValueError(f"{path}: expected a list of scenarios")
    out = []
    for raw in doc:
        scenario_id = str(raw["id"])
        steps = [_step(scenario_id, s) for s in raw.get("steps") or []]
        if not steps or steps[0]["op"] != "new":
            raise ValueError(f"scenario {scenario_id}: must start with op new")
        out.append({"id": scenario_id, "label": str(raw["label"]), "steps": steps})
    return tuple(out)


def load(data_dir: str) -> RefData:
    """Cards and scenarios from ``DATA_DIR``."""
    root = Path(data_dir)
    return RefData(cards=load_cards(root / "personas.yaml"),
                   scenarios=load_scenarios(root / "scenarios.yaml"))


def category_rank(tag: str) -> int:
    """Position of a category tag in 6.1 (unknown tags last)."""
    return CATEGORY_ORDER.index(tag) if tag in CATEGORY_ORDER else len(CATEGORY_ORDER)
