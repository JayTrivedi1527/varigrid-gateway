"""HTTPS client to the Varigrid API.

Two endpoints used:
  POST /api/gateways/heartbeat   — alive check (every ~60s)
  POST /api/ingest/{sensor_id}   — single reading
"""
import logging
from typing import Optional
import httpx

from . import __version__

logger = logging.getLogger(__name__)


class VarigridClient:
    def __init__(self, api_url: str, api_key: str, timeout_s: int = 15):
        self._client = httpx.AsyncClient(
            base_url = api_url.rstrip("/"),
            headers  = {
                "Authorization": f"Bearer {api_key}",
                "User-Agent":    f"varigrid-gateway/{__version__}",
                "Content-Type":  "application/json",
            },
            timeout  = timeout_s,
        )

    async def heartbeat(self) -> bool:
        try:
            r = await self._client.post("/api/gateways/heartbeat",
                                        json={"version": __version__})
            if r.status_code != 200:
                logger.warning("heartbeat returned %s: %s", r.status_code, r.text[:200])
                return False
            return True
        except Exception as e:
            logger.warning("heartbeat failed: %s", e)
            return False

    async def push(self, sensor_id: str, value: float, ts: str,
                   quality: str = "good") -> bool:
        try:
            r = await self._client.post(
                f"/api/ingest/{sensor_id}",
                json={"value": value, "ts": ts, "quality": quality},
            )
            if r.status_code in (200, 201):
                return True
            # 409 = sensor disabled, 404 = sensor unknown, 401 = bad key
            # All of these are non-recoverable for THIS reading; don't replay.
            if r.status_code in (401, 404, 409):
                logger.error("push rejected (%s) for sensor=%s: %s — dropping",
                             r.status_code, sensor_id, r.text[:200])
                return True
            logger.warning("push failed (%s) for sensor=%s: %s",
                           r.status_code, sensor_id, r.text[:200])
            return False
        except Exception as e:
            logger.warning("push exception for sensor=%s: %s", sensor_id, e)
            return False

    async def close(self) -> None:
        await self._client.aclose()
