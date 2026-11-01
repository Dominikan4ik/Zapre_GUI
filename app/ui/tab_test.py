from __future__ import annotations

import csv
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QFrame, QHeaderView, QHBoxLayout, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QScrollArea, QSpinBox, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import lists, log
from ..runner import service_state, stop_service
from ..tester import BASELINE_NAME, LABELS, StrategyResult, TestSession, find_curl, load_targets
from ..winutils import is_admin
from .style import C, button, card, label, score_color
from .tab_home import NumItem
from .workers import TestWorker, run_async

TOKEN_TEXT = {"OK": ("OK", C["ok"]), "ERROR": ("ошибка", C["bad"]), "SSL": ("DNS/SSL", C["bad"]),
              "UNSUP": ("н/д", C["warn"])}


class TestTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win, self.ctx = win, win.ctx
        self.worker: TestWorker | None = None
        self.results: dict[str, StrategyResult] = {}
        self._restore: str | None = None

        split = QSplitter(Qt.Orientation.Horizontal)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.addWidget(split)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 10, 0)
        ll.setSpacing(10)
        c1, l1 = card("Стратегии для теста", "Проверяются по очереди; внутри каждой - все цели сразу.")
        self.list = QListWidget()
        self.list.setMinimumHeight(170)
        l1.addWidget(self.list, 1)
        b_all, b_none, b_inv = button("Все"), button("Ничего"), button("Инвертировать")
        l1.addLayout(self._row(b_all, b_none, b_inv))
        ll.addWidget(c1, 1)

        c2, l2 = card("Параметры")
        t = self.ctx.cfg["test"]
        self.sp_timeout, self.sp_parallel = QSpinBox(), QSpinBox()
        self.sp_timeout.setRange(2, 20)
        self.sp_timeout.setValue(t["timeout"])
        self.sp_timeout.setSuffix(" с")
        self.sp_parallel.setRange(1, 32)
        self.sp_parallel.setValue(t["parallel"])
        self.cb_quick = QCheckBox("Быстрый режим (по 2 цели на сервис)")
        self.cb_quick.setChecked(t["quick"])
        self.cb_user = QCheckBox("Проверять и «Мои сайты» из списков")
        self.cb_user.setChecked(t["user_sites"])
        l2.addLayout(self._row(label("Таймаут:"), self.sp_timeout, label("Потоков:"), self.sp_parallel))
        l2.addWidget(self.cb_quick)
        l2.addWidget(self.cb_user)
        self.lbl_targets = label("", "muted")
        l2.addWidget(self.lbl_targets)
        ll.addWidget(c2)

        c3, l3 = card("Свои цели для теста")
        self.ed_url = QLineEdit()
        self.ed_url.setPlaceholderText("https://сайт, который проверять у каждой стратегии")
        b_add, b_del = button("+"), button("-")
        b_add.setFixedWidth(40)
        b_del.setFixedWidth(40)
        b_add.setToolTip("Добавить цель")
        b_del.setToolTip("Удалить выбранную цель из списка ниже")
        l3.addLayout(self._row(self.ed_url, b_add, b_del, stretch_end=False))
        self.custom = QListWidget()
        self.custom.setMaximumHeight(62)
        l3.addWidget(self.custom)
        ll.addWidget(c3)

        self.btn_run = button("▶  Запустить тест", "primary")
        self.btn_stop = button("■  Остановить", "danger")
        self.btn_stop.setEnabled(False)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(left)
        split.addWidget(scroll)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(10, 0, 0, 0)
        rl.setSpacing(10)
        rl.addLayout(self._row(self.btn_run, self.btn_stop))
        self.bar = QProgressBar()
        self.bar.setValue(0)
        self.lbl_status = label("Выберите стратегии и нажмите «Запустить тест».", "muted", wrap=True)
        rl.addWidget(self.lbl_status)
        rl.addWidget(self.bar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Стратегия", "Оценка", "HTTP", "TLS 1.2", "TLS 1.3", "Пинг"])
        self._setup_table(self.table)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 6):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(c, 78 if c != 1 else 96)
        rl.addWidget(self.table, 3)

        rl.addWidget(label("Детали по выбранной стратегии", "h2"))
        self.detail = QTableWidget(0, 5)
        self.detail.setHorizontalHeaderLabels(["Цель", "HTTP", "TLS 1.2", "TLS 1.3", "Пинг"])
        self._setup_table(self.detail)
        dh = self.detail.horizontalHeader()
        dh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 5):
            dh.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            self.detail.setColumnWidth(c, 78)
        rl.addWidget(self.detail, 2)

        self.btn_apply = button("Применить выбранную")
        self.btn_best = button("★  Применить лучшую", "primary")
        self.btn_export = button("Экспорт в CSV…")
        rl.addLayout(self._row(self.btn_apply, self.btn_best, self.btn_export))
        split.addWidget(right)
        split.setSizes([410, 700])

        b_all.clicked.connect(lambda: self._check_all(True))
        b_none.clicked.connect(lambda: self._check_all(False))
        b_inv.clicked.connect(self._invert)
        b_add.clicked.connect(self._add_custom)
        self.ed_url.returnPressed.connect(self._add_custom)
        b_del.clicked.connect(self._del_custom)
        self.btn_run.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.cancel)
        self.btn_apply.clicked.connect(self._apply_selected)
        self.btn_best.clicked.connect(self._apply_best)
        self.btn_export.clicked.connect(self._export)
        self.table.itemSelectionChanged.connect(self._show_detail)
        self.ctx.strategies_changed.connect(self._fill_strategies)
        self.ctx.busy_changed.connect(lambda _: self._update_buttons())
        for w in (self.cb_quick, self.cb_user):
            w.toggled.connect(self._update_target_count)
        self.ctx.lists_changed.connect(self._update_target_count)
        self._fill_strategies()
        self._fill_custom()
        self._update_buttons()

    @staticmethod
    def _row(*widgets, stretch_end=True):
        h = QHBoxLayout()
        for w in widgets:
            h.addWidget(w)
        if stretch_end:
            h.addStretch(1)
        return h

    @staticmethod
    def _setup_table(t: QTableWidget) -> None:
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setShowGrid(False)

    def _fill_strategies(self) -> None:
        checked = {self.list.item(i).data(Qt.ItemDataRole.UserRole): self.list.item(i).checkState()
                   for i in range(self.list.count())}
        self.list.clear()
        names = [BASELINE_NAME] + [s.name for s in self.ctx.strategies]
        for n in names:
            it = QListWidgetItem(n)
            it.setData(Qt.ItemDataRole.UserRole, n)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            default = Qt.CheckState.Checked if (n != BASELINE_NAME or self.ctx.cfg["test"]["baseline"]) \
                else Qt.CheckState.Unchecked
            it.setCheckState(checked.get(n, default))
            if n == BASELINE_NAME:
                it.setForeground(QColor(C["muted"]))
            self.list.addItem(it)
        self._update_target_count()

    def _check_all(self, value: bool) -> None:
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Checked if value else Qt.CheckState.Unchecked)

    def _invert(self) -> None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setCheckState(Qt.CheckState.Unchecked if it.checkState() == Qt.CheckState.Checked
                             else Qt.CheckState.Checked)

    def _selected_strategies(self) -> list:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() != Qt.CheckState.Checked:
                continue
            n = it.data(Qt.ItemDataRole.UserRole)
            out.append(None if n == BASELINE_NAME else self.ctx.get_strategy(n))
        return out

    def _fill_custom(self) -> None:
        self.custom.clear()
        for c in self.ctx.cfg["custom_targets"]:
            self.custom.addItem(c["url"])
        self._update_target_count()

    def _add_custom(self) -> None:
        url = self.ed_url.text().strip()
        if not url:
            return
        if "://" not in url:
            url = "https://" + url
        try:
            host = lists.normalize_domain(url)
        except ValueError as e:
            QMessageBox.warning(self, "Свои цели", f"Не удалось разобрать адрес: {e}")
            return
        items = self.ctx.cfg["custom_targets"]
        if any(c["url"] == url for c in items):
            return
        items.append({"name": host, "url": url})
        self.ctx.cfg.save()
        self.ed_url.clear()
        self._fill_custom()

    def _del_custom(self) -> None:
        r = self.custom.currentRow()
        if r >= 0:
            del self.ctx.cfg["custom_targets"][r]
            self.ctx.cfg.save()
            self._fill_custom()

    def _build_targets(self):
        user = lists.user_lists(self.ctx.zdir)["include"].entries() if self.cb_user.isChecked() else []
        return load_targets(self.ctx.zdir, self.ctx.cfg["custom_targets"], user, self.cb_quick.isChecked())

    def _update_target_count(self, *_) -> None:
        if self.ctx.installed:
            self.lbl_targets.setText(f"Всего целей в тесте: {len(self._build_targets())}")

    def _update_buttons(self) -> None:
        running = self.worker is not None and self.worker.isRunning()
        self.btn_run.setEnabled(not self.ctx.busy and self.ctx.installed)
        self.btn_stop.setEnabled(running)
        has_res = bool(self.results)
        self.btn_apply.setEnabled(has_res and not self.ctx.busy and self._sel_name() is not None)
        self.btn_best.setEnabled(has_res and not self.ctx.busy)
        self.btn_export.setEnabled(has_res)

    def start(self) -> None:
        if not self.ctx.installed:
            return
        strategies = self._selected_strategies()
        if not strategies:
            QMessageBox.information(self, "Тест", "Отметьте хотя бы одну стратегию.")
            return
        if not find_curl():
            QMessageBox.critical(self, "Тест", "Не найден curl.exe. Он входит в Windows 10 (1803+) и Windows 11.")
            return
        if any(s is not None for s in strategies) and not is_admin():
            self.win.ask_admin()
            return
        if service_state() == "RUNNING":
            if QMessageBox.question(self, "Служба zapret",
                                    "Запущена служба zapret - она помешает тесту.\nОстановить её на время теста?"
                                    ) != QMessageBox.StandardButton.Yes:
                return
            stop_service()
        targets = self._build_targets()
        if not targets:
            QMessageBox.warning(self, "Тест", "Нет целей для проверки (проверьте utils/targets.txt).")
            return
        cfg_t = self.ctx.cfg["test"]
        cfg_t.update(timeout=self.sp_timeout.value(), parallel=self.sp_parallel.value(),
                     quick=self.cb_quick.isChecked(), user_sites=self.cb_user.isChecked())
        self.ctx.cfg.save()

        running = self.ctx.running_strategy()
        self._restore = running.name if running else None
        session = TestSession(self.ctx.runner, self.ctx.zdir, self.ctx.game_filter(), targets,
                              timeout=self.sp_timeout.value(), parallel=self.sp_parallel.value())
        self.worker = TestWorker(session, strategies)
        self.worker.strategy_started.connect(self._on_started)
        self.worker.progress.connect(self._on_progress)
        self.worker.strategy_done.connect(self._on_done)
        self.worker.failed.connect(lambda m: QMessageBox.critical(self, "Тест", m))
        self.worker.finished.connect(self._on_finished)
        self.results.clear()
        self.table.setRowCount(0)
        self.detail.setRowCount(0)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self._total = len(strategies)
        self.ctx.set_busy(True)
        log.info(f"Тест: {len(strategies)} стратегий × {len(targets)} целей")
        self.worker.start()
        self._update_buttons()

    def cancel(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.lbl_status.setText("Останавливаю тест (дожидаюсь текущих проверок)…")
            self.btn_stop.setEnabled(False)

    def _on_started(self, i: int, total: int, name: str) -> None:
        self._cur = (i, total, name)
        self.lbl_status.setText(f"Стратегия {i + 1} из {total}: {name}")
        self.bar.setValue(int(100 * i / total))

    def _on_progress(self, done: int, total: int) -> None:
        i, n, name = self._cur
        self.bar.setValue(int(100 * (i + done / max(total, 1)) / n))
        self.lbl_status.setText(f"Стратегия {i + 1} из {n}: {name} - проверок {done}/{total}")

    def _on_done(self, sr: StrategyResult) -> None:
        self.results[sr.name] = sr
        self.ctx.record(sr)
        self._add_row(sr)
        self._update_buttons()

    def _on_finished(self) -> None:
        cancelled = self.worker.session.cancel.is_set()
        self.bar.setValue(100 if not cancelled else self.bar.value())
        done = [r for r in self.results.values() if not r.error and r.name != BASELINE_NAME]
        best = max(done, key=lambda r: (r.score, -(r.ping_avg or 9999)), default=None)
        msg = "Тест остановлен. " if cancelled else "Тест завершён. "
        if best and best.score > 0:
            msg += f"Лучшая: {best.name} - {best.score:.0f}%" + (f", пинг {best.ping_avg:.0f} мс" if best.ping_avg else "")
        elif done:
            msg += "Ни одна стратегия не открыла ни одной цели - проверьте права администратора, антивирус и интернет."
        self.lbl_status.setText(msg)
        self.ctx.set_busy(False)
        self.table.sortItems(1, Qt.SortOrder.DescendingOrder)
        if self.table.rowCount():
            self.table.selectRow(0)
        self._update_buttons()
        if self._restore:
            s = self.ctx.get_strategy(self._restore)
            self._restore = None
            if s:
                self.win.start_strategy(s, quiet=True)
        else:
            self.ctx.state_changed.emit()

    def _add_row(self, sr: StrategyResult) -> None:
        self.table.setSortingEnabled(False)
        r = self.table.rowCount()
        self.table.insertRow(r)
        name = QTableWidgetItem(sr.name)
        if sr.name == BASELINE_NAME:
            name.setForeground(QColor(C["muted"]))
        self.table.setItem(r, 0, name)
        if sr.error:
            it = NumItem("не запустилась")
            it.setData(Qt.ItemDataRole.UserRole, -1)
            it.setForeground(QColor(C["bad"]))
            it.setToolTip(sr.error)
            self.table.setItem(r, 1, it)
            for c in range(2, 6):
                self.table.setItem(r, c, NumItem("-"))
        else:
            sc = NumItem(f"{sr.score:.0f}%")
            sc.setData(Qt.ItemDataRole.UserRole, sr.score)
            sc.setForeground(QColor(score_color(sr.score)))
            self.table.setItem(r, 1, sc)
            for c, label_ in enumerate(LABELS, start=2):
                ok, tot = sr.count(label_)
                it = NumItem(f"{ok}/{tot}" if tot else "-")
                it.setData(Qt.ItemDataRole.UserRole, ok)
                self.table.setItem(r, c, it)
            p = sr.ping_avg
            pi = NumItem(f"{p:.0f} мс" if p is not None else "-")
            pi.setData(Qt.ItemDataRole.UserRole, p if p is not None else 99999)
            self.table.setItem(r, 5, pi)
        self.table.setSortingEnabled(True)

    def _sel_name(self) -> str | None:
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        return it.text() if it else None

    def _show_detail(self) -> None:
        sr = self.results.get(self._sel_name() or "")
        self.detail.setRowCount(0)
        self._update_buttons()
        if not sr:
            return
        if sr.error:
            self.detail.setRowCount(1)
            it = QTableWidgetItem(sr.error.replace("\n", " "))
            it.setForeground(QColor(C["bad"]))
            self.detail.setItem(0, 0, it)
            return
        self.detail.setRowCount(len(sr.results))
        for r, tr in enumerate(sr.results):
            grp = f"[{tr.target.group}] " if tr.target.user else ""
            self.detail.setItem(r, 0, QTableWidgetItem(grp + tr.target.name))
            for c, lab in enumerate(LABELS, start=1):
                tok = tr.tokens.get(lab)
                text, color = TOKEN_TEXT.get(tok, ("-", C["muted"]))
                it = QTableWidgetItem(text)
                it.setForeground(QColor(color))
                self.detail.setItem(r, c, it)
            ping = QTableWidgetItem(f"{tr.ping_ms:.0f} мс" if tr.ping_ms is not None else "таймаут")
            ping.setForeground(QColor(C["text"] if tr.ping_ms is not None else C["muted"]))
            self.detail.setItem(r, 4, ping)

    def _apply_selected(self) -> None:
        s = self.ctx.get_strategy(self._sel_name() or "")
        if s:
            self.win.start_strategy(s)
        else:
            QMessageBox.information(self, "Применить", "Выберите строку со стратегией (не базовую линию).")

    def _apply_best(self) -> None:
        cands = [r for r in self.results.values() if not r.error and r.name != BASELINE_NAME]
        if not cands:
            return
        best = max(cands, key=lambda r: (r.score, -(r.ping_avg or 9999)))
        if best.score <= 0:
            QMessageBox.information(self, "Применить лучшую", "Ни одна стратегия не дала доступа ни к одной цели.")
            return
        s = self.ctx.get_strategy(best.name)
        if s:
            self.win.start_strategy(s)

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт результатов",
                                              f"zapret_test_{time.strftime('%Y%m%d_%H%M')}.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Стратегия", "Оценка %", "OK", "Всего", "HTTP", "TLS1.2", "TLS1.3", "Пинг мс", "Ошибка"])
            for sr in sorted(self.results.values(), key=lambda r: -r.score):
                w.writerow([sr.name, f"{sr.score:.1f}", sr.ok, sr.total,
                            *[f"{a}/{b}" for a, b in (sr.count(l) for l in LABELS)],
                            f"{sr.ping_avg:.0f}" if sr.ping_avg is not None else "", sr.error.replace("\n", " ")])
            w.writerow([])
            w.writerow(["Детали"])
            w.writerow(["Стратегия", "Цель", "HTTP", "TLS1.2", "TLS1.3", "Пинг мс"])
            for sr in self.results.values():
                for tr in sr.results:
                    w.writerow([sr.name, tr.target.name, *[tr.tokens.get(l, "") for l in LABELS],
                                f"{tr.ping_ms:.0f}" if tr.ping_ms is not None else ""])
        self.win.statusBar().showMessage(f"Сохранено: {path}", 5000)
