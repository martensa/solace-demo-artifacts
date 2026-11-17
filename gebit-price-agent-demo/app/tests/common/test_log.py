"""log: one configuration per process from LOG_LEVEL (3.1)."""

from __future__ import annotations

import logging

import pytest

from gposdemo.common import log


def test_configure_sets_levels_and_format() -> None:
    root = logging.getLogger()
    saved = (root.level, list(root.handlers))
    try:
        log.configure("debug", "wws")
        assert root.level == logging.DEBUG
        assert "gpos-wws" in root.handlers[0].formatter._fmt  # type: ignore[union-attr]
        assert logging.getLogger("httpx").level == logging.WARNING
        log.configure("ERROR", "pos")
        assert logging.getLogger("httpx").level == logging.ERROR
        with pytest.raises(ValueError):
            log.configure("chatty")
    finally:
        root.handlers[:] = saved[1]
        root.setLevel(saved[0])
