"""SNMP v2c / v3 collector.

The biggest single coverage gain after Modbus TCP — covers:
  - Most enterprise UPS (APC Galaxy, Eaton 9PX/93PM, Vertiv Liebert NX)
  - All smart PDUs (Raritan PX, Vertiv Geist, APC measured rPDUs)
  - Many enterprise switches / firewalls (rarely useful for DC ops, but
    occasionally for power draw)

Config (v2c — most common):
  ip:        "10.20.1.18"           required
  port:      161                    default 161
  version:   "v2c"                  default "v2c"
  community: "public"               required for v2c
  oid:       "1.3.6.1.2.1.33.1.4.4.1.4.1"   required (the OID to GET)
  scale:     1.0                    default 1.0
  timeout_s: 5                      default 5
  retries:   1                      default 1

Config (v3):
  version:   "v3"
  user:      "varigrid"             required for v3
  auth_key:  "secret123"            required if auth_protocol set
  auth_protocol: "MD5" | "SHA"      default no-auth
  priv_key:  "secret456"            required if priv_protocol set
  priv_protocol: "DES" | "AES"      default no-priv

Common UPS OIDs (RFC 1628 UPS-MIB) — many vendors implement these:
  1.3.6.1.2.1.33.1.4.4.1.4.1   upsOutputPower (W) — output kW
  1.3.6.1.2.1.33.1.4.1.0       upsOutputSource — 1=other 2=none 3=normal
  1.3.6.1.2.1.33.1.2.4.0       upsEstimatedMinutesRemaining
  1.3.6.1.2.1.33.1.2.2.0       upsBatteryStatus

Vendor-specific examples:
  APC: PowerNet-MIB        1.3.6.1.4.1.318.1.1.1...
  Eaton: XUPS-MIB          1.3.6.1.4.1.534...
  Raritan PX: PDU2-MIB     1.3.6.1.4.1.13742.6.5...
"""
import asyncio
import logging
from typing import Optional

from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine, CommunityData, UsmUserData,
    UdpTransportTarget, ContextData,
    ObjectType, ObjectIdentity,
    get_cmd,
    usmHMACMD5AuthProtocol, usmHMACSHAAuthProtocol,
    usmDESPrivProtocol, usmAesCfb128Protocol,
)

from .base import Collector

logger = logging.getLogger(__name__)


_AUTH_MAP = {
    "MD5": usmHMACMD5AuthProtocol,
    "SHA": usmHMACSHAAuthProtocol,
}
_PRIV_MAP = {
    "DES": usmDESPrivProtocol,
    "AES": usmAesCfb128Protocol,
}


class SnmpCollector(Collector):
    def __init__(self, sensor_id: str, config: dict):
        super().__init__(sensor_id, config)
        self.ip        = config["ip"]
        self.port      = int(config.get("port", 161))
        self.version   = (config.get("version", "v2c") or "v2c").lower()
        self.oid       = config["oid"]
        self.scale     = float(config.get("scale", 1.0))
        self.timeout_s = int(config.get("timeout_s", 5))
        self.retries   = int(config.get("retries", 1))

        # v2c
        self.community = config.get("community", "public")

        # v3
        self.user            = config.get("user")
        self.auth_key        = config.get("auth_key")
        self.priv_key        = config.get("priv_key")
        self.auth_protocol   = config.get("auth_protocol")  # "MD5"|"SHA"|None
        self.priv_protocol   = config.get("priv_protocol")  # "DES"|"AES"|None

        if self.version == "v3" and not self.user:
            raise ValueError("SNMP v3 requires 'user' in config")

    def _auth_data(self):
        if self.version == "v3":
            kwargs = {}
            if self.auth_key:
                kwargs["authKey"] = self.auth_key
                kwargs["authProtocol"] = _AUTH_MAP.get(self.auth_protocol or "SHA", usmHMACSHAAuthProtocol)
            if self.priv_key:
                kwargs["privKey"] = self.priv_key
                kwargs["privProtocol"] = _PRIV_MAP.get(self.priv_protocol or "AES", usmAesCfb128Protocol)
            return UsmUserData(self.user, **kwargs)
        # v2c (and v1, treated the same)
        return CommunityData(self.community, mpModel=0 if self.version == "v1" else 1)

    async def read(self) -> float:
        engine = SnmpEngine()
        transport = await UdpTransportTarget.create(
            (self.ip, self.port),
            timeout=self.timeout_s,
            retries=self.retries,
        )
        errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
            engine,
            self._auth_data(),
            transport,
            ContextData(),
            ObjectType(ObjectIdentity(self.oid)),
        )
        try:
            if errorIndication:
                raise RuntimeError(f"SNMP error: {errorIndication}")
            if errorStatus:
                raise RuntimeError(f"SNMP error status: {errorStatus.prettyPrint()}")
            if not varBinds:
                raise RuntimeError("SNMP returned no varbinds")
            _, value = varBinds[0]
            # pysnmp returns various rfc1902 types — float() handles them all
            return float(value) * self.scale
        finally:
            try:
                engine.close_dispatcher()
            except Exception:
                pass
