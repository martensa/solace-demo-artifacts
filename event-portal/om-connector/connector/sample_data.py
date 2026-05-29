"""Live sample-data ingestion from a Solace broker.

When `sampleDataEnabled=true` and broker credentials are supplied, the
connector subscribes to each ingested Topic's reconstructed Solace
topic address for a short window, captures up to N payloads, and pushes
them to OpenMetadata via the Topic sample-data endpoint.

This is opt-in for two reasons:
  * Live messages can be sensitive — turning sample collection on is an
    explicit governance decision.
  * The collector adds a runtime dependency on `solace-pubsubplus` and
    a network path from the ingestion pod to the broker.

Memory + safety guards:
  * `max_messages` per Topic (default 5)
  * `max_bytes` per Topic across all captured payloads (default 64 KiB)
  * `collect_timeout_seconds` per Topic (default 10s)
  * payloads are decoded as UTF-8 with replacement; binary content is
    represented as `<binary N bytes>`.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_MAX_MESSAGES = 5
DEFAULT_MAX_BYTES = 64 * 1024
DEFAULT_TIMEOUT = 10  # seconds


@dataclass
class BrokerConfig:
    host: str
    vpn: str
    username: str
    password: str
    use_tls: bool = False

    @classmethod
    def from_options(cls, opts: Dict[str, Any]) -> Optional["BrokerConfig"]:
        if not opts.get("brokerHost"):
            return None
        host = str(opts["brokerHost"])
        return cls(
            host=host,
            vpn=str(opts.get("brokerVpn") or "default"),
            username=str(opts.get("brokerUsername") or ""),
            password=str(opts.get("brokerPassword") or ""),
            use_tls=host.startswith("tcps://") or host.startswith("wss://"),
        )


@dataclass
class CollectedSample:
    """Outcome of one sample-collection round per Topic."""

    topic_fqn: str
    topic_address: str
    messages: List[str] = field(default_factory=list)
    truncated: bool = False
    error: Optional[str] = None


class SampleDataCollector:
    """Per-connector-run collector. Reuses one Solace connection."""

    def __init__(
        self,
        broker: BrokerConfig,
        *,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        max_bytes: int = DEFAULT_MAX_BYTES,
        timeout_seconds: int = DEFAULT_TIMEOUT,
    ):
        self.broker = broker
        self.max_messages = max_messages
        self.max_bytes = max_bytes
        self.timeout = timeout_seconds
        self._service = None  # lazy-connected solace MessagingService

    # ------------------------------------------------------------ lifecycle

    def __enter__(self) -> "SampleDataCollector":
        self._connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._service is not None:
            try:
                self._service.disconnect()
            except Exception:
                logger.exception("Solace service disconnect failed")
            self._service = None

    def _connect(self) -> None:
        try:
            from solace.messaging.config.transport_security_strategy import TLS
            from solace.messaging.messaging_service import MessagingService
        except ImportError as exc:  # pragma: no cover - optional dep
            raise RuntimeError(
                "solace-pubsubplus is required for sample data. "
                "Install with: pip install '.[sample-data]'"
            ) from exc

        props = {
            "solace.messaging.transport.host": self.broker.host,
            "solace.messaging.service.vpn-name": self.broker.vpn,
            "solace.messaging.authentication.scheme.basic.username":
                self.broker.username,
            "solace.messaging.authentication.scheme.basic.password":
                self.broker.password,
        }
        builder = MessagingService.builder().from_properties(props)
        if self.broker.use_tls:
            builder = builder.with_transport_security_strategy(
                TLS.create().without_certificate_validation()
            )
        self._service = builder.build()
        self._service.connect()
        logger.info(
            "SampleDataCollector connected host=%s vpn=%s",
            self.broker.host, self.broker.vpn,
        )

    # ---------------------------------------------------------------- collect

    def collect(self, topic_fqn: str, topic_address: str) -> CollectedSample:
        """Subscribe to `topic_address`, capture up to max_messages payloads.

        Best-effort: any error from the broker leaves the sample empty
        with `error` populated. Never raises.
        """
        if self._service is None:
            return CollectedSample(
                topic_fqn=topic_fqn,
                topic_address=topic_address,
                error="not connected",
            )

        try:
            from solace.messaging.receiver.message_receiver import MessageHandler
            from solace.messaging.resources.topic_subscription import (
                TopicSubscription,
            )
        except ImportError as exc:  # pragma: no cover
            return CollectedSample(
                topic_fqn=topic_fqn, topic_address=topic_address,
                error=f"solace-pubsubplus import failed: {exc}",
            )

        collected: List[str] = []
        total_bytes = 0
        done = threading.Event()
        truncated = False

        class _Handler(MessageHandler):
            def on_message(self, message):
                nonlocal total_bytes, truncated
                if done.is_set():
                    return
                payload = _decode(message)
                size = len(payload.encode("utf-8", errors="replace"))
                if len(collected) >= self.max_messages or total_bytes + size > self.max_bytes:
                    truncated = True
                    done.set()
                    return
                collected.append(payload)
                total_bytes += size
                if len(collected) >= self.max_messages:
                    done.set()

        receiver = (
            self._service.create_direct_message_receiver_builder()
            .with_subscriptions([TopicSubscription.of(topic_address)])
            .build()
        )
        try:
            receiver.start()
            receiver.receive_async(_Handler())
            done.wait(timeout=self.timeout)
        except Exception as exc:
            return CollectedSample(
                topic_fqn=topic_fqn, topic_address=topic_address,
                messages=collected, error=str(exc),
            )
        finally:
            try:
                receiver.terminate(grace_period=1)
            except Exception:
                pass

        return CollectedSample(
            topic_fqn=topic_fqn,
            topic_address=topic_address,
            messages=collected,
            truncated=truncated,
        )

    # -------------------------------------------------------------- push

    @staticmethod
    def push_to_om(om, sample: CollectedSample) -> None:
        """PUT sample messages onto the Topic via the OM REST API.

        OM exposes `/topics/<id>/sampleData` (PUT). Silent on errors; the
        rest of the ingest must keep going.
        """
        if not sample.messages:
            return
        try:
            topic = om.client.get(f"/topics/name/{sample.topic_fqn}")
        except Exception as exc:
            logger.debug(
                "Could not fetch Topic %s for sample push: %s",
                sample.topic_fqn, exc,
            )
            return
        if not topic or not topic.get("id"):
            return
        body = {"messages": sample.messages}
        try:
            om.client.put(f"/topics/{topic['id']}/sampleData", data=body)
        except Exception:
            logger.exception(
                "Failed to PUT sample data for %s", sample.topic_fqn
            )


# ------------------------------------------------------------------ helpers


def _decode(message) -> str:
    """Best-effort payload-to-string. Falls back to a hint for binary content."""
    try:
        raw = message.get_payload_as_bytes() or b""
    except Exception:
        return "<unavailable payload>"
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return f"<binary {len(raw)} bytes>"
