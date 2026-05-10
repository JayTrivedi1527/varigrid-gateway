"""Main poll loop.

Three concurrent things happen:

  1. Per-sensor poll task
       loop:
         read collector
         try push → if fails, append to buffer
         sleep poll_interval_s

  2. Heartbeat task
       loop:
         POST /api/gateways/heartbeat
         sleep heartbeat_interval_s

  3. Replay task
       loop:
         take batch from buffer
         try push each → drop on success
         sleep 30s

All errors are logged but never crash the loop. On SIGINT/SIGTERM we
drain in-flight requests, close everything, and exit cleanly.
"""
import asyncio
import logging
import signal
from datetime import datetime, timezone
from typing import Optional

from .config import Config
from .client import VarigridClient
from .buffer import Buffer
from .collectors import build as build_collector
from .collectors.base import Collector

logger = logging.getLogger(__name__)


class Runner:
    def __init__(self, config: Config):
        self.config = config
        self.client = VarigridClient(config.gateway.api_url, config.gateway.api_key)
        self.buffer = Buffer(config.gateway.buffer_path)
        self._collectors: dict[str, Collector] = {}
        self._stop = asyncio.Event()

    async def run(self) -> None:
        # Build collectors up-front so config errors surface immediately
        for s in self.config.sensors:
            try:
                self._collectors[s.id] = build_collector(s.kind, s.id, s.config)
            except Exception as e:
                logger.error("sensor %s (%s) — could not build collector: %s",
                             s.id, s.kind, e)

        if not self._collectors:
            logger.error("No collectors built — exiting")
            return

        # Wire signals so docker stop / Ctrl-C drain cleanly
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._stop.set)
            except NotImplementedError:
                # Windows doesn't support signal handlers in asyncio
                pass

        logger.info("Starting %d sensor poll task(s) — buffer=%s",
                    len(self._collectors), self.config.gateway.buffer_path)
        if self.buffer.size():
            logger.info("Buffer has %d unsent reading(s) from a previous run", self.buffer.size())

        tasks = [
            asyncio.create_task(self._heartbeat_loop(),  name="heartbeat"),
            asyncio.create_task(self._replay_loop(),     name="replay"),
        ]
        for s in self.config.sensors:
            if s.id in self._collectors:
                tasks.append(asyncio.create_task(self._poll_loop(s), name=f"poll[{s.id[:8]}]"))

        # Wait for stop signal
        await self._stop.wait()
        logger.info("Stop requested — cancelling tasks…")
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        await self._cleanup()
        logger.info("Bye.")

    async def _cleanup(self) -> None:
        for c in self._collectors.values():
            try: await c.close()
            except Exception: pass
        await self.client.close()

    # ── Per-sensor poll loop ─────────────────────────────────

    async def _poll_loop(self, sensor) -> None:
        col = self._collectors[sensor.id]
        # Stagger start so 50 sensors don't all hit their devices at once
        await asyncio.sleep(hash(sensor.id) % max(1, sensor.poll_interval_s))
        while not self._stop.is_set():
            ts = datetime.now(timezone.utc).isoformat()
            value: Optional[float] = None
            try:
                value = await col.read()
            except Exception as e:
                logger.warning("sensor %s read failed: %s", sensor.id, e)

            if value is not None:
                ok = await self.client.push(sensor.id, value, ts)
                if not ok:
                    self.buffer.append(sensor.id, ts, value)
                    logger.debug("sensor %s push failed → buffered (size=%d)",
                                 sensor.id, self.buffer.size())

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=sensor.poll_interval_s)
                return  # stop fired
            except asyncio.TimeoutError:
                pass    # next iteration

    # ── Heartbeat loop ───────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        interval = self.config.gateway.heartbeat_interval_s
        while not self._stop.is_set():
            ok = await self.client.heartbeat()
            if ok:
                logger.debug("heartbeat ok")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                pass

    # ── Buffer replay loop ───────────────────────────────────

    async def _replay_loop(self) -> None:
        batch_size = self.config.gateway.push_batch_size
        while not self._stop.is_set():
            try:
                rows = self.buffer.take(batch_size)
            except Exception as e:
                logger.warning("replay take failed: %s", e)
                rows = []

            if rows:
                logger.info("replay: draining %d buffered reading(s)", len(rows))
                done_ids = []
                for (id_, sensor_id, ts, value, quality) in rows:
                    ok = await self.client.push(sensor_id, value, ts, quality)
                    if ok:
                        done_ids.append(id_)
                    else:
                        # Network is still bad — stop the batch, try later
                        break
                if done_ids:
                    self.buffer.drop(done_ids)

            # Sleep longer when buffer is empty; shorter when we're catching up
            sleep_s = 5 if rows else 30
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=sleep_s)
                return
            except asyncio.TimeoutError:
                pass
