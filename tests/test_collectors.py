"""Tests we can run without real hardware on the bench.

Each collector has ONE thing we can unit-test for free:
  - Config parsing (does it accept what it should, reject what it shouldn't)
  - The registry build() works for every kind

End-to-end protocol tests need real devices and are out of scope for
the unit suite — they live in our integration smoke notes (see README).
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from varigrid_gateway.collectors import COLLECTOR_KINDS, build   # noqa: E402


def test_all_kinds_registered():
    expected = {"simulator", "modbus_tcp", "modbus_rtu",
                "snmp", "mqtt", "opcua", "bacnet"}
    assert set(COLLECTOR_KINDS) == expected


def test_unknown_kind_raises():
    with pytest.raises(ValueError, match="Unknown sensor kind"):
        build("nope", "id-1", {})


# ── Modbus TCP ────────────────────────────────────────────
def test_modbus_tcp_strips_4xxxx_prefix():
    c = build("modbus_tcp", "id-1", {
        "ip": "10.0.0.1", "register": 40012, "data_type": "float32", "register_count": 2,
    })
    assert c.register == 11   # 40012 - 40001


def test_modbus_tcp_accepts_raw_pdu_offset():
    c = build("modbus_tcp", "id-1", {"ip": "10.0.0.1", "register": 100})
    assert c.register == 100


# ── Modbus RTU ────────────────────────────────────────────
def test_modbus_rtu_requires_port():
    with pytest.raises(KeyError):
        build("modbus_rtu", "id-1", {"register": 40012})


def test_modbus_rtu_strips_register_prefix():
    c = build("modbus_rtu", "id-1", {
        "port": "/dev/ttyUSB0", "register": 30002, "unit_id": 5,
    })
    assert c.register == 1     # 30002 - 30001
    assert c.unit_id == 5


# ── SNMP ──────────────────────────────────────────────────
def test_snmp_v3_requires_user():
    with pytest.raises(ValueError, match="v3 requires"):
        build("snmp", "id-1", {
            "ip": "10.0.0.1", "version": "v3", "oid": "1.2.3",
        })


def test_snmp_v2c_defaults_to_public_community():
    c = build("snmp", "id-1", {"ip": "10.0.0.1", "oid": "1.2.3"})
    assert c.community == "public"
    assert c.version == "v2c"


# ── MQTT ──────────────────────────────────────────────────
def test_mqtt_parses_config():
    c = build("mqtt", "id-1", {
        "broker_host": "mqtt.local",
        "topic": "facility/power",
        "json_path": "data.value",
    })
    assert c.host == "mqtt.local"
    assert c.port == 1883
    assert c.topic == "facility/power"
    assert c.json_path == "data.value"


def test_mqtt_message_parsing_plain_number():
    c = build("mqtt", "id-1", {"broker_host": "x", "topic": "t"})
    class _Msg:
        payload = b"42.5"
    c._on_message(None, None, _Msg())
    assert c._latest == 42.5


def test_mqtt_message_parsing_json_path():
    c = build("mqtt", "id-1", {
        "broker_host": "x", "topic": "t", "json_path": "data.temp",
    })
    class _Msg:
        payload = b'{"data": {"temp": 23.4, "humidity": 50}}'
    c._on_message(None, None, _Msg())
    assert c._latest == 23.4


def test_mqtt_message_parsing_json_value_key():
    c = build("mqtt", "id-1", {"broker_host": "x", "topic": "t"})
    class _Msg:
        payload = b'{"value": 100}'
    c._on_message(None, None, _Msg())
    assert c._latest == 100.0


def test_mqtt_garbage_payload_is_logged_not_raised():
    c = build("mqtt", "id-1", {"broker_host": "x", "topic": "t"})
    class _Msg:
        payload = b"not a number, not json"
    # Should not raise
    c._on_message(None, None, _Msg())
    assert c._latest is None


# ── OPC UA ────────────────────────────────────────────────
def test_opcua_rejects_http_endpoint():
    with pytest.raises(ValueError, match="opc.tcp"):
        build("opcua", "id-1", {
            "endpoint": "http://nope", "node_id": "ns=2;s=Foo",
        })


def test_opcua_accepts_opc_tcp():
    c = build("opcua", "id-1", {
        "endpoint": "opc.tcp://10.0.0.1:4840",
        "node_id":  "ns=2;s=Foo.Bar",
    })
    assert c.endpoint == "opc.tcp://10.0.0.1:4840"
    assert c.node_id  == "ns=2;s=Foo.Bar"


# ── BACnet ────────────────────────────────────────────────
def test_bacnet_rejects_unknown_object_type():
    with pytest.raises(ValueError, match="object_type"):
        build("bacnet", "id-1", {
            "device_address": "10.0.0.1", "device_id": 1,
            "object_type": "nopeNopeNope", "object_instance": 0,
        })


def test_bacnet_accepts_analog_input():
    c = build("bacnet", "id-1", {
        "device_address": "10.0.0.1", "device_id": 1001,
        "object_type": "analogInput", "object_instance": 12,
    })
    assert c.device_id == 1001
    assert c.object_instance == 12
    assert c.property == "presentValue"   # default
