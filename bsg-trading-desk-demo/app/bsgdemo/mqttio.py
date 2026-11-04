"""Thin MQTT helper around paho-mqtt 2.x.

Market data on exchanges is commonly distributed over MQTT from the
Solace appliances, so every demo component talks MQTT to solace-1
(plain MQTT port 1883 of the sam VPN). Configuration comes from the
environment; the password from a Kubernetes Secret.

  MQTT_HOST       host.docker.internal
  MQTT_PORT       1883
  MQTT_USERNAME   default
  MQTT_PASSWORD   (Secret bsg-broker)
  MQTT_CLIENT_ID  <component>-<random>
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Callable

import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)

Handler = Callable[[str, Any], None]


def now_ms() -> int:
    return int(time.time() * 1000)


class Bus:
    """One MQTT connection with JSON publish and dispatch by filter."""

    def __init__(self, component: str, subscriptions: list[str] | None = None,
                 on_message: Handler | None = None) -> None:
        self.component = component
        self.subscriptions = list(subscriptions or [])
        self.on_message = on_message
        self.connected = threading.Event()
        cid = os.environ.get("MQTT_CLIENT_ID") or f"{component}-{uuid.uuid4().hex[:6]}"
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=cid,
            protocol=mqtt.MQTTv311,
        )
        user = os.environ.get("MQTT_USERNAME", "default")
        pwd = os.environ.get("MQTT_PASSWORD", "")
        self.client.username_pw_set(user, pwd)
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.host = os.environ.get("MQTT_HOST", "host.docker.internal")
        self.port = int(os.environ.get("MQTT_PORT", "1883"))

    # -- lifecycle --------------------------------------------------------
    def start(self, wait_s: float = 15.0) -> "Bus":
        log.info("%s: connecting to mqtt://%s:%d", self.component, self.host, self.port)
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()
        if not self.connected.wait(wait_s):
            log.warning("%s: no MQTT connection after %.0fs (retrying in background)",
                        self.component, wait_s)
        return self

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    # -- callbacks --------------------------------------------------------
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("%s: MQTT connect failed: %s", self.component, reason_code)
            return
        for sub in self.subscriptions:
            client.subscribe(sub, qos=0)
        log.info("%s: connected, subscribed %s", self.component, self.subscriptions)
        self.connected.set()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected.clear()
        log.warning("%s: MQTT disconnected (%s)", self.component, reason_code)

    def _on_message(self, client, userdata, msg):
        if self.on_message is None:
            return
        try:
            payload: Any = json.loads(msg.payload.decode("utf-8")) if msg.payload else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = msg.payload.decode("utf-8", "replace")
        try:
            self.on_message(msg.topic, payload)
        except Exception:  # noqa: BLE001 -- one bad message must not kill the loop
            log.exception("%s: handler failed for %s", self.component, msg.topic)

    # -- publish ----------------------------------------------------------
    def publish(self, topic: str, payload: Any, qos: int = 0) -> None:
        data = payload if isinstance(payload, (bytes, str)) else json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"))
        self.client.publish(topic, data, qos=qos)
