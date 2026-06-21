"""Tests for bridge.logging_setup (Wave 5 / #11)."""
import json
import logging

import pytest

from bridge import logging_setup as ls


@pytest.fixture(autouse=True)
def _restore_root_logger():
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in saved_handlers:
        root.addHandler(h)
    root.setLevel(saved_level)


def _make_record(msg="hello %s", args=("world",)):
    return logging.LogRecord("mylogger", logging.INFO, "p", 1, msg, args, None)


def test_correlation_filter_injects_default_dash():
    rec = _make_record()
    assert ls.CorrelationIdFilter().filter(rec) is True
    assert rec.correlation_id == "-"


def test_set_and_reset_correlation_id():
    assert ls.get_correlation_id() == "-"
    token = ls.set_correlation_id("abc123")
    try:
        assert ls.get_correlation_id() == "abc123"
        rec = _make_record()
        ls.CorrelationIdFilter().filter(rec)
        assert rec.correlation_id == "abc123"
    finally:
        ls.reset_correlation_id(token)
    assert ls.get_correlation_id() == "-"


def test_new_correlation_id_is_unique_and_short():
    a, b = ls.new_correlation_id(), ls.new_correlation_id()
    assert a != b
    assert len(a) == 12


def test_json_formatter_emits_parseable_record():
    rec = _make_record()
    ls.CorrelationIdFilter().filter(rec)
    out = ls.JsonFormatter().format(rec)
    parsed = json.loads(out)
    assert parsed["message"] == "hello world"
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "mylogger"
    assert parsed["correlation_id"] == "-"
    assert "timestamp" in parsed
    # No active OTel span -> no trace fields.
    assert "trace_id" not in parsed


def test_json_formatter_includes_exception_and_extra():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = logging.LogRecord(
            "l", logging.ERROR, "p", 1, "failed", (), sys.exc_info()
        )
    rec.tenant = "tenant-a"  # structured extra
    ls.CorrelationIdFilter().filter(rec)
    parsed = json.loads(ls.JsonFormatter().format(rec))
    assert "ValueError: boom" in parsed["exception"]
    assert parsed["tenant"] == "tenant-a"


def test_configure_logging_json_installs_json_formatter():
    ls.configure_logging("json", "DEBUG")
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, ls.JsonFormatter)
    assert root.level == logging.DEBUG
    # Filter is attached so records carry a correlation id.
    assert any(isinstance(f, ls.CorrelationIdFilter) for f in root.handlers[0].filters)


def test_configure_logging_text_uses_plain_formatter():
    ls.configure_logging("text", "INFO")
    root = logging.getLogger()
    fmt = root.handlers[0].formatter
    assert isinstance(fmt, logging.Formatter)
    assert not isinstance(fmt, ls.JsonFormatter)
