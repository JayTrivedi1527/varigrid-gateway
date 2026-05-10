"""Smoke tests for config loader."""
import sys
import tempfile
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from varigrid_gateway.config import load   # noqa: E402


def _write(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    f.write(content)
    f.close()
    return f.name


def test_loads_valid_config():
    cfg = load(_write("""
gateway:
  api_url: https://api.varigrid.in
  api_key: vrg_abc123def456
sensors:
  - id: 9d3a2cb4-1f6e-4d8e-9a3b-1c2d3e4f5a6b
    kind: simulator
    poll_interval_s: 5
    config:
      pattern: walk
      start: 100
"""))
    assert cfg.gateway.api_url == "https://api.varigrid.in"
    assert cfg.gateway.api_key == "vrg_abc123def456"
    assert len(cfg.sensors) == 1
    assert cfg.sensors[0].kind == "simulator"


def test_rejects_http_api_url():
    with pytest.raises(SystemExit):
        load(_write("""
gateway:
  api_url: http://api.varigrid.in
  api_key: vrg_abc
sensors:
  - id: x
    kind: simulator
"""))


def test_rejects_placeholder_api_key():
    with pytest.raises(SystemExit):
        load(_write("""
gateway:
  api_url: https://api.varigrid.in
  api_key: vrg_REPLACE_ME
sensors:
  - id: x
    kind: simulator
"""))


def test_rejects_placeholder_sensor_id():
    with pytest.raises(SystemExit):
        load(_write("""
gateway:
  api_url: https://api.varigrid.in
  api_key: vrg_real_key
sensors:
  - id: REPLACE_WITH_SENSOR_UUID
    kind: simulator
"""))


def test_rejects_empty_sensors():
    with pytest.raises(SystemExit):
        load(_write("""
gateway:
  api_url: https://api.varigrid.in
  api_key: vrg_real_key
sensors: []
"""))
