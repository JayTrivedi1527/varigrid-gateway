"""Collector ABC."""
from abc import ABC, abstractmethod


class Collector(ABC):
    """A collector reads ONE numeric value from a device.

    Subclasses must:
      - call super().__init__(sensor_id, config) in their __init__
      - implement async read() -> float
      - optionally implement async close() for cleanup
    """

    def __init__(self, sensor_id: str, config: dict):
        self.sensor_id = sensor_id
        self.config    = config

    @abstractmethod
    async def read(self) -> float:
        ...

    async def close(self) -> None:
        pass
