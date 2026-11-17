"""approval_text: SAM and agent texts around the native approval (11.5, 10.2)."""

from __future__ import annotations

import pytest

from gposdemo.common.approval_text import (classify_error, classify_status, is_denial,
                                           is_tool_error)

DENY_TEXT = "Agent reported error: Price approval was denied by store manager"  # 12.11. lab
MODEL_TEXTS = ("Agent reported error: model refused to answer (stop_reason refusal)",
               "apply_price request was rejected by server (HTTP 500)",
               "Permission denied: connector scope missing")


@pytest.mark.parametrize(("text", "expected"), [
    (DENY_TEXT, "denied"),
    ("Tool call was denied by the user", "denied"),
    ("Freigabe abgelehnt", "denied"),
    ("Tool approval timed out after 2 minutes", "timeout"),
    ("approval timed out, treated as denied", "timeout"),
    ("litellm Timeout: request timed out", "timeout"),
    ("Permission denied: connector scope missing", "technical"),
    ("Connection refused", "technical"),
    ("Agent reported error: model refused to answer (stop_reason refusal)", "technical"),
    ("apply_price request was rejected by server (HTTP 500)", "technical"),
    ("agent declined to call apply_price", "other"),     # no approval context
    ("agent crashed", "other"),
    ("", ""),
    ("   \n ", ""),
])
def test_classify_error(text: str, expected: str) -> None:
    assert classify_error(text) == expected


def test_denial_needs_the_approval_context_in_the_same_clause() -> None:
    assert is_denial(DENY_TEXT)
    assert is_denial("Approval: denied")
    assert not is_denial("The call was denied. The store manager was informed")
    assert not is_denial("declined")
    assert is_denial("node approve failed | Freigabe nicht freigegeben")
    assert not is_denial(None)  # type: ignore[arg-type]


@pytest.mark.parametrize(("status", "expected"), [
    ("applied", "applied"), ("already_applied", "applied"), ("blocked", "blocked"),
    ("denied", "denied"), ("Denied", "denied"), (" rejected ", "denied"),
    ("refused", "denied"), ("timeout", "timeout"), ("expired", "timeout"),
    ("error", "error"), ("failed", "error"), ("superseded", "other"),
    ("denied by user", "other"),                          # exact words only
    ("", ""), ("  ", ""),
])
def test_classify_status(status: str, expected: str) -> None:
    assert classify_status(status) == expected


def test_model_and_server_texts_are_technical() -> None:
    assert {classify_error(t) for t in MODEL_TEXTS} == {"technical"}


@pytest.mark.parametrize(("text", "expected"), [
    # failed tool calls as a tool result message (transport words, no TECHNICAL word)
    ("Error executing tool apply_price: ClosedResourceError", True),
    ("Tool execution failed", True),
    ("MCP tool call failed", True),
    ("tool call failed: context deadline exceeded", True),
    ("Approval request could not be delivered", True),
    # denials, also paraphrased, and texts without error wording are no tool error
    ("Tool call denied by user.", False),
    ("Tool call denied.", False),
    ("error: Tool call denied by user.", False),
    ("The user did not approve the tool call", False),
    ("Neuer Preis 7,99 € aktiv", False),
    ("", False),
])
def test_tool_error_wording_of_a_result_message(text: str, expected: bool) -> None:
    """11.5 R7m: a copied result message that reads like a failed call and names no
    denial; used only for ``tool_message``."""
    assert is_tool_error(text) is expected
    if expected:
        assert classify_error(text) == "other"       # TECHNICAL does not catch these
