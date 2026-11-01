from __future__ import annotations

import subprocess
import time
from pathlib import Path

from . import log
from .log import logs_dir
from .strategies import GameFilter, Strategy
from .winutils import IS_WIN, NO_WINDOW, decode, run_hidden


class StartError(Exception):
    pass


def winws_pids() -> list[int]:
    if IS_WIN:
        r = run_hidden(["tasklist", "/FI", "IMAGENAME eq winws.exe", "/FO", "CSV", "/NH"])
        pids = []
        for line in decode(r.stdout).splitlines():
            parts = line.strip().strip('"').split('","')
            if len(parts) > 1 and parts[0].lower() == "winws.exe" and parts[1].isdigit():
                pids.append(int(parts[1]))
        return pids
    r = run_hidden(["pgrep", "-x", "winws.exe"])
    return [int(x) for x in decode(r.stdout).split() if x.isdigit()]


def kill_all_winws() -> None:
    if IS_WIN:
        run_hidden(["taskkill", "/F", "/T", "/IM", "winws.exe"])
    else:
        run_hidden(["pkill", "-x", "winws.exe"])
    deadline = time.time() + 4
    while time.time() < deadline and winws_pids():
        time.sleep(0.15)


def service_state(name: str = "zapret") -> str | None:
    if not IS_WIN:
        return None
    r = run_hidden(["sc", "query", name])
    if r.returncode != 0:
        return None
    for word in ("RUNNING", "STOP_PENDING", "START_PENDING", "STOPPED"):
        if word in decode(r.stdout):
            return word
    return "UNKNOWN"


def stop_service(name: str = "zapret") -> None:
    if IS_WIN:
        run_hidden(["sc", "stop", name], timeout=20)
        time.sleep(1.0)


def release_driver() -> None:
    if not IS_WIN:
        return
    for svc in ("WinDivert", "WinDivert14"):
        run_hidden(["net", "stop", svc], timeout=20)
        run_hidden(["sc", "delete", svc], timeout=20)


class Runner:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.current: Strategy | None = None

    def is_running(self) -> bool:
        if self.proc and self.proc.poll() is None:
            return True
        return bool(winws_pids())

    def external_running(self) -> bool:
        ours = self.proc is not None and self.proc.poll() is None
        return (not ours) and bool(winws_pids())

    def start(self, strategy: Strategy, zdir: Path, gf: GameFilter, settle: float = 1.2) -> None:
        self.stop()
        exe = zdir / "bin" / "winws.exe"
        if not exe.is_file():
            raise StartError(f"Не найден {exe}")
        args = strategy.build_args(zdir, gf)
        log_path = logs_dir() / "winws.log"
        with open(log_path, "wb") as logf:
            try:
                self.proc = subprocess.Popen(
                    [str(exe), *args], cwd=str(exe.parent), stdout=logf, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
            except OSError as e:
                raise StartError(f"Не удалось запустить winws.exe: {e}") from e
        deadline = time.time() + settle
        while time.time() < deadline:
            if self.proc.poll() is not None:
                tail = self._tail(log_path)
                self.proc = None
                raise StartError("winws.exe сразу завершился." + (f"\n{tail}" if tail else
                                 "\nПроверьте права администратора и антивирус (WinDivert)."))
            time.sleep(0.1)
        self.current = strategy
        log.info(f"Запущена стратегия: {strategy.name}")

    def stop(self, drop_driver: bool = False) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        if winws_pids():
            kill_all_winws()
        if drop_driver:
            release_driver()
        if self.current:
            log.info("Обход остановлен")
        self.current = None

    @staticmethod
    def _tail(path: Path, limit: int = 600) -> str:
        try:
            return decode(path.read_bytes()[-limit:]).strip()
        except OSError:
            return ""
