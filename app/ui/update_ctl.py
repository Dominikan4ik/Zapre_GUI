from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .. import log, updater
from ..config import app_dir
from ..runner import service_state, stop_service
from .workers import run_async


class UpdateController(QObject):
    available = Signal(object, str)
    uptodate = Signal(str)
    checking = Signal()
    progress = Signal(int, int)
    installed = Signal(object, object)
    failed = Signal(str)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.latest: updater.Release | None = None

    def local(self) -> str | None:
        return updater.local_version(self.ctx.zdir) if self.ctx.installed else None

    def check(self, manual: bool = False) -> None:
        self.checking.emit()
        run_async(self, updater.fetch_latest, lambda r: self._checked(r, manual),
                  lambda m: self._check_failed(m, manual))

    def _checked(self, rel, manual: bool) -> None:
        self.latest = rel
        local = self.local()
        if updater.is_newer(rel.tag, local):
            log.info(f"Доступна версия zapret {rel.tag} (установлена: {local or 'нет'})")
            self.available.emit(rel, local or "")
            if self.ctx.cfg["auto_install_updates"] and self.ctx.installed and not manual and not self.ctx.busy:
                self.install(rel)
        else:
            log.info(f"Установлена актуальная версия zapret: {local}")
            self.uptodate.emit(local or "")

    def _check_failed(self, msg: str, manual: bool) -> None:
        log.warn(f"Проверка обновлений не удалась: {msg}")
        if manual:
            self.failed.emit(msg)

    def install(self, rel: updater.Release | None = None) -> None:
        if self.ctx.busy:
            return
        running = self.ctx.running_strategy()
        was = running.name if running else None
        self.ctx.set_busy(True)

        def job():
            release = rel or updater.fetch_latest()
            log.info(f"Скачиваю zapret {release.tag}…")
            self.ctx.runner.stop(drop_driver=True)
            if service_state() == "RUNNING":
                stop_service()
            dl = app_dir() / "downloads" / f"zapret-{release.tag}.zip"
            updater.download(release, dl, progress=self.progress.emit)
            log.info("Устанавливаю обновление…")
            res = updater.install(dl, self.ctx.zdir, app_dir() / "backups", tag=release.tag)
            dl.unlink(missing_ok=True)
            return res

        run_async(self, job, lambda res: self._installed(res, was), self._install_failed)

    def _installed(self, res, was) -> None:
        self.ctx.set_busy(False)
        log.info(f"zapret обновлён до версии {res.version}")
        self.ctx.reload()
        self.latest = None
        self.installed.emit(res, was)

    def _install_failed(self, msg: str) -> None:
        self.ctx.set_busy(False)
        log.error(f"Обновление не удалось: {msg}")
        self.ctx.reload()
        self.failed.emit(msg)
