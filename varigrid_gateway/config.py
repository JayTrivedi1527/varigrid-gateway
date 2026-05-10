"""YAML config loader + validation.

Hard-failures with a clear message rather than letting Python tracebacks
bury the user's actual mistake (wrong key, missing field, etc.)."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import sys

import yaml


@dataclass
class GatewayConfig:
    api_url:               str
    api_key:               str
    heartbeat_interval_s:  int  = 60
    buffer_path:           str  = "/var/lib/varigrid/buffer.db"
    push_batch_size:       int  = 50


@dataclass
class SensorConfig:
    id:               str
    kind:             str
    poll_interval_s:  int
    config:           dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    gateway: GatewayConfig
    sensors: list[SensorConfig]


def load(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        die(f"Config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        die(f"Could not parse YAML at {path}: {e}")

    if not isinstance(raw, dict):
        die("Top-level config must be a mapping with 'gateway' and 'sensors' keys")

    gateway_raw = raw.get("gateway")
    if not isinstance(gateway_raw, dict):
        die("Missing 'gateway' section")

    if not gateway_raw.get("api_url"):
        die("gateway.api_url is required")
    if not gateway_raw["api_url"].startswith("https://"):
        die("gateway.api_url must start with https://  (refusing to send credentials over plaintext)")
    if not gateway_raw.get("api_key"):
        die("gateway.api_key is required — get it from Varigrid Settings → Sensors → Add gateway")
    if gateway_raw["api_key"].startswith("vrg_REPLACE"):
        die("gateway.api_key still has the placeholder — paste the real key from Varigrid")

    gateway = GatewayConfig(
        api_url               = gateway_raw["api_url"].rstrip("/"),
        api_key               = gateway_raw["api_key"],
        heartbeat_interval_s  = int(gateway_raw.get("heartbeat_interval_s", 60)),
        buffer_path           = str(gateway_raw.get("buffer_path", "/var/lib/varigrid/buffer.db")),
        push_batch_size       = int(gateway_raw.get("push_batch_size", 50)),
    )

    sensors_raw = raw.get("sensors") or []
    if not isinstance(sensors_raw, list) or not sensors_raw:
        die("'sensors' must be a non-empty list")

    sensors = []
    for i, s in enumerate(sensors_raw):
        if not isinstance(s, dict):
            die(f"sensors[{i}] must be a mapping")
        if not s.get("id"):
            die(f"sensors[{i}].id is required (use the sensor UUID from Varigrid)")
        if str(s["id"]).startswith("REPLACE"):
            die(f"sensors[{i}].id still has the placeholder — paste the real sensor UUID")
        if not s.get("kind"):
            die(f"sensors[{i}].kind is required (e.g. modbus_tcp, simulator)")
        sensors.append(SensorConfig(
            id              = str(s["id"]),
            kind            = str(s["kind"]),
            poll_interval_s = int(s.get("poll_interval_s", 60)),
            config          = s.get("config") or {},
        ))

    return Config(gateway=gateway, sensors=sensors)


def die(msg: str) -> None:
    print(f"varigrid-gateway: config error — {msg}", file=sys.stderr)
    sys.exit(2)
