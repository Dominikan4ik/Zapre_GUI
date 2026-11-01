from __future__ import annotations

import logging
import logging.handlers
import tempfile
from pathlib import Path

from .config import app_dir

logger = logging.getLogger("zm")
_listeners: list = []


class _ListenerHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        for cb in list(_listeners):
            try:
                cb(msg)
            except Exception:
                pass


def logs_dir() -> Path:
    d = app_dir() / "logs"
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d
    except OSError:
        d = Path(tempfile.gettempdir()) / "zapret_manager_logs"
        d.mkdir(parents=True, exist_ok=True)
        return d


def setup() -> None:
    if logger.handlers:
        return
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S")
    fh = logging.handlers.RotatingFileHandler(
        logs_dir() / "manager.log", maxBytes=512_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(fmt)
    lh = _ListenerHandler()
    lh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(lh)


def add_listener(cb) -> None:
    _listeners.append(cb)


def info(msg: str) -> None:
    logger.info(msg)


def warn(msg: str) -> None:
    logger.warning("⚠ " + msg)


def error(msg: str) -> None:
    logger.error("✖ " + msg)
