from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform.startswith("win")
NO_WINDOW = 0x08000000 if IS_WIN else 0
TASK_NAME = "ZapretManager"


def decode(b: bytes | None) -> str:
    if not b:
        return ""
    for enc in (("utf-8",) if not IS_WIN else ("utf-8", "cp866", "cp1251")):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def run_hidden(cmd: list[str], timeout: float = 15) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout,
                              creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    except (FileNotFoundError, PermissionError):
        return subprocess.CompletedProcess(cmd, 127, b"", b"command not found")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, b"", b"timeout")


def is_admin() -> bool:
    if IS_WIN:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _q(s: str) -> str:
    return '"' + s.replace('"', '\\"') + '"'


def relaunch_as_admin() -> bool:
    if not IS_WIN:
        return False
    if getattr(sys, "frozen", False):
        exe, args = sys.executable, sys.argv[1:]
    else:
        exe, args = sys.executable, [os.path.abspath(sys.argv[0]), *sys.argv[1:]]
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe, " ".join(_q(a) for a in args), None, 1)
        return rc > 32
    except Exception:
        return False


def _autostart_command() -> str:
    if getattr(sys, "frozen", False):
        return f'{_q(sys.executable)} --minimized'
    pyw = Path(sys.executable).with_name("pythonw.exe")
    py = str(pyw if pyw.exists() else sys.executable)
    return f'{_q(py)} {_q(os.path.abspath(sys.argv[0]))} --minimized'


def autostart_enabled() -> bool:
    if not IS_WIN:
        return False
    return run_hidden(["schtasks", "/Query", "/TN", TASK_NAME]).returncode == 0


def set_autostart(enable: bool) -> tuple[bool, str]:
    if not IS_WIN:
        return False, "Доступно только в Windows"
    if enable:
        r = run_hidden(["schtasks", "/Create", "/TN", TASK_NAME, "/TR", _autostart_command(),
                        "/SC", "ONLOGON", "/RL", "HIGHEST", "/F"])
    else:
        r = run_hidden(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    return r.returncode == 0, decode(r.stderr or r.stdout).strip()
