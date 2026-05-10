"""OPC UA collector.

The industrial-standard protocol used by SCADA systems and modern
BMS/EMS platforms. Common in:
  - Hyperscale operators with custom SCADA
  - Modern data centers with Wonderware / Ignition / Siemens WinCC
  - Power-grid analytics platforms

Reads ONE value from a single OPC UA node.

Config:
  endpoint:  "opc.tcp://10.20.1.50:4840"   required
  node_id:   "ns=2;s=Facility.PowerKW"     required (NodeId in OPC UA syntax)
  scale:     1.0                           default 1.0
  username:  "varigrid"                    optional
  password:  "secret"                      optional
  security_policy: "None" | "Basic256Sha256"   default "None"
  security_mode:   "None" | "Sign" | "SignAndEncrypt"   default "None"
  timeout_s: 5                             default 5

NodeId formats:
  ns=2;s=My.String.NodeId        — string identifier
  ns=2;i=12345                   — numeric identifier
  ns=2;g=GUID                    — GUID identifier
  ns=2;b=base64                  — opaque bytes

Most servers expose telemetry under namespace 2 with string IDs that
mirror the device tree. Browse with UaExpert (free) to find them.

Notes:
  - One client per (endpoint, credentials) — connections are pooled
    via _CLIENT_CACHE so 50 sensors on the same SCADA don't open 50
    sockets.
  - Auto-reconnects on disconnect; the runner's retry/buffer cycle
    handles the gap.
"""
import asyncio
import logging
from typing import Optional, Dict, Tuple

from asyncua import Client, ua

from .base import Collector

logger = logging.getLogger(__name__)


# Pool clients by (endpoint, user) — many sensors usually share a server
_CLIENT_CACHE: Dict[Tuple[str, str], Client] = {}
_CACHE_LOCK = asyncio.Lock()


class OpcuaCollector(Collector):
    def __init__(self, sensor_id: str, config: dict):
        super().__init__(sensor_id, config)
        self.endpoint        = config["endpoint"]
        self.node_id         = config["node_id"]
        self.scale           = float(config.get("scale", 1.0))
        self.username        = config.get("username")
        self.password        = config.get("password")
        self.security_policy = config.get("security_policy", "None")
        self.security_mode   = config.get("security_mode", "None")
        self.timeout_s       = int(config.get("timeout_s", 5))

        if not self.endpoint.startswith(("opc.tcp://", "opc.https://")):
            raise ValueError("endpoint must start with opc.tcp:// or opc.https://")

    def _cache_key(self) -> Tuple[str, str]:
        return (self.endpoint, self.username or "")

    async def _get_client(self) -> Client:
        key = self._cache_key()
        async with _CACHE_LOCK:
            client = _CLIENT_CACHE.get(key)
            if client is None or not getattr(client, "uaclient", None):
                client = Client(url=self.endpoint, timeout=self.timeout_s)
                if self.username:
                    client.set_user(self.username)
                    if self.password:
                        client.set_password(self.password)
                if self.security_policy != "None":
                    # Best-effort security setup; full cert pinning is
                    # caller's responsibility (would need cert paths in config)
                    try:
                        await client.set_security_string(
                            f"{self.security_policy},{self.security_mode}"
                        )
                    except Exception as e:
                        logger.warning("opcua security setup failed: %s", e)
                await client.connect()
                _CLIENT_CACHE[key] = client
                logger.info("opcua connected to %s", self.endpoint)
            return client

    async def read(self) -> float:
        client = await self._get_client()
        try:
            node  = client.get_node(self.node_id)
            value = await node.read_value()
            return float(value) * self.scale
        except (ConnectionError, ua.UaError, OSError) as e:
            # Drop the dead client so next call re-connects
            async with _CACHE_LOCK:
                _CLIENT_CACHE.pop(self._cache_key(), None)
            try: await client.disconnect()
            except Exception: pass
            raise RuntimeError(f"OPC UA read failed: {e}")

    async def close(self) -> None:
        # Don't close the shared client here — others might still use it.
        # The runner shutdown closes all collectors; we let the cache leak
        # at process exit (cheap).
        pass
