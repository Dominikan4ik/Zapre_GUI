from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from .runner import Runner, StartError
from .strategies import GameFilter, Strategy
from .winutils import IS_WIN, NO_WINDOW, decode

BASELINE_NAME = "Без обхода (базовая линия)"
VARIANTS = [
    ("HTTP", ["--http1.1"]),
    ("TLS1.2", ["--tlsv1.2", "--tls-max", "1.2"]),
    ("TLS1.3", ["--tlsv1.3", "--tls-max", "1.3"]),
]
LABELS = [v[0] for v in VARIANTS]

_RE_SSL = re.compile(r"could not resolve host|certificate|self[- ]?signed|"
                     r"certificate verify failed|unable to get local issuer", re.I)
_RE_UNSUP = re.compile(r"does not support|not supported|unsupported protocol|"
                       r"unrecognized option|unknown option|unsupported option|unsupported feature", re.I)
_TARGET_RE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*"([^"]+)"\s*$')


@dataclass
class Target:
    name: str
    url: str | None
    host: str
    group: str = ""
    user: bool = False


@dataclass
class TargetResult:
    target: Target
    tokens: dict = field(default_factory=dict)
    ping_ms: float | None = None


@dataclass
class StrategyResult:
    name: str
    results: list = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> int:
        return sum(1 for r in self.results for t in r.tokens.values() if t == "OK")

    @property
    def total(self) -> int:
        return sum(1 for r in self.results for t in r.tokens.values() if t != "UNSUP")

    def count(self, label: str) -> tuple[int, int]:
        vals = [r.tokens[label] for r in self.results if label in r.tokens and r.tokens[label] != "UNSUP"]
        return sum(1 for v in vals if v == "OK"), len(vals)

    @property
    def pings(self) -> list[float]:
        return [r.ping_ms for r in self.results if r.ping_ms is not None]

    @property
    def ping_avg(self) -> float | None:
        p = self.pings
        return sum(p) / len(p) if p else None

    @property
    def score(self) -> float:
        return 100.0 * self.ok / self.total if self.total else 0.0


def load_targets(zdir: Path, custom: list[dict] | None = None, user_domains: list[str] | None = None,
                 quick: bool = False) -> list[Target]:
    targets: list[Target] = []
    group = ""
    try:
        lines = (zdir / "utils" / "targets.txt").read_text("utf-8-sig", errors="replace").splitlines()
    except OSError:
        lines = []
    for line in lines:
        s = line.strip()
        if s.startswith("###"):
            group = s.lstrip("#").strip()
            continue
        m = _TARGET_RE.match(line)
        if not m:
            continue
        name, val = m.groups()
        if val.upper().startswith("PING:"):
            host = val[5:].strip()
            targets.append(Target(name, None, host, group))
        else:
            targets.append(Target(name, val, re.sub(r"^https?://", "", val).split("/")[0], group))
    if quick:
        seen: dict[str, int] = {}
        kept = []
        for t in targets:
            seen[t.group] = seen.get(t.group, 0) + 1
            if seen[t.group] <= 2:
                kept.append(t)
        targets = kept
    for c in custom or []:
        url = c.get("url", "").strip()
        if url:
            host = re.sub(r"^https?://", "", url).split("/")[0]
            targets.append(Target(c.get("name") or host, url, host, "Свои цели", True))
    for d in (user_domains or [])[:40]:
        targets.append(Target(d, f"https://{d}", d, "Мои сайты", True))
    return targets


def find_curl() -> str | None:
    if IS_WIN:
        p = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "curl.exe"
        if p.is_file():
            return str(p)
        return shutil.which("curl.exe")
    return shutil.which("curl")


def curl_check(curl: str, url: str, timeout: int, extra: list[str]) -> str:
    cmd = [curl, "-I", "-s", "-m", str(timeout), "--connect-timeout", str(min(2, timeout)),
           "-o", "NUL" if IS_WIN else "/dev/null", "-w", "%{http_code}", "--show-error"]
    if IS_WIN:
        cmd.append("--ssl-no-revoke")
    try:
        r = subprocess.run(cmd + extra + [url], capture_output=True, timeout=timeout + 4,
                           creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    except (subprocess.TimeoutExpired, OSError):
        return "ERROR"
    err = decode(r.stderr)
    if _RE_SSL.search(err):
        return "SSL"
    if _RE_UNSUP.search(err):
        return "UNSUP"
    return "OK" if r.returncode == 0 else "ERROR"


_PING_RE = re.compile(r"[=<]\s*(\d+)\s*[^\d\s]{1,6}\s+TTL=", re.I)


def ping_host(host: str, timeout_ms: int = 1000) -> float | None:
    cmd = (["ping", "-n", "1", "-w", str(timeout_ms), host] if IS_WIN
           else ["ping", "-c", "1", "-W", str(max(1, timeout_ms // 1000)), host])
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout_ms / 1000 + 3,
                           creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = decode(r.stdout)
    if IS_WIN:
        m = _PING_RE.search(out)
        return float(m.group(1)) if m else None
    m = re.search(r"time[=<]\s*([\d.]+)", out)
    return float(m.group(1)) if m else None


def aggregate(results: list[TargetResult]) -> tuple[int, int, float | None]:
    sr = StrategyResult("", results)
    return sr.ok, sr.total, sr.ping_avg



def check_targets(targets: list[Target], curl: str, timeout: int = 5, parallel: int = 12,
                  cancel: threading.Event | None = None, progress=None) -> list[TargetResult]:
    results = [TargetResult(t) for t in targets]
    jobs = []
    for idx, t in enumerate(targets):
        if t.url:
            jobs += [(idx, "curl", label, extra) for label, extra in VARIANTS]
        jobs.append((idx, "ping", "ping", None))
    done = 0

    def work(job):
        idx, kind, label, extra = job
        if cancel is not None and cancel.is_set():
            return idx, kind, label, None
        t = targets[idx]
        if kind == "curl":
            return idx, kind, label, curl_check(curl, t.url, timeout, extra)
        return idx, kind, label, ping_host(t.host)

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
        for fut in as_completed([ex.submit(work, j) for j in jobs]):
            idx, kind, label, val = fut.result()
            if kind == "curl" and val is not None:
                results[idx].tokens[label] = val
            elif kind == "ping":
                results[idx].ping_ms = val
            done += 1
            if progress:
                progress(done, len(jobs))
    return results

class TestSession:
    def __init__(self, runner: Runner, zdir: Path, gf: GameFilter, targets: list[Target],
                 timeout: int = 5, parallel: int = 12, cancel: threading.Event | None = None,
                 emit=None, settle: float = 1.3):
        self.runner, self.zdir, self.gf = runner, zdir, gf
        self.targets, self.timeout, self.parallel = targets, timeout, max(1, parallel)
        self.cancel = cancel or threading.Event()
        self.emit = emit or (lambda *a: None)
        self.settle = settle
        self.curl = find_curl()

    def run(self, strategies: list[Strategy | None]) -> list[StrategyResult]:
        if not self.curl:
            raise RuntimeError("Не найден curl.exe (есть в Windows 10 1803+ и Windows 11)")
        out: list[StrategyResult] = []
        for i, s in enumerate(strategies):
            if self.cancel.is_set():
                break
            name = s.name if s else BASELINE_NAME
            self.emit("strategy_start", i, len(strategies), name)
            res = StrategyResult(name)
            try:
                self.runner.stop()
                if s is not None:
                    self.runner.start(s, self.zdir, self.gf, settle=self.settle)
                res.results = self._check_all()
            except StartError as e:
                res.error = str(e)
            except Exception as e:
                res.error = f"{type(e).__name__}: {e}"
            finally:
                self.runner.stop()
            if self.cancel.is_set():
                break
            out.append(res)
            self.emit("strategy_done", res)
        return out

    def _check_all(self) -> list[TargetResult]:
        return check_targets(self.targets, self.curl, self.timeout, self.parallel, self.cancel,
                             lambda d, t: self.emit("progress", d, t))
