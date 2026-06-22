"""OM -> EP write-back tests (Wave 4.5 / #49).

bridge.writeback is SDK-free (the pure policy + the processor), so the
high-blast-radius logic is fully unit-tested locally. The live EP write
is isolated in EventPortalWriter and mocked here."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from bridge import writeback
from connector.property_keys import CP_APP_VERSION_ID, CP_EVENT_VERSION_ID


def _settings(enabled=True, dry_run=True, queue_max=100):
    return SimpleNamespace(enabled=enabled, dry_run=dry_run, queue_max=queue_max)


def _topic_event(extension, **entity_extra):
    entity = {"entityType": "topic", "extension": extension}
    entity.update(entity_extra)
    return {"entityType": "topic", "entity": entity}


# --------------------------------------------------------- extract_ep_target


def test_extract_ep_target_topic_and_pipeline():
    assert writeback.extract_ep_target("topic", {CP_EVENT_VERSION_ID: "ev-1"}) == (
        "eventVersions", "ev-1",
    )
    assert writeback.extract_ep_target(
        "pipeline", {CP_APP_VERSION_ID: "av-9"}
    ) == ("applicationVersions", "av-9")


def test_extract_ep_target_unsupported_or_missing_id():
    assert writeback.extract_ep_target("table", {CP_EVENT_VERSION_ID: "x"}) is None
    assert writeback.extract_ep_target("container", {}) is None
    assert writeback.extract_ep_target("topic", {}) is None  # no EP id


# --------------------------------------------------------- changed_fields


def test_changed_fields_strips_nested_and_unions_buckets():
    ce = {
        "changeDescription": {
            "fieldsUpdated": [{"name": "description"}],
            "fieldsAdded": [{"name": "extension.eventPortalContainsPii"}],
            "fieldsDeleted": [{"name": "owners"}],
        }
    }
    assert writeback.changed_fields(ce) == {"description", "extension", "owners"}
    assert writeback.changed_fields({}) == set()


# --------------------------------------------------------- plan_writes


def test_plan_writes_topic_governance_fields():
    entity = {
        "entityType": "topic",
        "extension": {CP_EVENT_VERSION_ID: "ev-1"},
        "description": "Extended in OM",
        "certification": {"tagLabel": {"tagFQN": "Certification.Gold"}},
        "owners": [{"name": "alice"}, {"displayName": "Bob B"}],
    }
    writes = writeback.plan_writes({"entityType": "topic", "entity": entity})
    by_ca = {w.ca_name: w for w in writes}
    assert by_ca[writeback.CA_EXTENDED_DESCRIPTION].value == "Extended in OM"
    assert by_ca[writeback.CA_EXTENDED_DESCRIPTION].ep_entity_path == "eventVersions"
    assert by_ca[writeback.CA_EXTENDED_DESCRIPTION].ep_entity_id == "ev-1"
    assert by_ca[writeback.CA_CERTIFICATION].value == "Certification.Gold"
    assert by_ca[writeback.CA_ADDITIONAL_OWNERS].value == "alice, Bob B"


def test_plan_writes_skips_unsupported_entity():
    entity = {"entityType": "table", "extension": {CP_EVENT_VERSION_ID: "ev-1"},
              "description": "x"}
    assert writeback.plan_writes({"entityType": "table", "entity": entity}) == []


def test_plan_writes_skips_when_only_structural_field_changed():
    entity = {
        "entityType": "topic",
        "extension": {CP_EVENT_VERSION_ID: "ev-1"},
        "description": "still here",
    }
    ce = {
        "entityType": "topic", "entity": entity,
        "changeDescription": {"fieldsUpdated": [{"name": "messageSchema"}]},
    }
    # EP-owned structural change only -> no write-back (EP wins).
    assert writeback.plan_writes(ce) == []


def test_plan_writes_proceeds_when_governance_field_changed():
    entity = {
        "entityType": "pipeline",
        "extension": {CP_APP_VERSION_ID: "av-1"},
        "description": "desc",
    }
    ce = {
        "entityType": "pipeline", "entity": entity,
        "changeDescription": {"fieldsUpdated": [{"name": "description"}]},
    }
    writes = writeback.plan_writes(ce)
    assert len(writes) == 1
    assert writes[0].ep_entity_path == "applicationVersions"


def test_plan_writes_external_linkage_from_extension():
    entity = {
        "entityType": "pipeline",
        "extension": {
            CP_APP_VERSION_ID: "av-1",
            writeback.CA_EXTERNAL_SOURCE: "sap.table.orders",
        },
    }
    writes = writeback.plan_writes({"entityType": "pipeline", "entity": entity})
    by_ca = {w.ca_name: w for w in writes}
    assert by_ca[writeback.CA_EXTERNAL_SOURCE].value == "sap.table.orders"


def test_plan_writes_unwraps_entity_extension_rootmodel():
    ext = SimpleNamespace(root={CP_EVENT_VERSION_ID: "ev-1"})
    entity = {"entityType": "topic", "extension": ext, "description": "d"}
    writes = writeback.plan_writes({"entityType": "topic", "entity": entity})
    assert writes and writes[0].ep_entity_id == "ev-1"


# --------------------------------------------------------- WritebackProcessor


def test_enqueue_noop_when_disabled():
    proc = writeback.WritebackProcessor(settings=_settings(enabled=False))
    assert proc.enqueue({"entityType": "topic"}) is False


def test_process_dry_run_does_not_call_writer():
    writer = MagicMock()
    proc = writeback.WritebackProcessor(settings=_settings(dry_run=True), writer=writer)
    entity = {"entityType": "topic", "extension": {CP_EVENT_VERSION_ID: "ev-1"},
              "description": "d"}
    plan = proc.process({"entityType": "topic", "entity": entity})
    assert len(plan) == 1
    writer.set_entity_custom_attributes.assert_not_called()


def test_process_live_calls_writer_per_write():
    writer = MagicMock()
    proc = writeback.WritebackProcessor(settings=_settings(dry_run=False), writer=writer)
    entity = {
        "entityType": "topic", "extension": {CP_EVENT_VERSION_ID: "ev-1"},
        "description": "d",
        "certification": {"tagLabel": {"tagFQN": "Certification.Gold"}},
    }
    proc.process({"entityType": "topic", "entity": entity})
    assert writer.set_entity_custom_attributes.call_count == 2
    args, kwargs = writer.set_entity_custom_attributes.call_args
    assert args[0] == "eventVersions"
    assert args[1] == "ev-1"


def test_drain_does_not_deadlock_without_worker():
    """Regression (#49 review): a non-empty queue with no consuming worker
    (e.g. a late OM webhook after the worker stopped) must NOT hang drain --
    it honors the timeout and returns the residual count."""
    import time as _time

    proc = writeback.WritebackProcessor(settings=_settings(dry_run=True))
    assert proc.enqueue({"entityType": "topic", "entity": {}}) is True  # no worker
    start = _time.monotonic()
    remaining = proc.drain(timeout=1)
    elapsed = _time.monotonic() - start
    assert elapsed < 3.0, "drain hung past its timeout"
    assert remaining >= 1


def test_enqueue_and_drain_processes_in_background():
    writer = MagicMock()
    proc = writeback.WritebackProcessor(settings=_settings(dry_run=False), writer=writer)
    proc.start()
    entity = {"entityType": "topic", "extension": {CP_EVENT_VERSION_ID: "ev-1"},
              "description": "d"}
    assert proc.enqueue({"entityType": "topic", "entity": entity}) is True
    remaining = proc.drain(timeout=5)
    assert remaining == 0
    writer.set_entity_custom_attributes.assert_called()


# --------------------------------------------------------- module-level drain


def test_module_drain_noop_without_processor():
    writeback.register_processor(None)
    assert writeback.drain(timeout=1) == 0


def test_module_drain_flushes_registered_processor():
    proc = writeback.WritebackProcessor(settings=_settings(dry_run=True))
    writeback.register_processor(proc)
    try:
        assert writeback.drain(timeout=1) == 0
    finally:
        writeback.register_processor(None)


# --------------------------------------------------------- CA definitions


def test_ensure_ca_definitions_dry_run_does_not_write():
    writer = MagicMock()
    names = writeback.ensure_writeback_ca_definitions(writer, dry_run=True)
    assert set(names) == set(writeback.WRITEBACK_CA_DEFINITIONS)
    writer.ensure_custom_attribute_definition.assert_not_called()


def test_ensure_ca_definitions_live_calls_writer():
    writer = MagicMock()
    writeback.ensure_writeback_ca_definitions(writer, dry_run=False)
    assert writer.ensure_custom_attribute_definition.call_count == len(
        writeback.WRITEBACK_CA_DEFINITIONS
    )
