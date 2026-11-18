"""Central logging setup for AvatarGen (owner request, Nov 18 2026).

Toggle lives in the global Settings dialog (D42); when enabled, events are
written to userdata/logs/avatargen.log and echoed to stderr.
"""
from __future__ import annotations

import logging
import os

LOG_DIR = os.path.join(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))), "userdata", "logs")
LOG_PATH = os.path.join(LOG_DIR, "avatargen.log")

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_handler: logging.FileHandler | None = None


def setup_logging(enabled: bool, level: int = logging.INFO) -> None:
    """(Re)configure file logging. Safe to call repeatedly."""
    global _handler
    root = logging.getLogger("avatargen")
    # always keep a stream handler so errors are visible on console
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
        root.addHandler(sh)
    if _handler is not None:
        root.removeHandler(_handler)
        _handler = None
    if enabled:
        os.makedirs(LOG_DIR, exist_ok=True)
        _handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        _handler.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
        root.addHandler(_handler)
        root.setLevel(level)
    else:
        root.setLevel(logging.WARNING)  # warnings/errors still reach console
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"avatargen.{name}")
