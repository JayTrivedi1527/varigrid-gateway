"""Structured logging — JSON when stdout is not a TTY (Docker / journald),
human-readable otherwise."""
import logging
import sys
import os
import json
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts":      datetime.now(timezone.utc).isoformat(),
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
        }
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        for k, v in (getattr(record, "extra", {}) or {}).items():
            out[k] = v
        return json.dumps(out, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    if sys.stdout.isatty():
        handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
            datefmt="%H:%M:%S",
        ))
    else:
        handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    # Don't double-add if called twice (tests etc.)
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Quiet down noisy libs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("pymodbus").setLevel(logging.WARNING)
