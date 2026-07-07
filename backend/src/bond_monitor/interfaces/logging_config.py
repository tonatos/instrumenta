"""Central logging configuration for the API process."""

from __future__ import annotations

import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure root and framework loggers with a consistent format."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        force=True,
    )
    for name in ("bond_monitor", "litestar", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).setLevel(log_level)
