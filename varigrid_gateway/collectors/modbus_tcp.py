"""Modbus TCP collector.

Reads ONE numeric value from a holding/input register. Most data-center
MFMs (Schneider PM5xxx, Selec MFM384, L&T 5060, Conzerv EM6400, Stulz
CRACs in Modbus mode, etc.) speak this.

Config:
  ip:              "10.20.1.5"           required
  port:            502                   default 502
  unit_id:         1                     default 1 (some devices use 0)
  register:        40012                 required (1-indexed Modbus number, OR 0-indexed offset)
  register_count:  2                     1 = 16-bit, 2 = 32-bit
  data_type:       float32 | int16 | uint16 | int32 | uint32  (default uint16)
  byte_order:      big | little          default big
  function:        holding | input       default holding
  scale:           1.0                   default 1.0 (use 0.001 for kW from W readings)

Notes:
  - register 40012 is the "Modbus PDU" address 12 in the holding-register
    bank (4xxxx convention). We strip the leading 4/3/1 if present.
  - pymodbus is sync; we run reads in a thread executor so the asyncio
    loop isn't blocked on slow networks.
"""
import asyncio
import struct
import logging
from typing import Optional

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

from .base import Collector

logger = logging.getLogger(__name__)


class ModbusTcpCollector(Collector):
    def __init__(self, sensor_id: str, config: dict):
        super().__init__(sensor_id, config)
        self.ip          = config["ip"]
        self.port        = int(config.get("port", 502))
        self.unit_id     = int(config.get("unit_id", 1))
        self.reg_count   = int(config.get("register_count", 1))
        self.data_type   = config.get("data_type", "uint16")
        self.byte_order  = config.get("byte_order", "big")
        self.scale       = float(config.get("scale", 1.0))
        self.function    = config.get("function", "holding")

        raw_reg = int(config["register"])
        # Strip Modbus 4xxxx / 3xxxx / 1xxxx prefix → PDU address
        if raw_reg >= 40001:
            self.register = raw_reg - 40001
        elif raw_reg >= 30001:
            self.register = raw_reg - 30001
        elif raw_reg >= 10001:
            self.register = raw_reg - 10001
        else:
            self.register = raw_reg   # treat as raw PDU offset

        self._client: Optional[ModbusTcpClient] = None

    def _ensure_client(self) -> ModbusTcpClient:
        if self._client is None or not self._client.connected:
            self._client = ModbusTcpClient(host=self.ip, port=self.port, timeout=5)
            if not self._client.connect():
                raise ModbusException(f"Could not connect to {self.ip}:{self.port}")
        return self._client

    def _decode(self, regs: list[int]) -> float:
        # Pack registers as 16-bit big/little endian, then interpret as
        # the requested data type. Most India deployments are big-endian
        # (CDAB / ABCD); some Schneider devices are mid-little (BADC).
        order = ">" if self.byte_order == "big" else "<"
        raw = b"".join(struct.pack(f"{order}H", r) for r in regs)
        type_map = {
            "uint16":  ("H", 2),
            "int16":   ("h", 2),
            "uint32":  ("I", 4),
            "int32":   ("i", 4),
            "float32": ("f", 4),
        }
        if self.data_type not in type_map:
            raise ValueError(f"Unsupported data_type: {self.data_type}")
        fmt, size = type_map[self.data_type]
        if len(raw) < size:
            raise ValueError(f"Need {size} bytes for {self.data_type}, got {len(raw)}")
        return struct.unpack(f"{order}{fmt}", raw[:size])[0]

    def _read_blocking(self) -> float:
        client = self._ensure_client()
        if self.function == "input":
            rr = client.read_input_registers(self.register, count=self.reg_count, slave=self.unit_id)
        else:
            rr = client.read_holding_registers(self.register, count=self.reg_count, slave=self.unit_id)
        if rr.isError():
            raise ModbusException(f"Modbus error: {rr}")
        decoded = self._decode(list(rr.registers))
        return float(decoded) * self.scale

    async def read(self) -> float:
        # pymodbus sync API in a thread to avoid blocking the loop
        return await asyncio.to_thread(self._read_blocking)

    async def close(self) -> None:
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
