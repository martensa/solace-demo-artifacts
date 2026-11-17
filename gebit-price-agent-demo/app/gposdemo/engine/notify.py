"""Notification texts the engine writes and SAM sends with ``notify_user``
(UC1-BUILD-SPEC 11.6): the summary before the approval request (``inform``), the
outcome (``tell``) and the login preflight (``probe``)."""

from __future__ import annotations

from decimal import Decimal
from zoneinfo import ZoneInfo

from . import texts
from .records import ProposalRecord

TITLE_MAX = 90
MESSAGE_MAX = 600
PROBE_TITLE = "gpos Preflight: Benachrichtigung ok"
PROBE_MESSAGE = "Testmeldung der Anmeldeprüfung, keine Aktion nötig."


def _fit_title(template: str, name: str) -> str:
    """Fill ``{name}`` into ``template``; shorten the name when the title exceeds 90."""
    title = template.format(name=name)
    if len(title) <= TITLE_MAX:
        return title
    return template.format(name=texts.shorten(name, len(name) - (len(title) - TITLE_MAX)))


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text[-1] in ".!?…" else text + "."


def inform(p: ProposalRecord, zone: ZoneInfo, min_margin_pct: Decimal) -> tuple[str, str]:
    """Title and message of the summary notification (node ``inform``)."""
    title = _fit_title(f"Preisvorschlag {{name}}: {p.old_label} € → {p.new_label} € "
                       f"({p.pct_label_unicode})", p.article_name)
    label = "KI-Empfehlung" if p.text_source == "ai" else "Begründung"
    before = f"Anlass: {p.reason_label} – {_sentence(p.facts_line.rstrip('.'))} {label}: "
    after = " ".join(part for part in (
        f"Leitplanken: Marge {p.margin_label} % ≥ {texts.de_num(min_margin_pct)} %, "
        f"keine laufende Aktion, Preispunkt {p.ending_label}.",
        f"Niedrigster Preis der letzten 30 Tage: {p.ref30_label} €.",
        _sentence(p.note),
        f"Gültig bis {p.valid_to_label(zone)}.",
        f"Bitte die folgende Freigabeanfrage beantworten (Ref {p.proposal_id}).") if part)
    rationale = _sentence(p.rationale)
    budget = MESSAGE_MAX - len(before) - len(after) - 1
    if len(rationale) > budget:
        rationale = texts.shorten(rationale, budget)
    return title, f"{before}{rationale} {after}"


def tell(outcome: str, p: ProposalRecord, zone: ZoneInfo, action_id: str,
         status_reason: str) -> tuple[str, str]:
    """Title and message of the outcome notification (node ``tell``); ``("", "")`` for
    ``unknown``."""
    ref = f"Ref {p.proposal_id}."
    if outcome == "approved":
        return (_fit_title(f"Preis aktiv: {{name}} {p.new_label} € bis "
                           f"{p.valid_to_label(zone)}", p.article_name),
                f"Freigegeben in Agent Mesh. Ab dem nächsten Scan kostet {p.article_name} "
                f"{p.new_label} € statt {p.old_label} €. Ref {p.proposal_id}, "
                f"Aktion {action_id}.")
    if outcome == "rejected":
        reason = (status_reason or texts.REASON_REJECTED).rstrip(".")
        return (_fit_title(f"Abgelehnt: {{name}} bleibt bei {p.old_label} €",
                           p.article_name), f"{reason}. Kein neuer Preis. {ref}")
    if outcome in ("blocked", "failed"):
        reason = (status_reason or texts.REASON_TECHNICAL).rstrip(".")
        return (_fit_title("Nicht angewendet: {name}", p.article_name), f"{reason}. {ref}")
    if outcome == "superseded":
        return (_fit_title(f"Zurückgesetzt: {{name}} bleibt bei {p.old_label} €",
                           p.article_name),
                f"Der Vorschlag wurde durch einen Reset beendet. {ref}")
    if outcome == "expired":
        return (_fit_title(f"Abgelaufen: {{name}} bleibt bei {p.old_label} €", p.article_name),
                f"{texts.REASON_EXPIRED}. {ref}")
    return "", ""
