"""Postgres access: small connection pool, transactions, ``LISTEN`` (UC1-BUILD-SPEC 2.4).

Every connection uses ``row_factory=dict_row``: ``conn.execute(...).fetchone()``
returns a ``dict`` keyed by column name, in ``tx()`` as well as in ``fetch()``.
Each service connects with its own role; ``search_path`` is set per role and
database by ``00-roles.sql``. Qualify the schema in SQL anyway (``wws.article``):
the engine also reads ``pos``.

The DSN contains a password and is never logged.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import sql as pgsql
from psycopg.rows import dict_row

log = logging.getLogger(__name__)

Params = Sequence[Any] | Mapping[str, Any]
LISTEN_RETRY_S = 2.0


class Db:
    """Thread-safe pool of at most ``max_size`` connections to one database.

    Connections are opened lazily; a connection that broke is discarded instead of
    returned. ``close()`` closes the idle connections and stops all ``listen`` threads.
    """

    def __init__(self, dsn: str, max_size: int = 5, *, application_name: str = "gpos"):
        if max_size < 1:
            raise ValueError("max_size must be at least 1")
        self._dsn = dsn
        self._app = application_name
        self._idle: queue.LifoQueue[psycopg.Connection[dict[str, Any]]] = queue.LifoQueue()
        self._slots = threading.BoundedSemaphore(max_size)
        self._stop = threading.Event()

    def _connect(self, *, autocommit: bool = False) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(
            self._dsn,
            autocommit=autocommit,
            row_factory=dict_row,
            connect_timeout=5,
            application_name=self._app,
        )

    def _acquire(self) -> psycopg.Connection[dict[str, Any]]:
        self._slots.acquire()
        try:
            while True:
                try:
                    conn = self._idle.get_nowait()
                except queue.Empty:
                    return self._connect()
                if not conn.closed:
                    return conn
        except BaseException:
            self._slots.release()
            raise

    def _release(self, conn: psycopg.Connection[dict[str, Any]], broken: bool) -> None:
        try:
            if broken or conn.closed or self._stop.is_set():
                conn.close()
            else:
                self._idle.put(conn)
        finally:
            self._slots.release()

    @contextmanager
    def tx(self) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        """One transaction: commit when the block succeeds, roll back when it raises."""
        conn = self._acquire()
        broken = False
        try:
            yield conn
            conn.commit()
        except BaseException:
            broken = conn.closed or conn.broken
            if not broken:
                try:
                    conn.rollback()
                except psycopg.Error:
                    broken = True
            raise
        finally:
            self._release(conn, broken or conn.broken)

    def fetch(self, sql: str, params: Params = ()) -> list[dict[str, Any]]:
        """Run one statement in its own transaction and return all rows as dicts.

        A statement without a result set (``insert`` without ``returning``) returns ``[]``.
        """
        with self.tx() as conn:
            cur = conn.execute(sql, params)
            return cur.fetchall() if cur.description else []

    def ping(self) -> bool:
        """True when ``select 1`` succeeds (``/health`` reports it as ``db``)."""
        try:
            return self.fetch("select 1 as ok") == [{"ok": 1}]
        except psycopg.Error:
            return False

    def listen(self, channel: str, on_notify: Callable[[], None]) -> threading.Thread:
        """Start a daemon thread that calls ``on_notify()`` for every ``NOTIFY channel``.

        The thread owns a dedicated autocommit connection (outside the pool) and
        reconnects after errors; it ends when :meth:`close` is called.
        """
        thread = threading.Thread(
            target=self._listen_loop, args=(channel, on_notify), name=f"listen-{channel}",
            daemon=True,
        )
        thread.start()
        return thread

    def _listen_loop(self, channel: str, on_notify: Callable[[], None]) -> None:
        while not self._stop.is_set():
            try:
                with self._connect(autocommit=True) as conn:
                    conn.execute(pgsql.SQL("listen {}").format(pgsql.Identifier(channel)))
                    while not self._stop.is_set():
                        for _ in conn.notifies(timeout=1.0):
                            on_notify()
            except psycopg.Error as exc:
                log.warning("listen %s: %s; retrying in %.0f s", channel, exc, LISTEN_RETRY_S)
                self._stop.wait(LISTEN_RETRY_S)

    def close(self) -> None:
        """Close idle connections and stop the ``listen`` threads (within about 1 s)."""
        self._stop.set()
        while True:
            try:
                self._idle.get_nowait().close()
            except queue.Empty:
                return
