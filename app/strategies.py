from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

GAME_FILE = Path("utils") / "game_filter.enabled"
_PORTS_RE = re.compile(r"^\d{1,5}(-\d{1,5})?$")
GAME_MODES = {"disabled": "Отключён", "all": "TCP и UDP", "tcp": "Только TCP", "udp": "Только UDP"}


@dataclass
class GameFilter:
    mode: str = "disabled"
    tcp: str = "1024-65535"
    udp: str = "1024-65535"

    @property
    def tcp_value(self) -> str:
        return self.tcp if self.mode in ("all", "tcp") else "12"

    @property
    def udp_value(self) -> str:
        return self.udp if self.mode in ("all", "udp") else "12"


def read_game_filter(zdir: Path) -> GameFilter:
    gf = GameFilter()
    try:
        text = (zdir / GAME_FILE).read_text("utf-8", errors="replace")
    except OSError:
        return gf
    for line in text.splitlines():
        k, _, v = line.strip().partition("=")
        k, v = k.strip().lower(), v.strip().lower()
        if k == "mode" and v in GAME_MODES:
            gf.mode = v
        elif k == "tcp" and _PORTS_RE.match(v):
            gf.tcp = v
        elif k == "udp" and _PORTS_RE.match(v):
            gf.udp = v
        elif not v and k in GAME_MODES:
            gf.mode = k
    return gf


def write_game_filter(zdir: Path, gf: GameFilter) -> None:
    p = zdir / GAME_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"mode={gf.mode}\r\ntcp={gf.tcp}\r\nudp={gf.udp}\r\n", encoding="utf-8")


def extract_command(text: str) -> str | None:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for i, line in enumerate(lines):
        if line.lstrip().lower().startswith(("rem ", "::")):
            continue
        m = re.search(r'winws\.exe"?\s*(.*)$', line, re.I)
        if not m or "--" not in m.group(1):
            continue
        parts = [m.group(1).rstrip()]
        j = i
        while parts[-1].endswith("^") and j + 1 < len(lines):
            parts[-1] = parts[-1][:-1]
            j += 1
            parts.append(lines[j].strip())
        return " ".join(p.strip() for p in parts)
    return None


def tokenize(cmd: str) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    in_q = has = False
    i = 0
    while i < len(cmd):
        ch = cmd[i]
        if ch == '"':
            in_q, has = not in_q, True
        elif ch == "^" and not in_q and i + 1 < len(cmd):
            i += 1
            cur.append(cmd[i])
            has = True
        elif ch.isspace() and not in_q:
            if has:
                out.append("".join(cur))
                cur, has = [], False
        else:
            cur.append(ch)
            has = True
        i += 1
    if has:
        out.append("".join(cur))
    return out


@dataclass
class Strategy:
    name: str
    path: Path
    template: str

    def build_args(self, zdir: Path, gf: GameFilter) -> list[str]:
        sep = os.sep
        env = {
            "bin": str(zdir / "bin") + sep,
            "lists": str(zdir / "lists") + sep,
            "~dp0": str(zdir) + sep,
            "gamefiltertcp": gf.tcp_value,
            "gamefilterudp": gf.udp_value,
            "gamefilter": gf.tcp_value if gf.mode == "tcp" else gf.udp_value if gf.mode == "udp"
            else gf.tcp_value if gf.mode == "all" else "12",
        }
        text = re.sub(r"%([~\w]+)%", lambda m: env.get(m.group(1).lower(), m.group(0)), self.template)
        return tokenize(text)

    def command_preview(self, zdir: Path, gf: GameFilter) -> str:
        return "winws.exe " + " ".join(self.build_args(zdir, gf))


def _sort_key(name: str):
    num = re.search(r"(\d+)", name)
    base = re.sub(r"\d+", "", name).lower()
    return (0 if name.lower() == "general" else 1, base, int(num.group(1)) if num else 0)


def discover(zdir: Path) -> list[Strategy]:
    result: list[Strategy] = []
    if not zdir.is_dir():
        return result
    for p in zdir.glob("*.bat"):
        if p.name.lower() == "service.bat":
            continue
        try:
            text = p.read_text("utf-8-sig", errors="replace")
        except OSError:
            continue
        cmd = extract_command(text)
        if cmd:
            result.append(Strategy(name=p.stem, path=p, template=cmd))
    result.sort(key=lambda s: _sort_key(s.name))
    return result


def zapret_installed(zdir: Path) -> bool:
    return (zdir / "bin" / "winws.exe").is_file()
