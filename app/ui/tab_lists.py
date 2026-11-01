from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QListWidget,
                               QMessageBox, QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget)

from .. import lists, log
from ..tester import LABELS, Target, check_targets, find_curl
from .style import C, button, card, label
from .workers import run_async


class ListEditor(QWidget):
    changed = Signal()

    def __init__(self, win, key: str, hint: str, placeholder: str, can_check: bool = False):
        super().__init__()
        self.win, self.ctx, self.key = win, win.ctx, key
        self.domain = key != "ip_exclude"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(label(hint, "muted", wrap=True))

        self.input = QPlainTextEdit()
        self.input.setPlaceholderText(placeholder)
        self.input.setFixedHeight(74)
        self.btn_add = button("Добавить", "primary")
        top = QHBoxLayout()
        top.addWidget(self.input, 1)
        top.addWidget(self.btn_add, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)
        self.lbl_result = label("", "muted", wrap=True)
        lay.addWidget(self.lbl_result)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по списку…")
        self.lbl_count = label("", "muted")
        srow = QHBoxLayout()
        srow.addWidget(self.search, 1)
        srow.addWidget(self.lbl_count)
        lay.addLayout(srow)
        self.view = QListWidget()
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        lay.addWidget(self.view, 1)

        self.btn_del = button("Удалить выбранное", "danger")
        self.btn_check = button("Проверить доступность") if can_check else None
        b_imp, b_exp, b_open = button("Импорт из .txt…"), button("Экспорт…"), button("Открыть файл")
        row = QHBoxLayout()
        for b in (self.btn_del, self.btn_check, b_imp, b_exp, b_open):
            if b:
                row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        self.btn_add.clicked.connect(self.add)
        self.btn_del.clicked.connect(self.remove)
        if self.btn_check:
            self.btn_check.clicked.connect(self.check)
        b_imp.clicked.connect(self.import_file)
        b_exp.clicked.connect(self.export_file)
        b_open.clicked.connect(self.open_file)
        self.search.textChanged.connect(self._apply_filter)
        self.ctx.strategies_changed.connect(self.reload)
        self.reload()

    @property
    def ul(self) -> lists.UserList:
        return lists.user_lists(self.ctx.zdir)[self.key]

    def reload(self) -> None:
        self.view.clear()
        if self.ctx.installed:
            self.view.addItems(self.ul.entries())
        self._apply_filter()

    def _apply_filter(self) -> None:
        q = self.search.text().strip().lower()
        shown = 0
        for i in range(self.view.count()):
            it = self.view.item(i)
            hide = bool(q) and q not in it.text().lower()
            it.setHidden(hide)
            shown += not hide
        self.lbl_count.setText(f"{self.view.count()} шт." if not q else f"{shown} из {self.view.count()}")

    def add(self) -> None:
        if not self.ctx.installed:
            return
        items = lists.split_input(self.input.toPlainText())
        if not items:
            return
        added, dup, errors = self.ul.add(items)
        parts = []
        if added:
            parts.append(f"✓ добавлено: {len(added)}")
        if dup:
            parts.append(f"уже были: {len(dup)}")
        if errors:
            parts.append("✖ " + "; ".join(errors[:4]) + (f" (+{len(errors) - 4})" if len(errors) > 4 else ""))
        self.lbl_result.setText("   ·   ".join(parts))
        self.lbl_result.setStyleSheet(f"color: {C['bad'] if errors and not added else C['warn'] if errors else C['ok'] if added else C['muted']};")
        notes = [f"{d} - уже есть во встроенном {m}" for d in added
                 if self.key == "include" and (m := lists.builtin_match(self.ctx.zdir, d))]
        if notes:
            self.lbl_result.setText(self.lbl_result.text() + "\nℹ " + "; ".join(notes[:3]) +
                                    " (поддомены включены автоматически)")
        if added:
            log.info(f"Список «{self.key}»: добавлено {', '.join(added)}")
            self.input.clear()
            self.reload()
            self.changed.emit()

    def remove(self) -> None:
        sel = [i.text() for i in self.view.selectedItems()]
        if not sel:
            return
        self.ul.remove(sel)
        log.info(f"Список «{self.key}»: удалено {', '.join(sel)}")
        self.lbl_result.setText(f"Удалено: {len(sel)}")
        self.lbl_result.setStyleSheet(f"color: {C['muted']};")
        self.reload()
        self.changed.emit()

    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Импорт списка", "", "Текстовые файлы (*.txt);;Все файлы (*)")
        if path:
            try:
                text = Path(path).read_text("utf-8-sig", errors="replace")
            except OSError as e:
                QMessageBox.warning(self, "Импорт", str(e))
                return
            self.input.setPlainText("\n".join(lists.split_input(text)))
            self.add()

    def export_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт списка", f"{self.key}.txt", "Текстовые файлы (*.txt)")
        if path:
            Path(path).write_text("\r\n".join(self.ul.entries()) + "\r\n", encoding="utf-8")

    def open_file(self) -> None:
        if self.ctx.installed:
            self.ul.ensure()
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ul.path)))

    def check(self) -> None:
        curl = find_curl()
        if not curl:
            QMessageBox.warning(self, "Проверка", "Не найден curl.exe")
            return
        names = [i.text() for i in self.view.selectedItems()] or self.ul.entries()[:15]
        if not names:
            self.lbl_result.setText("Список пуст - нечего проверять.")
            return
        targets = [Target(n, f"https://{n}", n) for n in names[:30]]
        self.btn_check.setEnabled(False)
        self.lbl_result.setText(f"Проверяю {len(targets)} сайт(ов) с текущими настройками обхода…")
        self.lbl_result.setStyleSheet(f"color: {C['muted']};")

        def done(results):
            self.btn_check.setEnabled(True)
            lines = []
            for r in results:
                ok = sum(1 for v in r.tokens.values() if v == "OK")
                mark = "✓" if ok == len(r.tokens) and ok else "◐" if ok else "✖"
                toks = " · ".join(f"{l} {'OK' if r.tokens.get(l) == 'OK' else 'нет'}" for l in LABELS)
                ping = f"{r.ping_ms:.0f} мс" if r.ping_ms is not None else "ping -"
                lines.append(f"{mark} {r.target.name}: {toks} · {ping}")
            state, name = self.ctx.state()
            head = f"Обход: {name}" if state == "running" else "Обход не запущен"
            QMessageBox.information(self, "Доступность сайтов", head + "\n\n" + "\n".join(lines))
            self.lbl_result.setText("Проверка завершена.")

        run_async(self, lambda: check_targets(targets, curl, 5, 8), done,
                  lambda m: (self.btn_check.setEnabled(True), QMessageBox.warning(self, "Проверка", m)))


class ListsTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win, self.ctx = win, win.ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        self.banner = QFrame()
        self.banner.setProperty("banner", True)
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 8, 14, 8)
        self.lbl_banner = label("", wrap=True)
        self.btn_restart = button("Перезапустить обход", "primary")
        bl.addWidget(self.lbl_banner, 1)
        bl.addWidget(self.btn_restart)
        self.banner.hide()
        lay.addWidget(self.banner)

        tabs = QTabWidget()
        self.inc = ListEditor(
            win, "include",
            "Сайты, которые нужно разблокировать. Попадают в lists/list-general-user.txt и обрабатываются всеми "
            "стратегиями. Поддомены включаются сами: «youtube.com» покрывает www.youtube.com, m.youtube.com и т.д. "
            "Можно вставлять ссылки целиком - программа вырежет домен. Это файл пользователя: обновления zapret его не трогают.",
            "Вставьте адреса: по одному в строке или через пробел/запятую\nhttps://example.com/page\nanother-site.org",
            can_check=True)
        self.exc = ListEditor(
            win, "exclude",
            "Сайты, которые обход НЕ должен трогать (lists/list-exclude-user.txt). Нужно, если какой-то сервис "
            "ломается при включённом обходе.", "Домены-исключения…")
        self.ipx = ListEditor(
            win, "ip_exclude",
            "IP-адреса и подсети, которые обход не трогает (lists/ipset-exclude-user.txt). Формат: 1.2.3.4 или 10.0.0.0/8.",
            "IP или подсети…")
        tabs.addTab(self.inc, "Мои сайты")
        tabs.addTab(self.exc, "Исключения (домены)")
        tabs.addTab(self.ipx, "Исключения (IP)")
        lay.addWidget(tabs, 1)

        for ed in (self.inc, self.exc, self.ipx):
            ed.changed.connect(self._changed)
        self.btn_restart.clicked.connect(self._restart)

    def _changed(self) -> None:
        self.ctx.lists_changed.emit()
        state, _ = self.ctx.state()
        if state != "running":
            self.banner.hide()
            return
        if self.ctx.cfg["auto_restart_on_lists"] and not self.ctx.busy:
            self.lbl_banner.setText("Список изменён - обход перезапущен, изменения применены.")
            self.btn_restart.hide()
            self.banner.show()
            self.win.restart_strategy(quiet=True)
        else:
            self.lbl_banner.setText("Список изменён. Перезапустите обход, чтобы изменения вступили в силу.")
            self.btn_restart.show()
            self.banner.show()

    def _restart(self) -> None:
        self.banner.hide()
        self.win.restart_strategy(quiet=True)
