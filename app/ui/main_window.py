from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget)

from .. import lists, log, winutils
from ..config import APP_NAME, APP_VERSION
from ..log import logs_dir
from ..runner import StartError, service_state, stop_service, winws_pids
from ..strategies import zapret_installed
from .style import C, button, label, make_icon
from .tab_home import HomeTab
from .tab_lists import ListsTab
from .tab_settings import SettingsTab
from .tab_test import TestTab
from .update_ctl import UpdateController
from .workers import run_async

CHECK_INTERVAL_MS = 6 * 3600 * 1000


class MainWindow(QMainWindow):
    def __init__(self, ctx, minimized: bool = False):
        super().__init__()
        self.ctx = ctx
        self.updates = UpdateController(ctx)
        self._quitting = False
        self._hint_shown = False
        self._last_state = None
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setWindowIcon(make_icon())
        self.resize(1120, 780)
        self.setMinimumSize(940, 640)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        self.banner_admin = self._banner("warn", "Нет прав администратора - движок обхода (WinDivert) без них не запустится.",
                                         "Перезапустить от администратора", self.ask_admin)
        self.banner_update, self.lbl_update, self.btn_update_now = self._banner(
            "true", "", "Обновить сейчас", lambda: self.updates.install(self.updates.latest), extra="Позже")
        self.banner_update.hide()
        show_admin = winutils.IS_WIN and not winutils.is_admin()
        self.banner_admin[0].setVisible(show_admin)
        root.addWidget(self.banner_admin[0])
        root.addWidget(self.banner_update)

        self.tabs = QTabWidget()
        self.home = HomeTab(self)
        self.test = TestTab(self)
        self.lists_tab = ListsTab(self)
        self.settings = SettingsTab(self)
        self.log_view = self._build_log_tab()
        for w, t in ((self.home, "Главная"), (self.test, "Тест стратегий"), (self.lists_tab, "Списки сайтов"),
                     (self.settings, "Настройки"), (self.log_view, "Журнал")):
            self.tabs.addTab(w, t)
        root.addWidget(self.tabs, 1)
        self.statusBar().setStyleSheet(f"QStatusBar {{ background: {C['panel']}; color: {C['muted']}; }}")

        self._setup_tray()
        ctx.state_changed.connect(self._on_state)
        ctx.log_message.connect(self._append_log)
        ctx.busy_changed.connect(lambda _: self._on_state())
        self.updates.available.connect(self._on_update_available)
        self.updates.installed.connect(self._on_installed)
        self.updates.failed.connect(lambda m: QMessageBox.warning(self, "Обновление", m))

        self.poll = QTimer(self)
        self.poll.timeout.connect(self._poll_external)
        self.poll.start(5000)
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(lambda: self.ctx.cfg["check_updates"] and self.updates.check())
        self.update_timer.start(CHECK_INTERVAL_MS)
        self._on_state()
        QTimer.singleShot(500, self._startup)
        if not (minimized and self.tray):
            self.show()

    def _build_header(self) -> QWidget:
        f = QFrame()
        f.setStyleSheet(f"QFrame#hdr {{ background: {C['panel']}; border-bottom: 1px solid {C['border']}; }}")
        f.setObjectName("hdr")
        h = QHBoxLayout(f)
        h.setContentsMargins(18, 12, 18, 12)
        logo = QLabel()
        logo.setPixmap(make_icon().pixmap(36, 36))
        h.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label(APP_NAME, "h1"))
        self.lbl_ver = label("", "muted")
        col.addWidget(self.lbl_ver)
        h.addLayout(col)
        h.addStretch(1)
        self.pill = QLabel()
        self.pill.setMinimumWidth(220)
        self.pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(self.pill)
        return f

    def _banner(self, kind: str, text: str, btn_text: str, slot, extra: str | None = None):
        f = QFrame()
        f.setProperty("banner", kind)
        h = QHBoxLayout(f)
        h.setContentsMargins(18, 8, 18, 8)
        lbl = label(text, wrap=True)
        b = button(btn_text, "primary")
        b.clicked.connect(slot)
        h.addWidget(lbl, 1)
        h.addWidget(b)
        if extra:
            later = button(extra)
            later.clicked.connect(f.hide)
            h.addWidget(later)
        return f, lbl, b

    def _build_log_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(18, 16, 18, 16)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(3000)
        self.log_edit.setStyleSheet("font-family: Consolas, 'DejaVu Sans Mono', monospace; font-size: 12px;")
        lay.addWidget(self.log_edit, 1)
        b_clear, b_dir, b_cmd = button("Очистить"), button("Папка журналов"), button("Показать команду winws для выбранной стратегии")
        row = QHBoxLayout()
        for b in (b_clear, b_dir, b_cmd):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        b_clear.clicked.connect(self.log_edit.clear)
        b_dir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir()))))
        b_cmd.clicked.connect(self._show_command)
        return w

    def _show_command(self) -> None:
        s = self.ctx.get_strategy(self.home.selected_name() or "")
        if s:
            self._append_log(f"--- {s.name}\n" + s.command_preview(self.ctx.zdir, self.ctx.game_filter()))

    def _append_log(self, msg: str) -> None:
        self.log_edit.appendPlainText(msg)

    def _setup_tray(self) -> None:
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(make_icon(), self)
        self._menu = QMenu()
        self._menu.addAction("Открыть окно", self.show_window)
        self.act_start = self._menu.addAction("Запустить последнюю стратегию", self._start_last)
        self.act_stop = self._menu.addAction("Остановить обход", self.stop_strategy)
        self._menu.addSeparator()
        self._menu.addAction("Выход", self.quit_app)
        self.tray.setContextMenu(self._menu)
        self.tray.activated.connect(lambda r: self.show_window() if r in (
            QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self.tray.show()

    def show_window(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def _start_last(self) -> None:
        s = self.ctx.get_strategy(self.ctx.cfg["last_strategy"]) or self.ctx.get_strategy(self.ctx.best_from_history() or "")
        if s:
            self.start_strategy(s, quiet=True)
        else:
            self.show_window()

    def _on_state(self) -> None:
        state, name = self.ctx.state()
        self._last_state = (state, name)
        text, color = {"running": (f"●  Работает · {name}", C["ok"]),
                       "external": ("●  winws запущен вне программы", C["warn"]),
                       "stopped": ("●  Остановлен", C["muted"])}[state]
        if self.ctx.busy:
            text, color = "●  Выполняется операция…", C["accent"]
        self.pill.setText(text)
        self.pill.setStyleSheet(f"background: transparent; color: {color}; font-weight: 600; font-size: 14px;"
                                f"border: 1px solid {color}; border-radius: 14px; padding: 6px 14px;")
        v = self.updates.local() if self.ctx.installed else None
        self.lbl_ver.setText(f"zapret {v}" if v else "zapret не установлен")
        if self.tray:
            self.tray.setIcon(make_icon(state))
            self.tray.setToolTip(f"{APP_NAME}: " + {"running": f"работает ({name})", "external": "winws вне программы",
                                                    "stopped": "остановлен"}[state])
            self.act_stop.setEnabled(state != "stopped" and not self.ctx.busy)
            self.act_start.setEnabled(state == "stopped" and not self.ctx.busy and self.ctx.installed)

    def _poll_external(self) -> None:
        if self.ctx.busy or not self.ctx.installed:
            return

        def done(pids):
            if self.ctx.busy:
                return
            self.ctx.set_external(bool(pids) and self.ctx.running_strategy() is None)
            if self._last_state != self.ctx.state():
                self.ctx.state_changed.emit()
        run_async(self, winws_pids, done)

    def ask_admin(self) -> None:
        if QMessageBox.question(self, "Нужны права администратора",
                                "Движок обхода (WinDivert) работает только с правами администратора.\n"
                                "Перезапустить программу от имени администратора?") == QMessageBox.StandardButton.Yes:
            if winutils.relaunch_as_admin():
                self._quitting = True
                QApplication.quit()

    def _preflight(self) -> bool:
        if winutils.IS_WIN and not winutils.is_admin():
            self.ask_admin()
            return False
        if service_state() == "RUNNING":
            if QMessageBox.question(self, "Служба zapret", "Запущена служба zapret (установлена через service.bat). "
                                    "Она конфликтует с запуском из программы.\nОстановить службу?"
                                    ) != QMessageBox.StandardButton.Yes:
                return False
            stop_service()
        if self.ctx.external and QMessageBox.question(
                self, "winws уже запущен", "winws.exe запущен вне программы (bat-файл).\n"
                "Остановить его и запустить выбранную стратегию?") != QMessageBox.StandardButton.Yes:
            return False
        return True

    def start_strategy(self, s, quiet: bool = False) -> None:
        if self.ctx.busy or not self._preflight():
            return
        self.ctx.set_busy(True)
        gf = self.ctx.game_filter()

        def done(_):
            self.ctx.cfg["last_strategy"] = s.name
            self.ctx.external = False
            self.ctx.set_busy(False)
            self.ctx.state_changed.emit()
            if self.tray and not quiet:
                self.tray.showMessage(APP_NAME, f"Обход запущен: {s.name}", QSystemTrayIcon.MessageIcon.Information, 2500)

        def fail(msg):
            self.ctx.set_busy(False)
            self.ctx.state_changed.emit()
            log.error(f"Не удалось запустить «{s.name}»: {msg}")
            QMessageBox.critical(self, "Не удалось запустить", f"Стратегия «{s.name}»:\n\n{msg}")
        run_async(self, lambda: self.ctx.runner.start(s, self.ctx.zdir, gf), done, fail)

    def stop_strategy(self) -> None:
        if self.ctx.busy:
            return
        self.ctx.set_busy(True)

        def done(_):
            self.ctx.external = False
            self.ctx.set_busy(False)
            self.ctx.state_changed.emit()
        run_async(self, self.ctx.runner.stop, done, lambda m: (self.ctx.set_busy(False), log.error(m)))

    def restart_strategy(self, quiet: bool = False) -> None:
        s = self.ctx.running_strategy()
        if s:
            self.start_strategy(s, quiet=True)

    def download_zapret(self) -> None:
        if self.ctx.busy:
            return
        self.statusBar().showMessage("Скачиваю последнюю версию zapret…")
        self.updates.install(None)

    def pick_zapret_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Выберите папку zapret (где лежит bin/winws.exe)",
                                             str(self.ctx.zdir.parent))
        if not d:
            return
        from pathlib import Path
        p = Path(d)
        if not zapret_installed(p):
            sub = [c for c in p.iterdir() if c.is_dir() and zapret_installed(c)] if p.is_dir() else []
            if sub:
                p = sub[0]
            else:
                QMessageBox.warning(self, "Папка zapret", "В этой папке нет bin/winws.exe.")
                return
        self.ctx.cfg["zapret_dir"] = str(p)
        self.ctx.reload()
        log.info(f"Папка zapret: {p}")

    def _on_update_available(self, rel, local: str) -> None:
        if not self.ctx.installed:
            return
        self.lbl_update.setText(f"Доступна новая версия zapret: {rel.tag} (у вас {local or '-'}). "
                                f"Списки «Мои сайты» и настройки сохранятся.")
        self.banner_update.show()

    def _on_installed(self, res, was) -> None:
        self.banner_update.hide()
        self.statusBar().showMessage(f"zapret обновлён до версии {res.version}", 8000)
        if res.orphans:
            shown = "\n".join("• " + d for d in res.orphans[:12]) + ("\n…" if len(res.orphans) > 12 else "")
            if QMessageBox.question(
                    self, "Обновление zapret",
                    "В старых системных списках были сайты, которых нет в новой версии "
                    "(возможно, вы добавляли их вручную):\n\n" + shown +
                    "\n\nПеренести их в «Мои сайты», чтобы обновления их больше не затирали?"
            ) == QMessageBox.StandardButton.Yes:
                added, _, _ = lists.user_lists(self.ctx.zdir)["include"].add(res.orphans)
                log.info(f"Перенесено в «Мои сайты»: {', '.join(added)}")
                self.lists_tab.inc.reload()
        if was:
            s = self.ctx.get_strategy(was)
            if s:
                self.start_strategy(s, quiet=True)

    def _startup(self) -> None:
        self.ctx.reload()
        log.info(f"{APP_NAME} {APP_VERSION} · папка zapret: {self.ctx.zdir} · "
                 f"стратегий: {len(self.ctx.strategies)}")
        if not self.ctx.installed:
            if self.isVisible() and QMessageBox.question(
                    self, "zapret не найден", f"Папка zapret не найдена:\n{self.ctx.zdir}\n\n"
                    "Скачать последнюю версию из релизов Flowseal?") == QMessageBox.StandardButton.Yes:
                self.download_zapret()
            return
        cfg = self.ctx.cfg
        if cfg["autostart_strategy"] and cfg["last_strategy"] and (winutils.is_admin() or not winutils.IS_WIN):
            s = self.ctx.get_strategy(cfg["last_strategy"])
            if s:
                self.start_strategy(s, quiet=True)
        if cfg["check_updates"]:
            self.updates.check()

    def quit_app(self) -> None:
        self._quitting = True
        self.close()

    def closeEvent(self, e) -> None:
        if not self._quitting and self.tray and self.ctx.cfg["minimize_to_tray"]:
            e.ignore()
            self.hide()
            if not self._hint_shown:
                self.tray.showMessage(APP_NAME, "Программа свёрнута в трей. Обход продолжает работать.",
                                      QSystemTrayIcon.MessageIcon.Information, 3000)
                self._hint_shown = True
            return
        w = self.test.worker
        if w is not None and w.isRunning():
            w.cancel()
            w.wait(15000)
        if self.ctx.cfg["stop_on_exit"]:
            self.ctx.runner.stop()
        self.ctx.cfg.save()
        if self.tray:
            self.tray.hide()
        e.accept()
        QApplication.quit()
