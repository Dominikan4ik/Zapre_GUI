from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import log
from .config import REPO
from .lists import normalize_domain

UA = "ZapretManager/1.0"
MANIFEST = ".manager_manifest.json"
VERSION_FILE = ".manager_version"
EXACT_PRESERVE = {"lists/ipset-all.txt", "utils/game_filter.enabled", "utils/check_updates.enabled"}


class UpdateError(Exception):
    pass


@dataclass
class Release:
    tag: str
    zip_url: str
    page_url: str
    notes: str = ""
    size: int = 0


@dataclass
class InstallResult:
    version: str
    backup: Path | None = None
    orphans: list = field(default_factory=list)


def version_key(v: str) -> tuple:
    m = re.match(r"v?(\d+(?:\.\d+)*)([a-z]*)", (v or "").strip().lower())
    if not m:
        return (0, 0, 0, 0, 0)
    nums = [int(x) for x in m.group(1).split(".")][:4]
    nums += [0] * (4 - len(nums))
    return (*nums, sum(ord(c) - 96 for c in m.group(2)))


def is_newer(remote: str, local: str | None) -> bool:
    return not local or version_key(remote) > version_key(local)


def local_version(zdir: Path) -> str | None:
    try:
        text = (zdir / "service.bat").read_text("utf-8-sig", errors="replace")
        m = re.search(r'set\s+"LOCAL_VERSION=([^"]+)"', text, re.I)
        if m:
            return m.group(1).strip()
    except OSError:
        pass
    try:
        return (zdir / VERSION_FILE).read_text("utf-8").strip() or None
    except OSError:
        return None


def _open(url: str, timeout: float, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def _asset_url(tag: str) -> str:
    return f"https://github.com/{REPO}/releases/download/{tag}/zapret-discord-youtube-{tag}.zip"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def fetch_latest(timeout: float = 12) -> Release:
    errors = []
    try:
        with _open(f"https://api.github.com/repos/{REPO}/releases/latest", timeout,
                   {"Accept": "application/vnd.github+json"}) as r:
            d = json.load(r)
        tag = d["tag_name"]
        asset = next((a for a in d.get("assets", []) if a["name"].lower().endswith(".zip")), None)
        return Release(tag, asset["browser_download_url"] if asset else _asset_url(tag),
                       d.get("html_url") or f"https://github.com/{REPO}/releases/tag/{tag}",
                       (d.get("body") or "")[:3000], asset.get("size", 0) if asset else 0)
    except Exception as e:
        errors.append(f"API: {e}")
    try:
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            opener.open(urllib.request.Request(f"https://github.com/{REPO}/releases/latest",
                                               headers={"User-Agent": UA}), timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                tag = (e.headers.get("Location") or "").rstrip("/").rsplit("/", 1)[-1]
                if tag:
                    return Release(tag, _asset_url(tag), f"https://github.com/{REPO}/releases/tag/{tag}")
            raise
    except Exception as e:
        errors.append(f"redirect: {e}")
    raise UpdateError("Не удалось получить информацию о релизе (" + "; ".join(errors) + ")")


def download(rel: Release, dest: Path, progress=None, cancel=None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".part")
    try:
        with _open(rel.zip_url, 30) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or rel.size or 0)
            done = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateError("Загрузка отменена")
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except Exception as e:
        part.unlink(missing_ok=True)
        raise UpdateError(f"Ошибка загрузки: {e}") from e
    part.replace(dest)
    return dest


def _root_prefix(zf: zipfile.ZipFile) -> str:
    for n in zf.namelist():
        if n.lower().endswith("bin/winws.exe"):
            return n[: -len("bin/winws.exe")]
    raise UpdateError("В архиве нет bin/winws.exe - это не сборка zapret-discord-youtube")


def _safe_extract(zf: zipfile.ZipFile, prefix: str, dest: Path) -> list[str]:
    root = dest.resolve()
    rels = []
    for info in zf.infolist():
        if info.is_dir() or not info.filename.startswith(prefix):
            continue
        rel = info.filename[len(prefix):]
        target = (dest / rel).resolve()
        if root != target and root not in target.parents:
            raise UpdateError(f"Небезопасный путь в архиве: {info.filename}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)
        rels.append(rel.replace("\\", "/"))
    return rels


def _is_preserved(rel: str) -> bool:
    return rel in EXACT_PRESERVE or bool(re.fullmatch(r"lists/[^/]+-user\.txt", rel))


def _read_lines(p: Path) -> set[str]:
    try:
        return {l.strip().lower() for l in p.read_text("utf-8-sig", errors="replace").splitlines()
                if l.strip() and not l.strip().startswith("#")}
    except OSError:
        return set()


def make_backup(zdir: Path, backups: Path, keep: int = 3) -> Path | None:
    if not zdir.is_dir() or not any(zdir.iterdir()):
        return None
    backups.mkdir(parents=True, exist_ok=True)
    ver = local_version(zdir) or "unknown"
    path = backups / f"zapret-{ver}-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in zdir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(zdir).as_posix())
    old = sorted(backups.glob("zapret-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in old[keep:]:
        p.unlink(missing_ok=True)
    return path


def restore_backup(zip_path: Path, zdir: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        _safe_extract(zf, "", zdir)


def install(zip_path: Path, zdir: Path, backups: Path, tag: str = "") -> InstallResult:
    if not zipfile.is_zipfile(zip_path):
        raise UpdateError("Скачанный файл повреждён (это не zip)")
    tmp = Path(tempfile.mkdtemp(prefix="zm_update_"))
    backup = None
    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad = zf.testzip()
            if bad:
                raise UpdateError(f"Повреждён файл в архиве: {bad}")
            new_files = _safe_extract(zf, _root_prefix(zf), tmp)

        orphans: list[str] = []
        for name in ("list-general.txt", "list-google.txt"):
            old = _read_lines(zdir / "lists" / name)
            new = _read_lines(tmp / "lists" / name)
            for line in sorted(old - new):
                if line.startswith("^"):
                    continue
                try:
                    d = normalize_domain(line)
                except ValueError:
                    continue
                if d not in orphans:
                    orphans.append(d)

        backup = make_backup(zdir, backups)
        old_manifest: list[str] = []
        try:
            old_manifest = json.loads((zdir / MANIFEST).read_text("utf-8"))
        except (OSError, ValueError):
            pass

        failures = []
        try:
            for rel in new_files:
                dst = zdir / rel
                if _is_preserved(rel) and dst.exists():
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(tmp / rel, dst)
                except OSError as e:
                    failures.append(f"{rel}: {e}")
            if failures:
                raise UpdateError("Не удалось заменить файлы (закройте обход/антивирус):\n" + "\n".join(failures[:5]))
            for rel in set(old_manifest) - set(new_files):
                if not _is_preserved(rel):
                    (zdir / rel).unlink(missing_ok=True)
        except UpdateError:
            if backup:
                restore_backup(backup, zdir)
                log.warn("Обновление не удалось - восстановлена резервная копия")
            raise

        (zdir / MANIFEST).write_text(json.dumps(sorted(new_files)), "utf-8")
        ver = local_version(zdir) or tag
        if tag:
            (zdir / VERSION_FILE).write_text(tag, "utf-8")
        return InstallResult(ver, backup, orphans)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
