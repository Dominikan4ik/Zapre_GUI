from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

_alive: set = set()


class Task(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self.fn())
        except Exception as e:
            self.failed.emit(str(e) or type(e).__name__)


def run_async(owner: QObject, fn, on_done=None, on_fail=None) -> Task:
    t = Task(fn)
    if on_done:
        t.done.connect(on_done)
    if on_fail:
        t.failed.connect(on_fail)
    t.finished.connect(lambda: _alive.discard(t))
    _alive.add(t)
    t.start()
    return t


class TestWorker(QThread):
    strategy_started = Signal(int, int, str)
    progress = Signal(int, int)
    strategy_done = Signal(object)
    failed = Signal(str)

    def __init__(self, session, strategies):
        super().__init__()
        self.session, self.strategies = session, strategies
        self.session.emit = self._emit

    def _emit(self, kind, *args) -> None:
        {"strategy_start": self.strategy_started, "progress": self.progress,
         "strategy_done": self.strategy_done}[kind].emit(*args)

    def cancel(self) -> None:
        self.session.cancel.set()

    def run(self) -> None:
        try:
            self.session.run(self.strategies)
        except Exception as e:
            self.failed.emit(str(e))
