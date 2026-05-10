"""Collector registry.

A collector is anything that can read a single float from somewhere —
a Modbus device, an SNMP agent, an MQTT broker, a simulated waveform.

Adding a new collector:
  1. Create a subclass of Collector in this directory
  2. Register it in COLLECTOR_KINDS below
  3. Add the dependency to pyproject.toml + requirements.txt

The runner doesn't know or care about protocols — it just calls
.read() on each collector at the configured interval.
"""
from typing import Type
from .base import Collector
from .simulator   import SimulatorCollector
from .modbus_tcp  import ModbusTcpCollector
from .modbus_rtu  import ModbusRtuCollector
from .snmp        import SnmpCollector
from .mqtt        import MqttCollector
from .opcua       import OpcuaCollector
from .bacnet      import BacnetCollector


COLLECTOR_KINDS: dict[str, Type[Collector]] = {
    "simulator":  SimulatorCollector,
    "modbus_tcp": ModbusTcpCollector,
    "modbus_rtu": ModbusRtuCollector,
    "snmp":       SnmpCollector,
    "mqtt":       MqttCollector,
    "opcua":      OpcuaCollector,
    "bacnet":     BacnetCollector,
}


def build(kind: str, sensor_id: str, config: dict) -> Collector:
    if kind not in COLLECTOR_KINDS:
        raise ValueError(
            f"Unknown sensor kind '{kind}'. Supported: {sorted(COLLECTOR_KINDS)}"
        )
    return COLLECTOR_KINDS[kind](sensor_id=sensor_id, config=config)
