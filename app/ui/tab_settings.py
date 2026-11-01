from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QLineEdit, QMessageBox, QProgressBar,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import lists, log, winutils
from ..config import APP_NAME, APP_VERSION, app_dir
from ..strategies import GAME_MODES, _PORTS_RE, write_game_filter
from .style import C, button, card, label
from .workers import run_async


class SettingsTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win, self.ctx = win, win.ctx
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        cfg = self.ctx.cfg

        c, l = card("Папка zapret")
        self.lbl_dir = label("", wrap=True)
        b_pick, b_open = button("Изменить…"), button("Открыть папку")
        l.addWidget(self.lbl_dir)
        l.addLayout(self._row(b_pick, b_open))
        lay.addWidget(c)
        b_pick.clicked.connect(win.pick_zapret_dir)
        b_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctx.zdir))))

        c, l = card("Обновления zapret", "Берутся из github.com/Flowseal/zapret-discord-youtube/releases. "
                                         "Ваши списки («Мои сайты»), игровой фильтр и режим ipset сохраняются, "
                                         "перед заменой файлов делается резервная копия.")
        self.lbl_local = label("")
        self.lbl_latest = label("Нажмите «Проверить сейчас», чтобы узнать о новой версии.", "muted")
        self.bar = QProgressBar()
        self.bar.hide()
        self.btn_check = button("Проверить сейчас")
        self.btn_update = button("Обновить", "primary")
        self.btn_update.hide()
        b_bk = button("Резервные копии")
        self.cb_check = QCheckBox("Проверять обновления при запуске программы (и раз в 6 часов)")
        self.cb_auto = QCheckBox("Устанавливать обновления автоматически (обход на время установки останавливается)")
        for w in (self.lbl_local, self.lbl_latest, self.bar):
            l.addWidget(w)
        l.addLayout(self._row(self.btn_check, self.btn_update, b_bk))
        l.addWidget(self.cb_check)
        l.addWidget(self.cb_auto)
        lay.addWidget(c)
        self.btn_check.clicked.connect(lambda: win.updates.check(manual=True))
        self.btn_update.clicked.connect(lambda: win.updates.install(win.updates.latest))
        b_bk.clicked.connect(lambda: self._open_dir(app_dir() / "backups"))
        self._bind(self.cb_check, "check_updates")
        self._bind(self.cb_auto, "auto_install_updates")
        u = win.updates
        u.checking.connect(lambda: self.lbl_latest.setText("Проверяю наличие обновлений…"))
        u.available.connect(self._on_available)
        u.uptodate.connect(lambda v: (self.lbl_latest.setText("✓ Установлена последняя версия"),
                                      self.btn_update.hide()))
        u.progress.connect(self._on_progress)
        u.installed.connect(lambda *_: (self.bar.hide(), self.btn_update.hide(), self.refresh()))
        u.failed.connect(lambda m: (self.bar.hide(), self.lbl_latest.setText("Не удалось: " + m[:140])))

        c, l = card("Поведение программы")
        self.cb_autostart = QCheckBox("При запуске программы автоматически включать последнюю стратегию")
        self.cb_logon = QCheckBox("Запускать программу при входе в Windows (свёрнутой в трей, с правами администратора)")
        self.cb_tray = QCheckBox("Кнопка «закрыть» сворачивает в трей")
        self.cb_stop = QCheckBox("Останавливать обход при выходе из программы")
        self.cb_lists = QCheckBox("Автоматически перезапускать обход после изменения списков")
        for cb, key in ((self.cb_autostart, "autostart_strategy"), (self.cb_tray, "minimize_to_tray"),
                        (self.cb_stop, "stop_on_exit"), (self.cb_lists, "auto_restart_on_lists")):
            self._bind(cb, key)
            l.addWidget(cb)
        l.insertWidget(2, self.cb_logon)
        lay.addWidget(c)
        self.cb_logon.toggled.connect(self._toggle_logon)

        c, l = card("Игровой фильтр", "Расширяет обход на диапазон портов для игр и голосовых чатов. "
                                      "Увеличивает нагрузку - включайте, только если игры не работают.")
        self.cmb_game = QComboBox()
        for k, v in GAME_MODES.items():
            self.cmb_game.addItem(v, k)
        self.ed_tcp, self.ed_udp = QLineEdit(), QLineEdit()
        self.ed_tcp.setFixedWidth(120)
        self.ed_udp.setFixedWidth(120)
        b_game = button("Применить")
        l.addLayout(self._row(label("Режим:"), self.cmb_game, label("TCP-порты:"), self.ed_tcp,
                              label("UDP-порты:"), self.ed_udp, b_game))
        lay.addWidget(c)
        b_game.clicked.connect(self._apply_game)

        c, l = card("IPSet (список IP-адресов)", "Нужен для обхода по IP-адресам (голос Discord, игры). "
                                                 "«Выключен» - только по доменным спискам. «Загруженный список» "
                                                 "скачивается из репозитория Flowseal.")
        self.cmb_ipset = QComboBox()
        for k, v in lists.IPSET_MODES.items():
            self.cmb_ipset.addItem(v, k)
        b_ip = button("Применить")
        l.addLayout(self._row(label("Режим:"), self.cmb_ipset, b_ip))
        lay.addWidget(c)
        b_ip.clicked.connect(self._apply_ipset)

        c, l = card("О программе")
        self.lbl_admin = label("")
        l.addWidget(label(f"{APP_NAME} {APP_VERSION} - графическая оболочка для zapret-discord-youtube (Flowseal)."))
        l.addWidget(self.lbl_admin)
        b_logs = button("Папка с журналами")
        l.addLayout(self._row(b_logs))
        b_logs.clicked.connect(lambda: self._open_dir(app_dir() / "logs"))
        lay.addWidget(c)
        lay.addStretch(1)

        self.ctx.strategies_changed.connect(self.refresh)
        self.refresh()

    @staticmethod
    def _row(*widgets):
        h = QHBoxLayout()
        h.setSpacing(8)
        for w in widgets:
            h.addWidget(w)
        h.addStretch(1)
        return h

    @staticmethod
    def _open_dir(path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _bind(self, cb: QCheckBox, key: str) -> None:
        cb.setChecked(bool(self.ctx.cfg[key]))
        cb.toggled.connect(lambda v: self.ctx.cfg.__setitem__(key, bool(v)))

    def refresh(self) -> None:
        self.lbl_dir.setText(str(self.ctx.zdir) + ("" if self.ctx.installed else "   - zapret здесь не найден"))
        local = self.win.updates.local()
        self.lbl_local.setText(f"Установленная версия zapret: {local or 'не определена'}")
        if self.ctx.installed:
            gf = self.ctx.game_filter()
            self.cmb_game.setCurrentIndex(max(0, self.cmb_game.findData(gf.mode)))
            self.ed_tcp.setText(gf.tcp)
            self.ed_udp.setText(gf.udp)
            self.cmb_ipset.setCurrentIndex(max(0, self.cmb_ipset.findData(lists.ipset_mode(self.ctx.zdir))))
        admin = winutils.is_admin()
        self.lbl_admin.setText("✓ Запущено с правами администратора" if admin else
                               "⚠ Нет прав администратора - обход не сможет запуститься")
        self.lbl_admin.setStyleSheet(f"color: {C['ok'] if admin else C['warn']};")
        if winutils.IS_WIN:
            run_async(self, winutils.autostart_enabled, self._set_logon_state)

    def _set_logon_state(self, value: bool) -> None:
        self.cb_logon.blockSignals(True)
        self.cb_logon.setChecked(bool(value))
        self.cb_logon.blockSignals(False)

    def _toggle_logon(self, value: bool) -> None:
        def done(res):
            ok, msg = res
            if not ok:
                self._set_logon_state(not value)
                QMessageBox.warning(self, "Автозапуск", msg or "Не удалось изменить автозапуск")
        run_async(self, lambda: winutils.set_autostart(value), done)

    def _on_available(self, rel, local: str) -> None:
        self.lbl_latest.setText(f"⬆ Доступна версия {rel.tag}")
        self.btn_update.setText(f"Обновить до {rel.tag}")
        self.btn_update.show()

    def _on_progress(self, done: int, total: int) -> None:
        self.bar.show()
        self.bar.setRange(0, total or 0)
        self.bar.setValue(done)
        self.bar.setFormat(f"Загрузка… {done // 1024} / {total // 1024} КБ" if total else "Загрузка…")

    def _apply_game(self) -> None:
        if not self.ctx.installed:
            return
        tcp, udp = self.ed_tcp.text().strip(), self.ed_udp.text().strip()
        if not (_PORTS_RE.match(tcp) and _PORTS_RE.match(udp)):
            QMessageBox.warning(self, "Игровой фильтр", "Порты: число или диапазон, например 1024-65535")
            return
        gf = self.ctx.game_filter()
        gf.mode, gf.tcp, gf.udp = self.cmb_game.currentData(), tcp, udp
        write_game_filter(self.ctx.zdir, gf)
        log.info(f"Игровой фильтр: {GAME_MODES[gf.mode]} (TCP {tcp}, UDP {udp})")
        if self.ctx.running_strategy():
            self.win.restart_strategy(quiet=True)

    def _apply_ipset(self) -> None:
        if not self.ctx.installed:
            return
        mode = self.cmb_ipset.currentData()
        self.cmb_ipset.setEnabled(False)

        def done(msg):
            self.cmb_ipset.setEnabled(True)
            log.info(msg)
            if self.ctx.running_strategy():
                self.win.restart_strategy(quiet=True)

        def fail(msg):
            self.cmb_ipset.setEnabled(True)
            QMessageBox.warning(self, "IPSet", f"Не удалось переключить режим: {msg}")
            self.refresh()
        run_async(self, lambda: lists.set_ipset_mode(self.ctx.zdir, mode), done, fail)
