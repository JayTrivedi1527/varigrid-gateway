"""MQTT subscriber collector.

Used when a customer already publishes sensor data to their own MQTT
broker — common with modern OT/IIoT stacks, Mosquitto deployments,
and any HiveMQ / EMQX install. Lets us hook into existing telemetry
without polling.

Config:
  broker_host:  "10.20.1.42"        required
  broker_port:  1883                default 1883 (8883 for TLS)
  topic:        "facility/it/power" required
  qos:          0                   default 0
  tls:          false               default false
  username:     "varigrid"          optional
  password:     "secret"            optional
  json_path:    "data.value"        optional — pull a nested field
  scale:        1.0                 default 1.0

Behaviour:
  - Connects on first read(), subscribes to `topic`, keeps the
    subscription alive in paho's background network thread.
  - read() returns the LATEST cached message; raises if no message
    received yet (the runner will buffer the failure and retry).
  - Same MQTT client is shared across collectors that point at the
    same broker (per (host, port) tuple) — paho is fine with multiple
    subscriptions on one connection.

Wildcards (e.g. "racks/+/temp") work in the topic, but each collector
expects ONE numeric value out — if the topic matches multiple sensors,
the cached value is whichever arrived last. Use distinct topics per
sensor for clean semantics.
"""
import asyncio
import json
import logging
import threading
from typing import Optional, Any

import paho.mqtt.client as mqtt

from .base import Collector

logger = logging.getLogger(__name__)


class MqttCollector(Collector):
    def __init__(self, sensor_id: str, config: dict):
        super().__init__(sensor_id, config)
        self.host      = config["broker_host"]
        self.port      = int(config.get("broker_port", 1883))
        self.topic     = config["topic"]
        self.qos       = int(config.get("qos", 0))
        self.tls       = bool(config.get("tls", False))
        self.username  = config.get("username")
        self.password  = config.get("password")
        self.json_path = config.get("json_path")
        self.scale     = float(config.get("scale", 1.0))

        self._latest:    Optional[float] = None
        self._client:    Optional[mqtt.Client] = None
        self._connected = False
        self._lock      = threading.Lock()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self._connected = True
            client.subscribe(self.topic, qos=self.qos)
            logger.info("mqtt sensor=%s connected to %s:%d, subscribed to %s",
                        self.sensor_id, self.host, self.port, self.topic)
        else:
            logger.warning("mqtt sensor=%s connect failed rc=%s", self.sensor_id, rc)

    def _on_disconnect(self, *args, **kwargs):
        self._connected = False

    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8").strip()
            value: Any
            if self.json_path:
                doc = json.loads(payload)
                for key in self.json_path.split("."):
                    doc = doc[key]
                value = doc
            else:
                # Try plain number, else assume JSON {"value": ...}
                try:
                    value = float(payload)
                except ValueError:
                    doc = json.loads(payload)
                    value = doc.get("value", doc)
            with self._lock:
                self._latest = float(value) * self.scale
        except Exception as e:
            logger.warning("mqtt sensor=%s payload parse failed: %s | raw=%r",
                           self.sensor_id, e, msg.payload[:200])

    def _connect_blocking(self) -> None:
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"varigrid-{self.sensor_id[:8]}",
            clean_session=True,
        )
        if self.tls:
            client.tls_set()
        if self.username:
            client.username_pw_set(self.username, self.password or "")
        client.on_connect    = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message    = self._on_message
        client.connect(self.host, self.port, keepalive=60)
        client.loop_start()   # spawns paho's background thread
        self._client = client

    async def read(self) -> float:
        if self._client is None:
            await asyncio.to_thread(self._connect_blocking)
        # Give the broker a moment on the very first call
        if self._latest is None:
            for _ in range(20):       # up to 2s
                if self._latest is not None:
                    break
                await asyncio.sleep(0.1)
        with self._lock:
            v = self._latest
        if v is None:
            raise RuntimeError(
                f"No MQTT message received yet on {self.topic} (broker {self.host}:{self.port})"
            )
        return v

    async def close(self) -> None:
        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
