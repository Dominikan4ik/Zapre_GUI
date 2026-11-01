from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .style import C, button, card, label, score_color


class NumItem(QTableWidgetItem):
    def __lt__(self, other) -> bool:
        a, b = self.data(Qt.ItemDataRole.UserRole), other.data(Qt.ItemDataRole.UserRole)
        try:
            return float(a) < float(b)
        except (TypeError, ValueError):
            return super().__lt__(other)


class HomeTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win, self.ctx = win, win.ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        self.missing, mlay = card("Папка zapret не найдена",
                                  "Программа может сама скачать последнюю версию zapret-discord-youtube "
                                  "из релизов Flowseal или использовать уже имеющуюся папку.")
        self.btn_download = button("Скачать последнюю версию", "primary")
        self.btn_pick = button("Указать папку zapret…")
        mlay.addLayout(self._row(self.btn_download, self.btn_pick))
        root.addWidget(self.missing)

        self.panel, play = card()
        top = QHBoxLayout()
        self.lbl_state = label("", "h1")
        self.lbl_sub = label("", "muted", wrap=True)
        top.addWidget(self.lbl_state, 1)
        self.btn_start = button("▶  Запустить выбранную", "primary")
        self.btn_stop = button("■  Остановить", "danger")
        self.btn_restart = button("↻  Перезапустить")
        self.btn_best = button("★  Лучшая по тесту")
        for b in (self.btn_best, self.btn_restart, self.btn_stop, self.btn_start):
            top.addWidget(b)
        play.addLayout(top)
        play.addWidget(self.lbl_sub)
        root.addWidget(self.panel)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "Стратегия", "Оценка теста", "Пинг", "Проверено"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.table.setSortingEnabled(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 34)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for c, w in ((2, 140), (3, 90), (4, 130)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(c, w)
        root.addWidget(self.table, 1)
        self.hint = label("Двойной щелчок по стратегии - запустить. «Оценка теста» берётся из вкладки «Тест стратегий»: "
                          "чем выше процент и ниже пинг, тем лучше.", "muted", wrap=True)
        root.addWidget(self.hint)

        self.btn_start.clicked.connect(self._start_selected)
        self.btn_stop.clicked.connect(self.win.stop_strategy)
        self.btn_restart.clicked.connect(self.win.restart_strategy)
        self.btn_best.clicked.connect(self._start_best)
        self.btn_download.clicked.connect(self.win.download_zapret)
        self.btn_pick.clicked.connect(self.win.pick_zapret_dir)
        self.table.cellDoubleClicked.connect(lambda *_: self._start_selected())
        self.table.itemSelectionChanged.connect(self._update_buttons)
        for sig in (self.ctx.strategies_changed, self.ctx.history_changed, self.ctx.state_changed):
            sig.connect(self.refresh)
        self.ctx.busy_changed.connect(lambda _: self._update_buttons())
        self.refresh()

    @staticmethod
    def _row(*widgets):
        h = QHBoxLayout()
        for w in widgets:
            h.addWidget(w)
        h.addStretch(1)
        return h

    def selected_name(self) -> str | None:
        r = self.table.currentRow()
        it = self.table.item(r, 1) if r >= 0 else None
        return it.text() if it else None

    def _start_selected(self) -> None:
        n = self.selected_name()
        s = self.ctx.get_strategy(n) if n else None
        if s:
            self.win.start_strategy(s)

    def _start_best(self) -> None:
        n = self.ctx.best_from_history()
        s = self.ctx.get_strategy(n) if n else None
        if s:
            self.win.start_strategy(s)

    def refresh(self) -> None:
        installed = self.ctx.installed
        self.missing.setVisible(not installed)
        self.panel.setVisible(installed)
        self.table.setVisible(installed)
        self.hint.setVisible(installed)
        state, name = self.ctx.state()
        if state == "running":
            self.lbl_state.setText("●  Обход работает")
            self.lbl_state.setStyleSheet(f"color: {C['ok']};")
            self.lbl_sub.setText(f"Стратегия: {name}")
        elif state == "external":
            self.lbl_state.setText("●  winws запущен вне программы")
            self.lbl_state.setStyleSheet(f"color: {C['warn']};")
            self.lbl_sub.setText("Запущен bat-файлом или службой zapret. Нажмите «Остановить» или выберите стратегию - "
                                 "программа возьмёт управление на себя.")
        else:
            self.lbl_state.setText("●  Обход остановлен")
            self.lbl_state.setStyleSheet(f"color: {C['muted']};")
            self.lbl_sub.setText("Выберите стратегию из списка и нажмите «Запустить».")

        keep = self.selected_name() or self.ctx.cfg["last_strategy"]
        hist = self.ctx.history()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.ctx.strategies))
        for r, s in enumerate(self.ctx.strategies):
            active = state == "running" and s.name == name
            mark = QTableWidgetItem("▶" if active else "")
            mark.setForeground(QColor(C["ok"]))
            mark.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            mark.setData(Qt.ItemDataRole.UserRole, 0 if active else 1)
            title = QTableWidgetItem(s.name)
            if active:
                title.setForeground(QColor(C["ok"]))
            h = hist.get(s.name)
            if h and not h.get("error"):
                score = NumItem(f"{h['score']:.0f}%  ({h['ok']}/{h['total']})")
                score.setData(Qt.ItemDataRole.UserRole, h["score"])
                score.setForeground(QColor(score_color(h["score"])))
                ping = NumItem(f"{h['ping']:.0f} мс" if h.get("ping") is not None else "-")
                ping.setData(Qt.ItemDataRole.UserRole, h["ping"] if h.get("ping") is not None else 99999)
                when = QTableWidgetItem(h.get("time", ""))
            elif h:
                score = NumItem("не запустилась")
                score.setData(Qt.ItemDataRole.UserRole, -1)
                score.setForeground(QColor(C["bad"]))
                score.setToolTip(h.get("error", ""))
                ping = NumItem("-")
                ping.setData(Qt.ItemDataRole.UserRole, 99999)
                when = QTableWidgetItem(h.get("time", ""))
            else:
                score = NumItem("-")
                score.setData(Qt.ItemDataRole.UserRole, -2)
                score.setForeground(QColor(C["muted"]))
                ping = NumItem("-")
                ping.setData(Qt.ItemDataRole.UserRole, 99999)
                when = QTableWidgetItem("-")
                when.setForeground(QColor(C["muted"]))
            for c, it in enumerate((mark, title, score, ping, when)):
                self.table.setItem(r, c, it)
        self.table.setSortingEnabled(True)
        if keep:
            for r in range(self.table.rowCount()):
                if self.table.item(r, 1).text() == keep:
                    self.table.selectRow(r)
                    break
        elif self.table.rowCount():
            self.table.selectRow(0)
        self._update_buttons()

    def _update_buttons(self) -> None:
        busy = self.ctx.busy
        state, _ = self.ctx.state()
        has_sel = self.selected_name() is not None
        self.btn_start.setEnabled(has_sel and not busy)
        self.btn_stop.setEnabled(state != "stopped" and not busy)
        self.btn_restart.setEnabled(state == "running" and not busy)
        self.btn_best.setEnabled(self.ctx.best_from_history() is not None and not busy)
        best = self.ctx.best_from_history()
        self.btn_best.setToolTip(f"Запустить «{best}» - лучшую по результатам теста" if best
                                 else "Сначала запустите тест стратегий")
