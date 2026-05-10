"""Synthetic waveform collector.

Useful for:
  - Demos / sales — let prospects see the dashboard fill up without
    setting up real meters
  - Local testing — verify the agent + Varigrid pipeline end to end
  - CI — keep the test suite fast and deterministic

Patterns:
  walk  : random walk around a starting value
  sine  : amplitude * sin(2π t / period_s) + offset
  ramp  : linear from start → end over period_s, then resets
"""
import math
import random
import time
from .base import Collector


class SimulatorCollector(Collector):
    def __init__(self, sensor_id: str, config: dict):
        super().__init__(sensor_id, config)
        self.pattern = config.get("pattern", "walk")
        self.start   = float(config.get("start", 100.0))
        self.drift   = float(config.get("drift", 5.0))
        self.amp     = float(config.get("amplitude", 100.0))
        self.period  = float(config.get("period_s", 3600.0))
        self.offset  = float(config.get("offset", self.start))
        self.end     = float(config.get("end", self.start * 1.2))
        self._value  = self.start
        self._t0     = time.monotonic()

    async def read(self) -> float:
        if self.pattern == "walk":
            self._value += random.uniform(-self.drift, self.drift)
            return round(self._value, 3)
        if self.pattern == "sine":
            t = time.monotonic() - self._t0
            return round(self.offset + self.amp * math.sin(2 * math.pi * t / self.period), 3)
        if self.pattern == "ramp":
            t = (time.monotonic() - self._t0) % self.period
            frac = t / self.period
            return round(self.start + (self.end - self.start) * frac, 3)
        # Unknown pattern → just hold the start value
        return self.start
