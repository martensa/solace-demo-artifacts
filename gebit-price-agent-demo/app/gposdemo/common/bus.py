"""Message bus: ``Bus`` protocol, ``SolaceBus`` (SMF) and ``MemoryBus`` (tests).

UC1-BUILD-SPEC 3.3 and 7.3: payloads are UTF-8 JSON text and go on the wire as a
``bytearray`` binary attachment (G0-13; ``bytes`` fails in the SDK, ``str`` becomes an
SDT string). User properties are strings; the application message id is set when
given. ``persistent=True`` publishes guaranteed and waits for the broker ack; the
outbox relay decides that per row (``outbox.is_persistent``). In the lab everything
is Direct (DMR backlog, finding 20).

Handlers run on the receiving thread (``SolaceBus``: the SDK dispatch thread;
``MemoryBus``: the publishing thread). A handler exception is logged and never
reaches the publisher.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from solace.messaging.config.retry_strategy import RetryStrategy
from solace.messaging.config.solace_properties import authentication_properties as auth
from solace.messaging.config.solace_properties import service_properties as svc
from solace.messaging.config.solace_properties import transport_layer_properties as tl
from solace.messaging.messaging_service import MessagingService
from solace.messaging.publisher.persistent_message_publisher import PersistentMessagePublisher
from solace.messaging.receiver.direct_message_receiver import DirectMessageReceiver
from solace.messaging.receiver.inbound_message import InboundMessage
from solace.messaging.receiver.message_receiver import MessageHandler
from solace.messaging.resources.topic import Topic
from solace.messaging.resources.topic_subscription import TopicSubscription

from .config import Settings

log = logging.getLogger(__name__)

Handler = Callable[[str, bytes, dict[str, str]], None]  # topic, payload, user props

ACK_TIMEOUT_MS = 5000
RECONNECT_INTERVAL_MS = 3000
CONNECT_RETRIES = 3


@runtime_checkable
class Bus(Protocol):
    """What publishers and subscribers of the demo need from a message bus."""

    def publish(self, topic: str, payload: str, *, persistent: bool = False,
                props: dict[str, str] | None = None,
                app_message_id: str | None = None) -> None:
        """Send ``payload`` (UTF-8 text) to ``topic``; raises when it cannot be sent."""
        ...

    def subscribe(self, topic_filter: str, handler: Handler) -> None:
        """Deliver every message matching ``topic_filter`` (Solace ``*``/``>``) to ``handler``."""
        ...

    def close(self) -> None:
        """Stop receiving and release the connection."""
        ...


def topic_matches(topic_filter: str, topic: str) -> bool:
    """Solace subscription semantics.

    ``*`` alone matches exactly one level; ``abc*`` at the end of a level matches
    levels starting with ``abc``; ``>`` as the last level matches one or more
    remaining levels. Elsewhere both characters are literal.
    """
    f_levels = topic_filter.split("/")
    t_levels = topic.split("/")
    for i, f in enumerate(f_levels):
        if f == ">" and i == len(f_levels) - 1:
            return len(t_levels) > i
        if i >= len(t_levels):
            return False
        if f.endswith("*"):
            if not t_levels[i].startswith(f[:-1]):
                return False
        elif f != t_levels[i]:
            return False
    return len(t_levels) == len(f_levels)


def _check_publish_topic(topic: str) -> None:
    if not topic or "*" in topic or ">" in topic or "//" in topic or topic.endswith("/"):
        raise ValueError(f"not a publishable topic: {topic!r}")


@dataclass(frozen=True)
class Published:
    """One message seen by :class:`MemoryBus`."""

    topic: str
    payload: bytes
    persistent: bool = False
    props: dict[str, str] = field(default_factory=dict)
    app_message_id: str | None = None

    def text(self) -> str:
        """Payload decoded as UTF-8."""
        return self.payload.decode("utf-8")

    def json(self) -> Any:
        """Payload parsed as JSON."""
        return json.loads(self.payload)


class _Subscriptions:
    """Filter -> handlers, matched locally (shared by both bus implementations)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[tuple[str, Handler]] = []

    def add(self, topic_filter: str, handler: Handler) -> bool:
        """Register; True when the filter is new (needs a broker subscription)."""
        with self._lock:
            new = all(f != topic_filter for f, _ in self._entries)
            self._entries.append((topic_filter, handler))
            return new

    def dispatch(self, topic: str, payload: bytes, props: dict[str, str]) -> list[Exception]:
        """Call every matching handler once; return the exceptions they raised."""
        with self._lock:
            targets = [h for f, h in self._entries if topic_matches(f, topic)]
        errors: list[Exception] = []
        for handler in dict.fromkeys(targets):
            try:
                handler(topic, payload, dict(props))
            except Exception as exc:  # noqa: BLE001 - a subscriber must not break the bus
                log.exception("handler for %s failed", topic)
                errors.append(exc)
        return errors


class MemoryBus:
    """In-process bus for tests (``GPOS_BUS=memory``): synchronous delivery, full record.

    ``published`` keeps every message in order; ``errors`` every handler exception.
    """

    def __init__(self) -> None:
        self.published: list[Published] = []
        self.errors: list[Exception] = []
        self._subs = _Subscriptions()
        self._cond = threading.Condition()
        self._closed = False

    def publish(self, topic: str, payload: str, *, persistent: bool = False,
                props: dict[str, str] | None = None,
                app_message_id: str | None = None) -> None:
        """Record the message, then deliver it to matching subscribers on this thread."""
        _check_publish_topic(topic)
        if self._closed:
            raise RuntimeError("bus is closed")
        msg = Published(topic, payload.encode("utf-8"), persistent,
                        {k: str(v) for k, v in (props or {}).items()}, app_message_id)
        with self._cond:
            self.published.append(msg)
            self._cond.notify_all()
        errors = self._subs.dispatch(msg.topic, msg.payload, msg.props)
        with self._cond:
            self.errors.extend(errors)

    def subscribe(self, topic_filter: str, handler: Handler) -> None:
        """Register ``handler`` for ``topic_filter``."""
        self._subs.add(topic_filter, handler)

    def messages(self, topic_filter: str = ">") -> list[Published]:
        """Recorded messages whose topic matches ``topic_filter``, oldest first."""
        with self._cond:
            return [m for m in self.published if topic_matches(topic_filter, m.topic)]

    def wait_for(self, topic_filter: str, count: int = 1, timeout: float = 5.0) -> list[Published]:
        """Block until ``count`` matching messages were published; ``TimeoutError`` else."""
        with self._cond:
            ok = self._cond.wait_for(
                lambda: sum(topic_matches(topic_filter, m.topic) for m in self.published)
                >= count, timeout)
            found = [m for m in self.published if topic_matches(topic_filter, m.topic)]
        if not ok:
            raise TimeoutError(f"{len(found)}/{count} messages on {topic_filter} "
                               f"after {timeout} s")
        return found

    def clear(self) -> None:
        """Forget recorded messages and errors (subscriptions stay)."""
        with self._cond:
            self.published.clear()
            self.errors.clear()

    def healthy(self) -> bool:
        """True until :meth:`close`."""
        return not self._closed

    def close(self) -> None:
        """Refuse further publishes."""
        self._closed = True


class _Dispatcher(MessageHandler):
    """SDK ``MessageHandler`` adapter: inbound message -> local handlers."""

    def __init__(self, subs: _Subscriptions):
        self._subs = subs

    def on_message(self, message: InboundMessage) -> None:
        try:
            topic = message.get_destination_name() or ""
            payload = message.get_payload_as_bytes()
            if payload is None:
                text = message.get_payload_as_string() or ""
                payload = text.encode("utf-8")
            props = {k: str(v) for k, v in (message.get_properties() or {}).items()}
        except Exception:  # noqa: BLE001 - never let the SDK thread die
            log.exception("cannot read inbound message")
            return
        self._subs.dispatch(topic, bytes(payload), props)


class SolaceBus:
    """SMF connection to the broker (``SOLACE_HOST``, VPN ``SOLACE_VPN``).

    Connects in the constructor (3 attempts, then the exception propagates and the
    pod restarts) and reconnects forever every 3 s afterwards. A publish during an
    outage raises; the outbox relay retries, telemetry drops the event.
    """

    def __init__(self, s: Settings, client_name: str):
        props = {
            tl.HOST: s.solace_host,
            svc.VPN_NAME: s.solace_vpn,
            auth.SCHEME_BASIC_USER_NAME: s.solace_username,
            auth.SCHEME_BASIC_PASSWORD: s.solace_password,
            svc.GENERATE_SENDER_ID: True,
            svc.GENERATE_SEND_TIMESTAMPS: True,
        }
        self.client_name = f"{client_name}-{uuid.uuid4().hex[:6]}"
        self._service: MessagingService = (
            MessagingService.builder().from_properties(props)
            .with_connection_retry_strategy(
                RetryStrategy.parametrized_retry(CONNECT_RETRIES, RECONNECT_INTERVAL_MS))
            .with_reconnection_retry_strategy(RetryStrategy.forever_retry(RECONNECT_INTERVAL_MS))
            .build(self.client_name))
        self._service.connect()
        self._direct = self._service.create_direct_message_publisher_builder().build()
        self._direct.start()
        self._persistent: PersistentMessagePublisher | None = None
        self._receiver: DirectMessageReceiver | None = None
        self._subs = _Subscriptions()
        # one lock per SDK object: a guaranteed send waiting for its ack (up to 5 s)
        # never holds up Direct sends such as telemetry
        self._direct_lock = threading.Lock()
        self._persistent_lock = threading.Lock()
        self._receiver_lock = threading.Lock()
        log.info("SMF connected to %s vpn %s as %s", s.solace_host, s.solace_vpn,
                 self.client_name)

    def _message(self, payload: str, props: dict[str, str] | None,
                 app_message_id: str | None) -> Any:
        builder = (self._service.message_builder()
                   .with_http_content_header("application/json", "utf-8"))
        if app_message_id:
            builder = builder.with_application_message_id(app_message_id)
        for key, value in (props or {}).items():
            builder = builder.with_property(key, str(value))
        return builder.build(bytearray(payload.encode("utf-8")))

    def _persistent_publisher(self) -> PersistentMessagePublisher:
        if self._persistent is None:
            self._persistent = self._service.create_persistent_message_publisher_builder().build()
            self._persistent.start()
        return self._persistent

    def publish(self, topic: str, payload: str, *, persistent: bool = False,
                props: dict[str, str] | None = None,
                app_message_id: str | None = None) -> None:
        """Direct send, or guaranteed send that returns after the broker ack (5 s max)."""
        _check_publish_topic(topic)
        msg = self._message(payload, props, app_message_id)
        if persistent:
            with self._persistent_lock:
                self._persistent_publisher().publish_await_acknowledgement(
                    msg, Topic.of(topic), time_out=ACK_TIMEOUT_MS)
        else:
            with self._direct_lock:
                self._direct.publish(msg, Topic.of(topic))

    def subscribe(self, topic_filter: str, handler: Handler) -> None:
        """Direct subscription; one receiver serves all filters of this bus."""
        if not self._subs.add(topic_filter, handler):
            return
        with self._receiver_lock:
            if self._receiver is None:
                self._receiver = (self._service.create_direct_message_receiver_builder()
                                  .with_subscriptions([TopicSubscription.of(topic_filter)])
                                  .build())
                self._receiver.start()
                self._receiver.receive_async(_Dispatcher(self._subs))
            else:
                self._receiver.add_subscription(TopicSubscription.of(topic_filter))

    def healthy(self) -> bool:
        """True while the SMF session is up."""
        return bool(self._service.is_connected)

    def close(self) -> None:
        """Terminate publishers and receiver, then disconnect (errors are logged)."""
        for part in (self._receiver, self._persistent, self._direct):
            if part is None:
                continue
            try:
                part.terminate(grace_period=2000)
            except Exception:  # noqa: BLE001 - best effort on shutdown
                log.warning("terminate %s failed", type(part).__name__, exc_info=True)
        try:
            self._service.disconnect()
        except Exception:  # noqa: BLE001 - best effort on shutdown
            log.warning("disconnect failed", exc_info=True)


def make_bus(s: Settings, client_name: str) -> Bus:
    """``MemoryBus`` for ``GPOS_BUS=memory``, else a connected ``SolaceBus``.

    The broker client name is ``client_name`` plus a random suffix, so a restarted
    pod never collides with its predecessor's session.
    """
    if s.bus_kind == "memory":
        return MemoryBus()
    return SolaceBus(s, client_name)
