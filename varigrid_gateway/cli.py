"""Command-line entrypoint.

Usage:
  varigrid-gateway --config /path/to/gateway_config.yaml
  python -m varigrid_gateway --config /path/to/gateway_config.yaml
"""
import argparse
import asyncio
import os
import sys

from . import __version__
from .config import load
from .log import setup_logging
from .runner import Runner


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="varigrid-gateway",
        description="Edge agent that polls sensors and pushes readings to Varigrid.",
    )
    parser.add_argument(
        "--config", "-c",
        default=os.environ.get("VARIGRID_CONFIG", "gateway_config.yaml"),
        help="Path to gateway_config.yaml (default: $VARIGRID_CONFIG or ./gateway_config.yaml)",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("VARIGRID_LOG_LEVEL", "INFO"),
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    parser.add_argument("--version", action="version", version=f"varigrid-gateway {__version__}")
    args = parser.parse_args()

    setup_logging(args.log_level)
    cfg = load(args.config)

    print(f"varigrid-gateway {__version__} — {len(cfg.sensors)} sensor(s) → {cfg.gateway.api_url}")
    try:
        asyncio.run(Runner(cfg).run())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
