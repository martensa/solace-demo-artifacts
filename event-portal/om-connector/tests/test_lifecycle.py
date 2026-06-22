"""Tests for bridge.lifecycle graceful shutdown (Wave 5 / #13)."""
from unittest.mock import MagicMock

from bridge import lifecycle


def test_shutdown_flushes_dedupe_and_closes_clients():
    ep = MagicMock()
    om = MagicMock()
    dedupe = MagicMock()

    summary = lifecycle.shutdown(ep_client=ep, om=om, dedupe=dedupe)

    dedupe.flush.assert_called_once()
    ep.close.assert_called_once()
    om.close.assert_called_once()
    assert summary["dedupe_flushed"] is True
    assert summary["ep_closed"] is True
    assert summary["om_closed"] is True
    # Wave 4.5 (#49): bridge.writeback now exists; with no processor
    # registered the drain hook runs as a no-op and reports True.
    assert summary["writeback_drained"] is True


def test_shutdown_tolerates_missing_methods():
    # Plain objects without flush()/close() must not raise.
    class Bare:
        pass

    summary = lifecycle.shutdown(ep_client=Bare(), om=Bare(), dedupe=Bare())
    assert summary == {
        "dedupe_flushed": False,
        "writeback_drained": True,  # no-op drain hook (no processor)
        "ep_closed": False,
        "om_closed": False,
    }


def test_shutdown_isolates_a_failing_close():
    ep = MagicMock()
    ep.close.side_effect = RuntimeError("network gone")
    om = MagicMock()

    summary = lifecycle.shutdown(ep_client=ep, om=om)

    # ep close failed but om still closed; no exception escaped.
    assert summary["ep_closed"] is False
    assert summary["om_closed"] is True
    om.close.assert_called_once()


def test_shutdown_with_no_args_is_safe():
    assert lifecycle.shutdown() == {
        "dedupe_flushed": False,
        "writeback_drained": True,  # no-op drain hook (no processor)
        "ep_closed": False,
        "om_closed": False,
    }
