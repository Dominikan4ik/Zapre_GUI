from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path

APP_NAME = "Zapret Manager"
APP_VERSION = "1.0.0"
REPO = "Flowseal/zapret-discord-youtube"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


DEFAULTS: dict = {
    "zapret_dir": "",
    "last_strategy": "",
    "autostart_strategy": False,
    "stop_on_exit": True,
    "minimize_to_tray": True,
    "auto_restart_on_lists": True,
    "check_updates": True,
    "auto_install_updates": True,
    "test": {
        "timeout": 5,
        "parallel": 12,
        "quick": False,
        "baseline": True,
        "user_sites": True,
    },
    "custom_targets": [],
    "history": {},
}


def _merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v


class Config:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else app_dir() / "config.json"
        self.data: dict = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text("utf-8"))
            if isinstance(raw, dict):
                _merge(self.data, raw)
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value) -> None:
        self.data[key] = value
        self.save()

    @property
    def zapret_dir(self) -> Path:
        p = self.data.get("zapret_dir") or ""
        return Path(p) if p else app_dir() / "zapret"
