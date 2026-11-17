"""Transactional outbox: writer with offsets and the publishing relay (UC1-BUILD-SPEC 5.1).

Writers add rows in the same transaction as their business change and notify
``<schema>_outbox``. The relay listens, also polls every second, publishes in ``id``
order and sets ``published_at`` (Direct: after sending; persistent: after the ack).

Offsets: the producer gets the offset *before* building the payload (it is part of
``metadata.offset``) and passes it to ``add`` in the same transaction.

* ``pos``: aggregate ``tx_id``, offset ``pos.basket.last_offset + 1`` under the basket
  row lock (the POS does not need :meth:`OutboxWriter.next_offset`).
* ``wws``: aggregate ``"<article_number>:<store_id>"``, :meth:`OutboxWriter.next_offset`.
* ``engine`` (engine and gate): aggregate ``review_id`` / ``proposal_id``,
  :meth:`OutboxWriter.next_offset` under the review / proposal row lock.

Delivery class per row (3.3): ``sam_input`` and ``business`` are persistent when
``GPOS_DELIVERY=persistent``; ``ui`` and ``telemetry`` are always Direct.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from .bus import Bus
from .config import Settings
from .db import Db

log = logging.getLogger(__name__)

DELIVERY_CLASSES = ("sam_input", "business", "ui", "telemetry")
PERSISTENT_CLASSES = ("sam_input", "business")
POLL_INTERVAL_S = 1.0
BATCH_SIZE = 200

_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

Connection = psycopg.Connection[Any]


def _schema(schema: str) -> str:
    if not _SCHEMA.match(schema):
        raise ValueError(f"not a schema name: {schema!r}")
    return schema


def notify_channel(schema: str) -> str:
    """``LISTEN``/``NOTIFY`` channel of the outbox of ``schema``: ``<schema>_outbox``."""
    return f"{_schema(schema)}_outbox"


def is_persistent(delivery_class: str, delivery: str) -> bool:
    """True when a row of ``delivery_class`` is published guaranteed under ``delivery``."""
    if delivery_class not in DELIVERY_CLASSES:
        raise ValueError(f"unknown delivery class {delivery_class!r}")
    return delivery == "persistent" and delivery_class in PERSISTENT_CLASSES


class OutboxWriter:
    """Adds rows to ``<schema>.event_outbox`` inside the caller's transaction."""

    def __init__(self, schema: str):
        self.schema = _schema(schema)
        self._table = sql.Identifier(self.schema, "event_outbox")

    def next_offset(self, conn: Connection, aggregate_id: str) -> int:
        """Next offset of ``aggregate_id``: ``coalesce(max(aggregate_offset), 0) + 1``.

        Takes ``pg_advisory_xact_lock(hashtext('<schema>:<aggregate_id>'))`` first, so two
        processes (engine and gate) never hand out the same offset; the lock is held
        until the caller's transaction ends, so call :meth:`add` in that transaction.
        """
        conn.execute("select pg_advisory_xact_lock(hashtext(%s))",
                     (f"{self.schema}:{aggregate_id}",))
        row = conn.execute(
            sql.SQL("select coalesce(max(aggregate_offset), 0) + 1 as next "
                    "from {} where aggregate_id = %s").format(self._table),
            (aggregate_id,)).fetchone()
        return int(_value(row, "next"))

    def add(self, conn: Connection, *, aggregate_id: str, aggregate_offset: int,
            event_type: str, topic: str, payload_text: str, delivery_class: str,
            user_props: dict[str, str] | None = None) -> None:
        """Insert one row (``app_message_id = "<aggregate_id>:<aggregate_offset>"``) and
        ``pg_notify('<schema>_outbox', '')``; both take effect on commit."""
        if delivery_class not in DELIVERY_CLASSES:
            raise ValueError(f"unknown delivery class {delivery_class!r}")
        if aggregate_offset < 1:
            raise ValueError(f"aggregate_offset must be positive, got {aggregate_offset}")
        props = {k: str(v) for k, v in (user_props or {}).items()}
        conn.execute(
            sql.SQL("insert into {} (aggregate_id, aggregate_offset, event_type, topic, "
                    "payload_text, delivery_class, user_props, app_message_id) "
                    "values (%s, %s, %s, %s, %s, %s, %s, %s)").format(self._table),
            (aggregate_id, aggregate_offset, event_type, topic, payload_text, delivery_class,
             Jsonb(props), f"{aggregate_id}:{aggregate_offset}"))
        conn.execute("select pg_notify(%s, '')", (notify_channel(self.schema),))


def _value(row: Any, key: str) -> Any:
    """Column of a dict row (``Db``) or the first column of a tuple row."""
    return row[key] if isinstance(row, dict) else row[0]


class OutboxRelay(threading.Thread):
    """Publishes unpublished rows of ``<schema>.event_outbox`` in ``id`` order.

    One relay per schema (single replica). Wakes on ``NOTIFY``, on :meth:`kick` and at
    least every second. A failed publish stops the batch; the row stays unpublished
    and the next round retries it, so order per schema is kept.
    """

    def __init__(self, db: Db, schema: str, bus: Bus, s: Settings):
        super().__init__(name=f"outbox-{schema}", daemon=True)
        self.schema = _schema(schema)
        self._db = db
        self._bus = bus
        self._delivery = s.delivery
        self._table = sql.Identifier(self.schema, "event_outbox")
        self._wake = threading.Event()
        self._halt = threading.Event()

    def kick(self) -> None:
        """Publish now instead of waiting for the next poll (call after commit)."""
        self._wake.set()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the loop and wait for the thread to end."""
        self._halt.set()
        self._wake.set()
        if self.is_alive():
            self.join(timeout)

    def run(self) -> None:
        self._db.listen(notify_channel(self.schema), self.kick)
        while not self._halt.is_set():
            try:
                while self.drain() == BATCH_SIZE and not self._halt.is_set():
                    pass
            except psycopg.Error as exc:
                log.warning("outbox %s: %s", self.schema, exc)
            except Exception:  # noqa: BLE001 - the relay thread must survive any round
                log.exception("outbox %s: relay round failed", self.schema)
            self._wake.wait(POLL_INTERVAL_S)
            self._wake.clear()

    def drain(self) -> int:
        """Publish up to one batch of pending rows now; return how many were published.

        Rows are locked with ``for update skip locked`` while they are sent.
        """
        published = 0
        with self._db.tx() as conn:
            rows = conn.execute(
                sql.SQL("select id, topic, payload_text, delivery_class, user_props, "
                        "app_message_id from {} where published_at is null "
                        "order by id limit %s for update skip locked").format(self._table),
                (BATCH_SIZE,)).fetchall()
            for row in rows:
                if not self._send(row):
                    break
                conn.execute(sql.SQL("update {} set published_at = now() where id = %s")
                             .format(self._table), (row["id"],))
                published += 1
        return published

    def _send(self, row: dict[str, Any]) -> bool:
        try:
            self._bus.publish(
                row["topic"], row["payload_text"],
                persistent=is_persistent(row["delivery_class"], self._delivery),
                props={k: str(v) for k, v in (row["user_props"] or {}).items()},
                app_message_id=row["app_message_id"])
        except Exception as exc:  # noqa: BLE001 - any bus failure means: retry later
            log.warning("outbox %s: publish of row %s failed: %s", self.schema, row["id"], exc)
            return False
        return True
