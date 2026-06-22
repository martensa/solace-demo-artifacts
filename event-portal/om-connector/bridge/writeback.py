"""OM -> EP governance write-back (Wave 4.5 / #49).

The bridge receives OpenMetadata EntityChangeEvents (OM Alerts -> webhook
destination, consumed locally in the on-prem cluster -- never inbound from
EP, see Cluster 6.9), maps the OM-owned governance fields to Event Portal
custom-attribute values per the Cluster 5 per-field policy, and writes them
back to EP using the SEPARATE write-scoped token.

Design guards (this is the highest-blast-radius path in the connector):

* OFF by default (`writebackEnabled=false`) and DRY-RUN by default even
  when enabled -- live EP writes require an explicit opt-out of dry-run
  after a green shadow-deploy drift cron (plan exit criterion).
* The pure policy (:func:`plan_writes`) has no I/O and is fully unit
  tested; the live EP write is isolated in ``EventPortalWriter`` and
  marked for contract verification.
* A module-level processor + :func:`drain` satisfy the graceful-shutdown
  hook (#13) so an in-flight queue is flushed on SIGTERM.

Per-field policy (Cluster 5, OM-wins governance fields pushed as EP CAs):
description -> epExtendedDescription, certification -> epCertification,
owners(added) -> epAdditionalOwners, external linkage ->
externalSourceOmFqn / externalSinkOmFqn.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from connector.property_keys import (
    CP_APP_VERSION_ID,
    CP_EVENT_VERSION_ID,
)

from . import metrics

logger = logging.getLogger(__name__)

# EP governance custom attributes written by OM (Cluster 5 / plan #49).
CA_EXTENDED_DESCRIPTION = "epExtendedDescription"
CA_CERTIFICATION = "epCertification"
CA_ADDITIONAL_OWNERS = "epAdditionalOwners"
CA_EXTERNAL_SOURCE = "externalSourceOmFqn"
CA_EXTERNAL_SINK = "externalSinkOmFqn"

WRITEBACK_CA_DEFINITIONS = (
    CA_EXTENDED_DESCRIPTION,
    CA_CERTIFICATION,
    CA_ADDITIONAL_OWNERS,
    CA_EXTERNAL_SOURCE,
    CA_EXTERNAL_SINK,
)

# Governance fields whose change should trigger a write-back. An EP-owned
# structural change (schema, topic address, ...) is ignored here -- EP wins.
_GOVERNANCE_FIELDS = frozenset(
    {"description", "certification", "owners", "tags", "extension"}
)

# OM entity type -> (EP architecture sub-path, OM extension CP holding the
# EP version id). Only entities the connector emits per-version are
# writable targets; schemas / containers are EP-wins structural, so absent.
_OM_TO_EP_TARGET = {
    "topic": ("eventVersions", CP_EVENT_VERSION_ID),
    "pipeline": ("applicationVersions", CP_APP_VERSION_ID),
}


@dataclass(frozen=True)
class CaWrite:
    """One custom-attribute write against a resolved EP entity."""

    ep_entity_path: str
    ep_entity_id: str
    ca_name: str
    value: str


def _extension_dict(entity: Dict[str, Any]) -> Dict[str, Any]:
    """Unwrap an OM entity's ``extension`` (dict or EntityExtension(root))."""
    ext = entity.get("extension")
    if ext is None:
        return {}
    root = getattr(ext, "root", None)
    if isinstance(root, dict):
        return root
    return ext if isinstance(ext, dict) else {}


def changed_fields(change_event: Dict[str, Any]) -> Set[str]:
    """Top-level field names touched by an OM EntityChangeEvent.

    Returns an empty set when no changeDescription is present (callers treat
    that as 'unknown -> evaluate current governance state')."""
    cd = change_event.get("changeDescription") or {}
    names: Set[str] = set()
    for bucket in ("fieldsUpdated", "fieldsAdded", "fieldsDeleted"):
        for f in cd.get(bucket) or []:
            name = f.get("name") if isinstance(f, dict) else f
            if name:
                # OM nests as "owners", "description", "extension.<cp>", ...
                names.add(str(name).split(".", 1)[0])
    return names


def extract_ep_target(entity_type: str, extension: Dict[str, Any]):
    """Resolve the EP write target (path, id) from an OM entity, or None."""
    mapping = _OM_TO_EP_TARGET.get((entity_type or "").lower())
    if not mapping:
        return None
    ep_path, cp_key = mapping
    ep_id = extension.get(cp_key)
    if not ep_id:
        return None
    return ep_path, str(ep_id)


def _certification(entity: Dict[str, Any]) -> Optional[str]:
    cert = entity.get("certification")
    if not isinstance(cert, dict):
        return None
    label = cert.get("tagLabel")
    if isinstance(label, dict):
        return label.get("tagFQN") or label.get("name")
    return None


def _owner_names(entity: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for owner in entity.get("owners") or []:
        if isinstance(owner, dict):
            name = (
                owner.get("displayName")
                or owner.get("name")
                or owner.get("fullyQualifiedName")
            )
            if name:
                out.append(str(name))
    return out


def plan_writes(change_event: Dict[str, Any]) -> List[CaWrite]:
    """Pure: OM EntityChangeEvent -> the EP custom-attribute writes it
    implies under the Cluster 5 policy. Returns [] when the entity is not a
    writable target, has no resolvable EP id, or only EP-owned (structural)
    fields changed.
    """
    entity = change_event.get("entity")
    if not isinstance(entity, dict):
        entity = change_event
    entity_type = (
        change_event.get("entityType") or entity.get("entityType") or ""
    )
    extension = _extension_dict(entity)
    target = extract_ep_target(entity_type, extension)
    if target is None:
        return []
    ep_path, ep_id = target

    touched = changed_fields(change_event)
    # If we know what changed and it is purely EP-owned/structural, skip.
    if touched and not (touched & _GOVERNANCE_FIELDS):
        return []

    writes: List[CaWrite] = []

    description = entity.get("description")
    if description:
        writes.append(
            CaWrite(ep_path, ep_id, CA_EXTENDED_DESCRIPTION, str(description))
        )

    cert = _certification(entity)
    if cert:
        writes.append(CaWrite(ep_path, ep_id, CA_CERTIFICATION, cert))

    owners = _owner_names(entity)
    if owners:
        writes.append(
            CaWrite(ep_path, ep_id, CA_ADDITIONAL_OWNERS, ", ".join(owners))
        )

    # External-system linkage (#60 reverse): pushed only when OM carries the
    # value on a matching extension CP. No-op for entities that do not.
    for cp_key, ca_name in (
        (CA_EXTERNAL_SOURCE, CA_EXTERNAL_SOURCE),
        (CA_EXTERNAL_SINK, CA_EXTERNAL_SINK),
    ):
        value = extension.get(cp_key)
        if value:
            writes.append(CaWrite(ep_path, ep_id, ca_name, str(value)))

    return writes


class WritebackProcessor:
    """Queues OM change events and applies the implied EP writes on a worker
    thread. Dry-run logs + counts the planned writes without touching EP."""

    def __init__(self, *, settings, writer=None):
        self.settings = settings           # WritebackSettings
        self.writer = writer               # EventPortalWriter or None
        self._queue: "queue.Queue[dict]" = queue.Queue(
            maxsize=max(1, getattr(settings, "queue_max", 10000))
        )
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---- producer side -------------------------------------------------
    def enqueue(self, change_event: Dict[str, Any]) -> bool:
        if not self.settings.enabled:
            return False
        try:
            self._queue.put_nowait(change_event)
        except queue.Full:
            logger.warning("write-back queue full; dropping OM change event")
            metrics.record_writeback("dropped")
            return False
        metrics.set_writeback_queue_depth(self._queue.qsize())
        return True

    # ---- worker side ---------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="writeback-worker", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                change_event = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self.process(change_event)
            except Exception:  # noqa: BLE001 - one bad event must not kill the worker
                logger.exception("write-back failed for an OM change event")
                metrics.record_writeback("error")
            finally:
                self._queue.task_done()
                metrics.set_writeback_queue_depth(self._queue.qsize())

    def process(self, change_event: Dict[str, Any]) -> List[CaWrite]:
        """Apply (or dry-run) the writes for one change event. Returns the
        plan so callers/tests can assert on it."""
        writes = plan_writes(change_event)
        for w in writes:
            if self.settings.dry_run or self.writer is None:
                logger.info(
                    "[writeback dry-run] would set %s=%r on %s/%s",
                    w.ca_name, w.value, w.ep_entity_path, w.ep_entity_id,
                )
                metrics.record_writeback("dry_run")
            else:
                self.writer.set_entity_custom_attributes(
                    w.ep_entity_path,
                    w.ep_entity_id,
                    [{"name": w.ca_name, "value": w.value}],
                )
                metrics.record_writeback("applied")
        return writes

    def drain(self, timeout: float = 10.0) -> int:
        """Wait (up to ``timeout`` wall-clock) for the queue to empty, then
        stop the worker. Returns the number of items still queued (0 = fully
        drained).

        Uses a bounded poll rather than ``queue.join()`` so it can NEVER
        block indefinitely: if no worker is consuming (never started, or a
        late event arrived after the worker stopped) ``join()`` would hang
        forever with no ``task_done``. Safe to call when never started.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        while self._queue.qsize() and time.monotonic() < deadline:
            time.sleep(0.05)
        # Signal the worker to exit, then give an in-flight item the rest of
        # the budget to finish (the worker get()s with a 1s timeout).
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, deadline - time.monotonic()))
        remaining = self._queue.qsize()
        metrics.set_writeback_queue_depth(remaining)
        if remaining:
            logger.warning(
                "write-back drain timed out with %d events still queued", remaining
            )
        return remaining


# --------------------------------------------------------------------------- #
# Module-level processor registry (for the graceful-shutdown hook in #13).
# --------------------------------------------------------------------------- #

_PROCESSOR: Optional[WritebackProcessor] = None


def register_processor(processor: Optional[WritebackProcessor]) -> None:
    global _PROCESSOR
    _PROCESSOR = processor


def get_processor() -> Optional[WritebackProcessor]:
    return _PROCESSOR


def drain(timeout: float = 10.0) -> int:
    """Flush the registered processor's queue (called by lifecycle.shutdown).
    No-op (returns 0) when write-back is not running."""
    processor = _PROCESSOR
    if processor is None:
        return 0
    return processor.drain(timeout)


def ensure_writeback_ca_definitions(writer, dry_run: bool = True) -> List[str]:
    """Register the EP CA definitions write-back targets (idempotent).

    Returns the CA names ensured. In dry-run, only logs what would be
    created (the live POST is in EventPortalWriter, marked for contract
    verification)."""
    ensured: List[str] = []
    for name in WRITEBACK_CA_DEFINITIONS:
        if dry_run or writer is None:
            logger.info("[writeback dry-run] would ensure EP CA definition %s", name)
        else:
            writer.ensure_custom_attribute_definition(
                name, associated_entity_types=["application", "event"]
            )
        ensured.append(name)
    return ensured
