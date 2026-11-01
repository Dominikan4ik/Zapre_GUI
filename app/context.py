from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import lists, log
from .config import Config
from .runner import Runner
from .strategies import Strategy, discover, read_game_filter, zapret_installed
from .tester import StrategyResult


class AppContext(QObject):
    strategies_changed = Signal()
    state_changed = Signal()
    history_changed = Signal()
    lists_changed = Signal()
    busy_changed = Signal(bool)
    log_message = Signal(str)

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg
        self.runner = Runner()
        self.strategies: list[Strategy] = []
        self.busy = False
        self.external = False
        log.add_listener(self.log_message.emit)

    @property
    def zdir(self) -> Path:
        return self.cfg.zapret_dir

    @property
    def installed(self) -> bool:
        return zapret_installed(self.zdir)

    def reload(self) -> None:
        if self.installed:
            try:
                lists.ensure_user_files(self.zdir)
            except OSError as e:
                log.warn(f"Не удалось подготовить пользовательские списки: {e}")
        self.strategies = discover(self.zdir)
        self.strategies_changed.emit()
        self.state_changed.emit()

    def game_filter(self):
        return read_game_filter(self.zdir)

    def get_strategy(self, name: str) -> Strategy | None:
        return next((s for s in self.strategies if s.name == name), None)

    def running_strategy(self) -> Strategy | None:
        p = self.runner.proc
        return self.runner.current if (p is not None and p.poll() is None) else None

    def state(self) -> tuple[str, str]:
        s = self.running_strategy()
        if s:
            return "running", s.name
        return ("external", "") if self.external else ("stopped", "")

    def set_external(self, value: bool) -> None:
        if value != self.external:
            self.external = value
            self.state_changed.emit()

    def set_busy(self, value: bool) -> None:
        self.busy = value
        self.busy_changed.emit(value)

    def record(self, sr: StrategyResult) -> None:
        self.cfg.data["history"][sr.name] = {
            "score": round(sr.score, 1), "ok": sr.ok, "total": sr.total,
            "ping": round(sr.ping_avg, 1) if sr.ping_avg is not None else None,
            "time": time.strftime("%d.%m %H:%M"), "error": sr.error,
        }
        self.cfg.save()
        self.history_changed.emit()

    def history(self) -> dict:
        return self.cfg.data.get("history", {})

    def best_from_history(self) -> str | None:
        from .tester import BASELINE_NAME
        cands = [(v["score"], -(v["ping"] if v.get("ping") is not None else 9999), k)
                 for k, v in self.history().items()
                 if k != BASELINE_NAME and not v.get("error") and self.get_strategy(k)]
        return max(cands)[2] if cands else None
