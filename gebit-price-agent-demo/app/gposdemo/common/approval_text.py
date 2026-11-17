"""Words of SAM and agent texts around the native approval (UC1-BUILD-SPEC 11.5, 10.2).

Shared by the engine (record_outcome, sam-error) and the BFF (run label). Pure, no I/O.
A denial word counts only next to an approval context; technical and timeout words win.
"""

from __future__ import annotations

import re

TIMEOUT = re.compile(r"\b(timed out|time[- ]?out|expired|abgelaufen)\b", re.IGNORECASE)
TECHNICAL = re.compile(
    r"\b(permission|access denied|forbidden|unauthori[sz]ed|scope|rbac|"
    r"connection|connect|unavailable|unreachable|stop_reason|content filter|safety|"
    r"policy|llm|model|rate limit|overloaded|server|internal|exception|traceback|"
    r"invalid|schema|validation|40[13]|429|5\d\d)\b", re.IGNORECASE)
DENIAL = re.compile(
    r"\b(denied|deny|denial|rejected|reject|refused|refusal|declined|not approved|"
    r"abgelehnt|nicht freigegeben)\b", re.IGNORECASE)
CONTEXT = re.compile(
    r"(approv|freigab|freigeg|store manager|marktleitung|manager|\buser\b|human|mensch)",
    re.IGNORECASE)
CLAUSE = re.compile(r"[.;|\n]+")
# wording of a failed tool call in a tool RESULT message (MCP or transport error), substring
# match ("ClosedResourceError"); only for the approver's copied message, never for SAM's task
# error text, which starts "Agent reported error:" even on a denial
TOOL_ERROR = re.compile(r"(error|fail|exception|could not|cannot|unable|exceeded)",
                        re.IGNORECASE)

STATUS_APPLIED = ("applied", "already_applied")
STATUS_DENIED = ("denied", "rejected", "refused", "declined", "not_approved",
                 "not approved", "abgelehnt")
STATUS_TIMEOUT = ("timeout", "timed_out", "timed out", "expired")
STATUS_ERROR = ("error", "failed", "failure", "tool_error")


def _norm(text: object) -> str:
    return " ".join(str(text or "").split())


def is_denial(text: str) -> bool:
    """A denial word and an approval context in the same clause."""
    return any(DENIAL.search(c) and CONTEXT.search(c) for c in CLAUSE.split(_norm(text)))


def is_tool_error(text: str) -> bool:
    """A tool result message that reads like a failed call and has no denial word
    (``"Tool execution failed"``; a paraphrased denial such as ``"Tool call denied."``
    is none)."""
    t = _norm(text)
    return bool(TOOL_ERROR.search(t)) and not DENIAL.search(t)


def classify_error(text: str) -> str:
    """'' | 'timeout' | 'technical' | 'denied' | 'other'; first match in this order."""
    t = _norm(text)
    if not t:
        return ""
    if TIMEOUT.search(t):
        return "timeout"
    if TECHNICAL.search(t):
        return "technical"
    return "denied" if is_denial(t) else "other"


def classify_status(status: str) -> str:
    """Approver status: '' | 'applied' | 'blocked' | 'denied' | 'timeout' | 'error' |
    'other' (exact words, never a substring match)."""
    s = _norm(status).casefold()
    if not s:
        return ""
    if s in STATUS_APPLIED:
        return "applied"
    if s == "blocked":
        return "blocked"
    if s in STATUS_DENIED:
        return "denied"
    if s in STATUS_TIMEOUT:
        return "timeout"
    if s in STATUS_ERROR:
        return "error"
    return "other"
