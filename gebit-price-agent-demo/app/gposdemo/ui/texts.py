"""Fixed German UI texts and the colour scheme of /kasse and /monitor (UC1-BUILD-SPEC 10.3-10.5).

Single source of truth: the BFF serves these constants to the browser as
``/static/shared/texts.js`` (``window.GPOS_TEXTS``), so the pages never carry their own
copy. Texts of 10.5 are verbatim; the colour scheme is the one of 10.4.

Model rule (15.2 UC1-26, shared by counters, monitor header, proposal card and
timeline): an agent's model alias is ``fast`` or ``planning``; anything else (missing in
legacy reviews, ``""``) means ``fast``, the former single agent. ``{model}`` in
:data:`TIMELINE_STEPS` and :data:`AGENT_ASKS` is always the display name of
:data:`MODEL_NAMES`, never the alias.
"""

from __future__ import annotations

from typing import Any

from ..common.jsonutil import compact

# 10.5 occasion labels
REASON_LABELS: dict[str, str] = {
    "slow_seller": "Ladenhüter",
    "season_end": "Saisonende",
    "customer_behaviour": "Kundenverhalten",
}

# 10.5 states (proposal states, the review state ``deferred`` and the signal
# ``duplicate_request``)
STATE_TEXTS: dict[str, str] = {
    "ready": "Vorschlag bereit",
    "pending": "Liegt in Agent Mesh bei der Marktleitung",
    "approved": "Freigegeben",
    "rejected": "Abgelehnt – kein neuer Preis",
    "expired": "Abgelaufen – kein neuer Preis",
    "blocked": "Blockiert durch Leitplanke",
    "failed": "Technischer Fehler",
    "superseded": "Zurückgesetzt",
    "deferred": "Zurückgestellt – offene Freigabe an dieser Kasse, nicht nachgeholt",
    "duplicate_request": "Zweite Freigabeanfrage erkannt – Preis ist bereits aktiv",
}

# 10.2 run labels (``sam_run.label``)
RUN_LABEL_OK = "ok"
RUN_LABEL_ERROR = "Fehler"
RUN_LABEL_EXPIRED = "Abgelaufen"
RUN_LABEL_DENIED = "Abgelehnt"

# Model aliases of the agents (SAM model configuration) and their display names
# (16.1 no. 35: whoever re-points an alias in SAM updates MODEL_NAMES).
MODELS = ("fast", "planning")
DEFAULT_MODEL = "fast"
MODEL_NAMES: dict[str, str] = {"fast": "Claude Haiku 4.5", "planning": "Claude Sonnet 5"}

# 10.4 colour scheme: scan-analysis chips by signal code. Candidate signals red,
# on_plan green, neutral grey, blocked grey with a lock.
CHIPS: dict[str, dict[str, Any]] = {
    "slow_seller": {"tone": "red", "lock": False, "text": ""},
    "season_end": {"tone": "red", "lock": False, "text": ""},
    "customer_behaviour": {"tone": "red", "lock": False, "text": ""},
    "on_plan": {"tone": "green", "lock": False, "text": "läuft nach Plan"},
    "neutral": {"tone": "grey", "lock": False, "text": "unauffällig"},
    "excluded": {"tone": "grey", "lock": True, "text": ""},
    "action": {"tone": "grey", "lock": True, "text": ""},
}
# Source colours, only for stations, the run list and the agent timeline (10.4).
SOURCE_TONES: dict[str, str] = {
    "rule": "turquoise", "ai": "violet", "human": "orange", "till": "blue",
}

# 10.4 monitor
CLAIM = "KI schlägt vor. Regeln prüfen. Mensch entscheidet."
BADGES = ("Simulator (GEBIT Purchase API 2.50)", "Lab", "Solace Agent Mesh 2.542.1")
STATIONS: tuple[dict[str, str], ...] = (
    {"no": "1", "label": "Kasse", "source": "till"},
    {"no": "2", "label": "Analyse in Agent Mesh", "source": "rule"},
    {"no": "3", "label": "KI prüft und empfiehlt", "source": "ai"},
    {"no": "4", "label": "Freigabe Marktleitung", "source": "human"},
    {"no": "5", "label": "Neuer Preis", "source": "till"},
)
COLUMNS = ("Kasse live", "Agent Mesh", "Freigabe und Preis")
CONSENT_YES = "Karte mit Profil-Einwilligung"
CONSENT_NO = "Karte ohne Profil-Einwilligung – Kundenverhalten nicht genutzt"
RULE_ANALYSIS = "Regel-Analyse (ohne KI)"
AI_RECOMMENDATION = "KI-Empfehlung · {model} ({name})"
NO_CHANGE_RECOMMENDED = "Keine Preisänderung empfohlen"
EVIDENCE_TITLE = "Belege · {model} ({name})"
EVIDENCE_HOLDS = {"yes": "Anlass bestätigt", "no": "Anlass nicht bestätigt",
                  "unknown": "Beleg unklar"}
EVIDENCE_LINE = "{article} · {reason}: {holds}"
TEMPLATE_TEXT = "Vorlagentext der Engine (KI-Text verworfen)"
GUARDRAILS_TITLE = "Leitplanken der Engine (ohne KI)"
TIMELINE_STEPS = {
    "rules": "Regel-Analyse (ohne KI): {candidates} Kandidat(en) markiert",
    "evidenceRunning": "{model} prüft Belege …",
    "evidenceDone": "{model} prüft Belege über {n} API-Abfragen",
    "evidenceDetail": "{holding} von {checked} Anlässen bestätigt",
    "planningRunning": "{model} wertet die Belege aus …",
    "planningPropose": "{model} empfiehlt: {article} ({reason})",
    "planningNoAction": "{model} empfiehlt: keine Preisänderung",
    "planningFailed": "{model}: keine Empfehlung (Lauf abgebrochen)",
    "engine": "Engine prüft Leitplanken und rechnet den Preis (ohne KI): {old} € → {new} €",
    "engineBlocked": "Engine blockiert die Empfehlung: {reason}",
    "approver": "{model} legt der Marktleitung die Freigabe vor",
}
NO_ADJUSTMENT = "keine Preisanpassung"
NO_ADJUSTMENT_NEEDED = "keine Preisanpassung nötig"
OTHER_CANDIDATES = "weitere Kandidaten (nicht vorgeschlagen)"
NO_ACTION_NEEDED = "keine Aktion nötig"
API_FAMILIES = {"pos": "Kasse", "wws": "Warenwirtschaft", "loyalty": "Loyalty"}
AGENT_ASKS = "{model} fragt {family}: {tool}"
REF30_LINE = "Niedrigster Preis der letzten 30 Tage: {ref30} €"
CLAMPED_INFO = "Stufe von der Engine festgelegt"
PENDING_SINCE = "Liegt in Agent Mesh bei der Marktleitung seit {elapsed}"
STAMP_APPROVED = "Freigegeben · Marktleitung · in Agent Mesh"
STAMP_BY = "empfohlen von KI (planning), geprüft von der Engine"
STAMPS = {"rejected": "Abgelehnt", "expired": "Abgelaufen", "blocked": "Blockiert"}
NEW_PRICE_ACTIVE = "Neuer Preis {price} € aktiv"
NEXT_SCAN = "Nächster Scan: {price} € AKTION"
RECAP = "Rückblick: letzte Freigabe"
COUNTERS_LINE = ("{pos_events} Kassenereignisse → {sam_runs} SAM-Läufe → {agent_runs} "
                 "KI-Agenten-Läufe (fast {fast}, planning {planning}) · {agent_tool_calls} "
                 "API-Abfragen der Agenten → {approvals} Freigabe(n)")
LLM_HINT = "≈ 1–2 KI-Aufrufe je Agentenlauf"
FICTIONAL = "Fiktive Daten"
SIMPLIFICATION = ("Vereinfachung: Messe-Aktionen zählen für den 30-Tage-Tiefstpreis nicht "
                  "mit (Wiederholbarkeit)")
RECAP_AFTER_S = 90
REVIEW_REQUESTED = "Warenkorb-Prüfung angefordert"
REVIEW_SUMMARY = "{articles} Artikel, {candidates} Kandidat(en)"
REVIEW_WITHOUT_AI = "Regel-Analyse (ohne KI) – keine Preisanpassung nötig"
MONITOR_LABELS = {
    "noBon": "Kein offener Bon", "bonOpen": "Bon offen", "bonClosed": "Bon abgeschlossen",
    "bonCancelled": "Bon abgebrochen", "events": "GEBIT-Ereignisse", "toSam": "→ SAM",
    "runs": "SAM-Läufe", "review": "Warenkorb-Prüfung", "candidates": "Kandidaten",
    "blocked": "Gesperrt", "timeline": "KI-Schritte", "sum": "Summe",
    "card": "Karte {persona}", "reason": "Anlass: {label}", "validTo": "gültig bis {label}",
    "basePrice": "Grundpreis: {label}", "priceEvent": "Ereignis", "waiting": "Warte auf den "
    "nächsten Vorschlag …",
}

# 10.3 till simulator
TILL_HEAD = "Kasse {till} · Messestand"
TEST_TILL_HEAD = "Kasse {till} · Testkasse"
TEST_TILL_SWITCH = "Testkasse 99"
TILL_STATUS = {"ready": "Bereit", "open": "Bon offen", "payment": "Zahlung",
               "closed": "Abgeschlossen"}
EAN_PLACEHOLDER = "EAN scannen oder tippen"
UNKNOWN_EAN = "Unbekannte EAN: {ean}"
CARD_BAR = "Kundenkarte"
SCENARIO_BAR = "Szenarien"
BUTTONS = {"new": "Neuer Bon", "void": "Zeile stornieren", "pay": "Bezahlen (bar)",
           "cancel": "Abbrechen", "reset": "Demo zurücksetzen"}
ACTION_BADGE = "AKTION"
RESET_HINT = ("Offene Freigabeanfragen räumt der Inbox-Wächter (make demo-watch) bzw. "
              "make demo-reset ab.")
RESET_SCOPES = {"booth": "Messestand (Standard)", "day": "Ganzer Tag (Laufzeitdaten löschen)"}
SCENARIO_STEP_MS = 1200
KASSE_LABELS = {
    "bon": "Bon", "sum": "Summe", "noCard": "keine Karte", "eanButton": "OK",
    "scenarioRunning": "{label}: Schritt {step} von {steps}",
    "resetTitle": "Demo zurücksetzen", "resetConfirm": "Zurücksetzen", "close": "Schließen",
    "resetDone": "Demo zurückgesetzt", "resetFailed": "Reset unvollständig: {steps}",
    "error": "Fehler: {message}", "paid": "Bar bezahlt: {amount} €",
    "catalogError": "Artikelstamm nicht erreichbar", "selectLine": "Zeile antippen, dann "
    "stornieren",
}
CONNECTION_LOST = "Verbindung zum Server unterbrochen – verbinde neu …"


def model_of(alias: Any) -> str:
    """The model rule: ``fast`` or ``planning``; anything else (missing, ``""``) is
    ``fast``."""
    return alias if isinstance(alias, str) and alias in MODELS else DEFAULT_MODEL


def model_name(alias: Any) -> str:
    """Display name of an alias after :func:`model_of` (``{model}`` of the timeline)."""
    return MODEL_NAMES[model_of(alias)]


def bundle() -> dict[str, Any]:
    """Everything the pages need, as one JSON-able object."""
    return {
        "reasons": REASON_LABELS, "states": STATE_TEXTS, "connectionLost": CONNECTION_LOST,
        "runLabels": {"ok": RUN_LABEL_OK, "error": RUN_LABEL_ERROR,
                      "expired": RUN_LABEL_EXPIRED, "denied": RUN_LABEL_DENIED},
        "models": list(MODELS), "defaultModel": DEFAULT_MODEL, "modelNames": MODEL_NAMES,
        "chips": CHIPS, "sourceTones": SOURCE_TONES,
        "monitor": {
            "claim": CLAIM, "badges": list(BADGES), "stations": list(STATIONS),
            "columns": list(COLUMNS), "consentYes": CONSENT_YES, "consentNo": CONSENT_NO,
            "ruleAnalysis": RULE_ANALYSIS, "aiRecommendation": AI_RECOMMENDATION,
            "noChangeRecommended": NO_CHANGE_RECOMMENDED, "evidenceTitle": EVIDENCE_TITLE,
            "evidenceHolds": EVIDENCE_HOLDS, "evidenceLine": EVIDENCE_LINE,
            "templateText": TEMPLATE_TEXT, "guardrailsTitle": GUARDRAILS_TITLE,
            "timelineSteps": TIMELINE_STEPS,
            "noAdjustment": NO_ADJUSTMENT, "noAdjustmentNeeded": NO_ADJUSTMENT_NEEDED,
            "otherCandidates": OTHER_CANDIDATES, "noActionNeeded": NO_ACTION_NEEDED,
            "apiFamilies": API_FAMILIES, "agentAsks": AGENT_ASKS, "ref30": REF30_LINE,
            "clamped": CLAMPED_INFO, "pendingSince": PENDING_SINCE,
            "stampApproved": STAMP_APPROVED, "stampBy": STAMP_BY, "stamps": STAMPS,
            "newPriceActive": NEW_PRICE_ACTIVE, "nextScan": NEXT_SCAN, "recap": RECAP,
            "countersLine": COUNTERS_LINE, "llmHint": LLM_HINT, "fictional": FICTIONAL,
            "simplification": SIMPLIFICATION, "recapAfterS": RECAP_AFTER_S,
            "reviewRequested": REVIEW_REQUESTED, "reviewSummary": REVIEW_SUMMARY,
            "reviewWithoutAi": REVIEW_WITHOUT_AI, "labels": MONITOR_LABELS,
        },
        "kasse": {
            "head": TILL_HEAD, "testHead": TEST_TILL_HEAD, "testSwitch": TEST_TILL_SWITCH,
            "status": TILL_STATUS, "eanPlaceholder": EAN_PLACEHOLDER,
            "unknownEan": UNKNOWN_EAN, "cardBar": CARD_BAR, "scenarioBar": SCENARIO_BAR,
            "buttons": BUTTONS, "actionBadge": ACTION_BADGE, "resetHint": RESET_HINT,
            "resetScopes": RESET_SCOPES, "scenarioStepMs": SCENARIO_STEP_MS,
            "labels": KASSE_LABELS,
        },
    }


def texts_js() -> str:
    """``window.GPOS_TEXTS = {...};`` (frozen) for ``/static/shared/texts.js``."""
    return f"window.GPOS_TEXTS = Object.freeze({compact(bundle())});\n"


def counters_line(counters: dict[str, Any]) -> str:
    """The footer line of 10.2 for a counters dict; ``fast``/``planning`` come from
    ``agent_runs_by_model`` (default 0)."""
    by_model = counters.get("agent_runs_by_model") or {}
    return COUNTERS_LINE.format(**{**counters, "fast": by_model.get("fast", 0),
                                   "planning": by_model.get("planning", 0)})
