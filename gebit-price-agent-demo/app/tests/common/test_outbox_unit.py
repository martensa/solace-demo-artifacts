"""outbox without a database: delivery class per row and name checks (3.3, 5.1)."""

from __future__ import annotations

import pytest

from gposdemo.common import outbox
from gposdemo.common.outbox import OutboxWriter, is_persistent


def test_is_persistent_per_class_and_mode() -> None:
    assert outbox.DELIVERY_CLASSES == ("sam_input", "business", "ui", "telemetry")
    assert [is_persistent(c, "persistent") for c in outbox.DELIVERY_CLASSES] == [
        True, True, False, False]
    assert not any(is_persistent(c, "direct") for c in outbox.DELIVERY_CLASSES)
    with pytest.raises(ValueError):
        is_persistent("gold", "persistent")


def test_schema_names_and_channels() -> None:
    assert outbox.notify_channel("engine") == "engine_outbox"
    assert OutboxWriter("wws").schema == "wws"
    for bad in ("engine; drop table x", "Engine", "", "1pos"):
        with pytest.raises(ValueError):
            OutboxWriter(bad)
