"""German texts of the engine: labels, fact texts and scan insights (UC1-BUILD-SPEC 6.6,
10.5, 11.1, 11.3).

Numbers in texts: counts as integers, ``plan`` and ``Reichweite`` with at most one
decimal (``6,5``, ``14``), the cardholder drop as a whole percent (``47``).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from ..common.fmt import date_label, dt_label

REASON_LABELS = {"slow_seller": "Ladenhüter", "season_end": "Saisonende",
                 "customer_behaviour": "Kundenverhalten"}
TEMPLATE_HEADLINES = {"slow_seller": "Abverkauf ankurbeln",
                      "season_end": "Saisonrest abverkaufen",
                      "customer_behaviour": "Stammkunden zurückgewinnen"}
ACTION_KIND = {"CENTRAL_ACTION": "Zentralaktion", "BOOTH_ACTION": "Messe-Aktion"}

BLOCK_PRICE_BOUND = "Preisbindung"
BLOCK_MIN_MARGIN = "Mindestmarge"
NEUTRAL = "unauffällig"
INSIGHT_EXCLUDED = "Gesperrt: Preisbindung"
INSIGHT_VOID = "Zeile storniert"
INSIGHT_CLOSE = "Bon abgeschlossen"
INSIGHT_CANCEL = "Bon abgebrochen"
INSIGHT_UNAVAILABLE = "Analyse nicht verfügbar"
INSIGHT_MAX = 120

# status_reason of the approval outcomes (11.5, 11.6); outcome.py and notify.py import them
REASON_EXPIRED = "Keine Antwort binnen 2 Minuten"
REASON_REJECTED = "Abgelehnt in Agent Mesh"
REASON_REJECTED_ERROR = "Abgelehnt in Agent Mesh (Agent meldete einen Fehler)"
REASON_DENY_TOO_EARLY = "Ablehnung schneller als möglich – Agent prüfen"
REASON_DENY_AFTER_APPROVAL = "Agent meldet Ablehnung trotz Freigabe – kein neuer Preis"
REASON_NO_STATUS = "Agent meldete keinen Status – kein neuer Preis"
REASON_TECHNICAL = "Technischer Fehler – kein neuer Preis"
REASON_CONTRADICTION = "Agent-Antwort widerspricht der Datenbank"


def de_num(value: Decimal | int, places: int = 1) -> str:
    """German number, at most ``places`` decimals: ``6.508`` -> ``"6,5"``, ``14`` -> ``"14"``."""
    quantum = Decimal(1).scaleb(-places)
    rounded = Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP).normalize()
    return f"{rounded:f}".replace(".", ",")


def shorten(text: str, limit: int) -> str:
    """Cut ``text`` at a word end so that it fits ``limit`` characters with ``…``."""
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    cut = head.rsplit(" ", 1)[0] if " " in head else head
    return cut.rstrip(" ,;:–-") + "…"


def slow_seller_facts(sold: int, plan: Decimal, weeks_of_supply: Decimal | None,
                      stock: int) -> str:
    """6.6: ``"9 von 35 geplanten Stück verkauft (7 Tage), Reichweite 6,5 Wochen, Bestand 96"``

    ``weeks_of_supply`` is ``None`` when nothing sold in the last 4 weeks.
    """
    reach = (f"Reichweite {de_num(weeks_of_supply)} Wochen" if weeks_of_supply is not None
             else "kein Abverkauf in 4 Wochen")
    return f"{sold} von {de_num(plan)} geplanten Stück verkauft (7 Tage), {reach}, Bestand {stock}"


def season_end_facts(label: str, end: date, days_to_end: int, stock: int) -> str:
    """6.6: running (``endet am … (n Tage)``) or over (``endete am …``)."""
    if days_to_end < 0:
        return f"Saison {label} endete am {date_label(end)}, Restbestand {stock}"
    return (f"Saison {label} endet am {date_label(end)} ({days_to_end} Tage), "
            f"Restbestand {stock}")


def customer_behaviour_facts(days_since_last: int, interval: int, drop_pct: Decimal) -> str:
    """6.6: ``"Stammartikel der Karte: zuletzt vor 35 Tagen (sonst alle 14 Tage); …"``"""
    return (f"Stammartikel der Karte: zuletzt vor {days_since_last} Tagen "
            f"(sonst alle {interval} Tage); Kartenkunden kaufen {de_num(drop_pct, 0)} % "
            "seltener")


def on_plan_facts(sold: int, plan: Decimal) -> str:
    """``"läuft nach Plan (180/180)"``"""
    return f"läuft nach Plan ({sold}/{de_num(plan)})"


def neutral_facts(sold: int, plan: Decimal) -> str:
    """``"unauffällig (17/30)"``"""
    return f"{NEUTRAL} ({sold}/{de_num(plan)})"


def action_block(source: str, valid_to: datetime | None) -> str:
    """Block reason of an open action: ``"Zentralaktion läuft bis 21.02."`` (8.2.1)."""
    kind = ACTION_KIND.get(source, "Aktion")
    return f"{kind} läuft bis {date_label(valid_to)}" if valid_to else f"{kind} läuft"


def action_insight(source: str, valid_to: datetime | None) -> str:
    """Scan chip of an open action: ``"Messe-Aktion aktiv bis Di 23.02. 20:00"`` (1.4)."""
    kind = ACTION_KIND.get(source, "Aktion")
    return f"{kind} aktiv bis {dt_label(valid_to)}" if valid_to else f"{kind} aktiv"


def signal_insight(code: str, facts: str) -> str:
    """``"Ladenhüter: 9 von 35 …"`` (<= 120 characters)."""
    return shorten(f"{REASON_LABELS[code]}: {facts}", INSIGHT_MAX)


def member_insight(persona: str, consent_profiling: bool) -> str:
    """11.1: ``"Karte Kaffeepause · Profil-Einwilligung ja"``"""
    return f"Karte {persona} · Profil-Einwilligung {'ja' if consent_profiling else 'nein'}"


def template_headline(name: str, reason: str, limit: int) -> str:
    """11.3 step 7: ``"{Name}: Abverkauf ankurbeln"``"""
    return shorten(f"{name}: {TEMPLATE_HEADLINES[reason]}", limit)
