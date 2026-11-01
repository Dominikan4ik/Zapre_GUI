from __future__ import annotations

import ipaddress
import os
import re
import tempfile
import urllib.request
from pathlib import Path

PLACEHOLDER_DOMAIN = "domain.example.abc"
PLACEHOLDER_IP = "203.0.113.113/32"
IPSET_URL = ("https://raw.githubusercontent.com/Flowseal/zapret-discord-youtube/"
             "refs/heads/main/.service/ipset-service.txt")

_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
DOMAIN_RE = re.compile(rf"^(?=.{{1,253}}$){_LABEL}(\.{_LABEL})+$")


def normalize_domain(raw: str) -> str:
    s = raw.strip().lower()
    if not s:
        raise ValueError("пустая строка")
    s = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", s)
    s = re.split(r"[/?#]", s, 1)[0]
    s = s.rsplit("@", 1)[-1]
    if s.count(":") == 1:
        s = s.split(":")[0]
    s = s.strip(".")
    for prefix in ("*.", "www."):
        if s.startswith(prefix):
            s = s[len(prefix):]
    try:
        ipaddress.ip_address(s)
        raise ValueError("это IP-адрес - для списка сайтов нужно доменное имя")
    except ValueError as e:
        if "IP-адрес" in str(e):
            raise
    try:
        s = s.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError("некорректное доменное имя") from None
    if not DOMAIN_RE.match(s):
        raise ValueError("некорректное доменное имя")
    return s


def normalize_ip(raw: str) -> str:
    s = raw.strip()
    try:
        return str(ipaddress.ip_network(s, strict=False))
    except ValueError:
        raise ValueError("некорректный IP или подсеть (пример: 1.2.3.0/24)") from None


def split_input(text: str) -> list[str]:
    return [t for t in re.split(r"[\s,;]+", text) if t and not t.startswith("#")]


def _atomic_write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "wb") as f:
        f.write(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    os.replace(tmp, path)


class UserList:
    def __init__(self, path: Path, kind: str, header: list[str] | None = None):
        self.path, self.kind = path, kind
        self.placeholder = PLACEHOLDER_DOMAIN if kind == "domain" else PLACEHOLDER_IP
        self.header = header or []

    def _raw(self) -> list[str]:
        try:
            return [l.strip() for l in self.path.read_text("utf-8-sig", errors="replace").splitlines()]
        except OSError:
            return []

    def entries(self) -> list[str]:
        return [l for l in self._raw() if l and not l.startswith("#") and l != self.placeholder]

    def _write(self, entries: list[str]) -> None:
        lines = list(self.header) + (entries or [self.placeholder])
        _atomic_write(self.path, lines)

    def ensure(self) -> None:
        if not self.path.exists():
            self._write([])

    def add(self, items: list[str]) -> tuple[list[str], list[str], list[str]]:
        current = self.entries()
        seen = set(current)
        added, dup, errors = [], [], []
        norm = normalize_domain if self.kind == "domain" else normalize_ip
        for raw in items:
            try:
                n = norm(raw)
            except ValueError as e:
                errors.append(f"{raw}: {e}")
                continue
            if n in seen:
                dup.append(n)
            else:
                seen.add(n)
                added.append(n)
        if added:
            self._write(current + added)
        return added, dup, errors

    def remove(self, items: list[str]) -> None:
        drop = set(items)
        self._write([e for e in self.entries() if e not in drop])


def user_lists(zdir: Path) -> dict[str, UserList]:
    L = zdir / "lists"
    return {
        "include": UserList(L / "list-general-user.txt", "domain", ["# Never leave this file empty"]),
        "exclude": UserList(L / "list-exclude-user.txt", "domain"),
        "ip_exclude": UserList(L / "ipset-exclude-user.txt", "ip"),
    }


def ensure_user_files(zdir: Path) -> None:
    for ul in user_lists(zdir).values():
        ul.ensure()


def builtin_match(zdir: Path, domain: str) -> str | None:
    labels = domain.split(".")
    candidates = {".".join(labels[i:]) for i in range(len(labels) - 1)}
    for fname in ("list-general.txt", "list-google.txt"):
        try:
            lines = (zdir / "lists" / fname).read_text("utf-8-sig", errors="replace").splitlines()
        except OSError:
            continue
        for l in lines:
            l = l.strip().lower()
            if not l or l.startswith("#"):
                continue
            if l.startswith("^"):
                if l[1:] == domain:
                    return fname
            elif l in candidates:
                return fname
    return None


IPSET_MODES = {"none": "Выключен (по умолчанию)", "any": "Любые IP (any)", "loaded": "Загруженный список"}


def ipset_mode(zdir: Path) -> str:
    p = zdir / "lists" / "ipset-all.txt"
    try:
        raw = p.read_text("utf-8-sig", errors="replace")
    except OSError:
        return "none"
    if not raw.strip():
        return "any"
    if PLACEHOLDER_IP in raw and len(raw.splitlines()) <= 2:
        return "none"
    return "loaded"


def set_ipset_mode(zdir: Path, mode: str) -> str:
    p = zdir / "lists" / "ipset-all.txt"
    backup = p.with_name("ipset-all.txt.backup")
    cur = ipset_mode(zdir)
    if cur == mode:
        return "Режим ipset не изменился"
    if cur == "loaded" and p.exists():
        backup.write_bytes(p.read_bytes())
    if mode == "none":
        _atomic_write(p, [PLACEHOLDER_IP])
    elif mode == "any":
        p.write_bytes(b"")
    else:
        if backup.exists() and backup.stat().st_size > 1024:
            p.write_bytes(backup.read_bytes())
            return "Восстановлен сохранённый список ipset"
        req = urllib.request.Request(IPSET_URL, headers={"User-Agent": "ZapretManager"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        if len(data) < 1024:
            raise RuntimeError("Скачанный список ipset подозрительно короткий")
        p.write_bytes(data)
        return f"Список ipset загружен ({len(data) // 1024} КБ)"
    return f"Режим ipset: {IPSET_MODES[mode]}"
