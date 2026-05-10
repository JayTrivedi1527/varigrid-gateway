"""Modbus RTU collector — Modbus over RS-485 serial.

Used by:
  - Older MFMs without ethernet (Selec MFM35, L&T 3-series, Conzerv pre-2018)
  - Aisle temperature probe chains (one bus, many addresses)
  - Older chillers, BMS-attached gateways
  - Inverters and gensets in plant rooms with serial-only controllers

Same decode logic as Modbus TCP — only the transport differs. Subclasses
the TCP collector and overrides the client construction.

Config:
  port:            /dev/ttyUSB0    required (the serial device)
  baudrate:        9600            default 9600
  parity:          N | E | O       default N (none)
  stopbits:        1 | 2           default 1
  bytesize:        7 | 8           default 8
  unit_id:         1               default 1   (Modbus slave address)
  register:        40012           required
  register_count:  2               1=16-bit, 2=32-bit
  data_type:       float32 | int16 | uint16 | int32 | uint32   default uint16
  byte_order:      big | little    default big
  function:        holding | input default holding
  scale:           1.0             default 1.0

Notes:
  - On Linux the agent must have read/write permission on the device
    (e.g. add the user to the `dialout` group, or run with --device
    /dev/ttyUSB0 in Docker)
  - One serial bus serves many devices; create one Sensor row per device
    (varying unit_id) all pointing at the same `port`. The agent
    serialises reads on the bus per port to avoid clashing with the
    half-duplex transport.
"""
import asyncio
import logging
import threading
from typing import Optional

from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusException

from .modbus_tcp import ModbusTcpCollector

logger = logging.getLogger(__name__)


# RS-485 is half-duplex — concurrent reads on the same physical bus
# corrupt frames. Serialise per port across all collectors.
_PORT_LOCKS: dict[str, threading.Lock] = {}


class ModbusRtuCollector(ModbusTcpCollector):
    def __init__(self, sensor_id: str, config: dict):
        # Don't call super().__init__ — TCP has different required keys.
        # Re-implement the minimum needed plus serial-specific bits.
        super(ModbusTcpCollector, self).__init__(sensor_id, config)

        self.port      = config["port"]
        self.baudrate  = int(config.get("baudrate", 9600))
        self.parity    = config.get("parity", "N").upper()
        self.stopbits  = int(config.get("stopbits", 1))
        self.bytesize  = int(config.get("bytesize", 8))

        # Register + decode params (shared with TCP)
        self.unit_id     = int(config.get("unit_id", 1))
        self.reg_count   = int(config.get("register_count", 1))
        self.data_type   = config.get("data_type", "uint16")
        self.byte_order  = config.get("byte_order", "big")
        self.scale       = float(config.get("scale", 1.0))
        self.function    = config.get("function", "holding")

        raw_reg = int(config["register"])
        if raw_reg >= 40001:   self.register = raw_reg - 40001
        elif raw_reg >= 30001: self.register = raw_reg - 30001
        elif raw_reg >= 10001: self.register = raw_reg - 10001
        else:                  self.register = raw_reg

        # Per-port lock (shared across collectors that hit the same bus)
        self._lock = _PORT_LOCKS.setdefault(self.port, threading.Lock())
        self._client: Optional[ModbusSerialClient] = None

    def _ensure_client(self) -> ModbusSerialClient:
        if self._client is None or not self._client.connected:
            self._client = ModbusSerialClient(
                port     = self.port,
                baudrate = self.baudrate,
                parity   = self.parity,
                stopbits = self.stopbits,
                bytesize = self.bytesize,
                timeout  = 3,
            )
            if not self._client.connect():
                raise ModbusException(f"Could not open serial port {self.port}")
        return self._client

    def _read_blocking(self) -> float:
        with self._lock:
            client = self._ensure_client()
            if self.function == "input":
                rr = client.read_input_registers(self.register, count=self.reg_count, slave=self.unit_id)
            else:
                rr = client.read_holding_registers(self.register, count=self.reg_count, slave=self.unit_id)
            if rr.isError():
                raise ModbusException(f"Modbus RTU error on {self.port} unit={self.unit_id}: {rr}")
            decoded = self._decode(list(rr.registers))
            return float(decoded) * self.scale

    async def read(self) -> float:
        return await asyncio.to_thread(self._read_blocking)
