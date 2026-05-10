"""Smoke tests for simulator collector."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from varigrid_gateway.collectors.simulator import SimulatorCollector


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_walk_drifts_around_start():
    s = SimulatorCollector("x", {"pattern": "walk", "start": 100, "drift": 5})
    samples = [_run(s.read()) for _ in range(20)]
    # Should never wander dramatically far in just 20 ticks
    assert all(50 < v < 150 for v in samples), samples


def test_sine_oscillates_around_offset():
    s = SimulatorCollector("x", {"pattern": "sine", "amplitude": 100, "period_s": 0.001, "offset": 1000})
    samples = [_run(s.read()) for _ in range(50)]
    assert min(samples) < 1000
    assert max(samples) > 1000


def test_unknown_pattern_returns_start():
    s = SimulatorCollector("x", {"pattern": "🤷", "start": 42})
    assert _run(s.read()) == 42
