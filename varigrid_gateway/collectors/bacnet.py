"""BACnet/IP collector.

ASHRAE Standard 135 — the dominant protocol in commercial building
automation. Used by:
  - Honeywell BMS (Niagara, EBI)
  - Siemens BMS (Desigo CC, Apogee)
  - Johnson Controls Metasys
  - Many CRAC controllers (Stulz, Vertiv, Schneider in BACnet mode)
  - Chiller plant controllers

Reads ONE present-value from a BACnet object on a remote device.

Config:
  device_address: "10.20.1.60"             required (the BACnet device IP)
  device_id:      1001                     required (BACnet device instance)
  object_type:    "analogInput"            required — see _OBJECT_TYPES
  object_instance: 12                      required (instance number)
  property:       "presentValue"           default "presentValue"
  scale:          1.0                      default 1.0
  bbmd:           ""                       optional — BBMD address for routing
  bbmd_ttl:       3600                     default 3600

Object types supported:
  analogInput, analogOutput, analogValue,
  binaryInput, binaryOutput, binaryValue,
  multiStateInput, multiStateOutput, multiStateValue

Notes:
  - The agent itself becomes a BACnet device on the network (auto
    instance ID, configurable). Only ONE BAC0 instance can run per
    process — we share it across all BACnet collectors via _BAC_LOCK.
  - First read takes ~2-3s while BAC0 binds to the network and
    discovers the device; subsequent reads are fast.
  - On networks with multiple BACnet subnets, set `bbmd` to your
    BBMD IP so the gateway can reach across the broadcast domain.
"""
import asyncio
import logging
import threading
from typing import Optional

import BAC0

from .base import Collector

logger = logging.getLogger(__name__)


# BAC0 binds to one UDP socket per process (port 47808 by default).
# Lock so multiple collectors don't try to start the network at once.
_BAC_LOCK = threading.Lock()
_BAC_NETWORK: Optional[object] = None


_OBJECT_TYPES = {
    "analogInput", "analogOutput", "analogValue",
    "binaryInput", "binaryOutput", "binaryValue",
    "multiStateInput", "multiStateOutput", "multiStateValue",
}


def _ensure_network(bbmd: Optional[str] = None, bbmd_ttl: int = 3600):
    """Lazy-init the shared BAC0 network. Returns the BAC0 instance."""
    global _BAC_NETWORK
    with _BAC_LOCK:
        if _BAC_NETWORK is None:
            kwargs = {"bbmdAddress": bbmd, "bbmdTTL": bbmd_ttl} if bbmd else {}
            _BAC_NETWORK = BAC0.lite(**kwargs)
            logger.info("bacnet: BAC0 network started")
        return _BAC_NETWORK


class BacnetCollector(Collector):
    def __init__(self, sensor_id: str, config: dict):
        super().__init__(sensor_id, config)
        self.device_address  = config["device_address"]
        self.device_id       = int(config["device_id"])
        self.object_type     = config["object_type"]
        self.object_instance = int(config["object_instance"])
        self.property        = config.get("property", "presentValue")
        self.scale           = float(config.get("scale", 1.0))
        self.bbmd            = config.get("bbmd")
        self.bbmd_ttl        = int(config.get("bbmd_ttl", 3600))

        if self.object_type not in _OBJECT_TYPES:
            raise ValueError(
                f"BACnet object_type must be one of {sorted(_OBJECT_TYPES)}"
            )

    def _read_blocking(self) -> float:
        net = _ensure_network(self.bbmd, self.bbmd_ttl)
        # BAC0 read syntax: "<addr> <objType> <instance> <property>"
        # e.g. "10.20.1.60 analogInput 12 presentValue"
        request = f"{self.device_address} {self.object_type} {self.object_instance} {self.property}"
        result = net.read(request)
        if result is None:
            raise RuntimeError(
                f"BACnet read returned None for {request} (device unreachable?)"
            )
        return float(result) * self.scale

    async def read(self) -> float:
        # BAC0 calls are sync + chatty — run in a thread
        return await asyncio.to_thread(self._read_blocking)
