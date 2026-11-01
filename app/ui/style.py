from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

C = dict(bg="#14161a", panel="#1b1e24", panel2="#232730", border="#2d323c", text="#e7e9ed",
         muted="#8b93a0", accent="#4f8cff", ok="#3ecf8e", warn="#f5b94a", bad="#ef5b5b")

QSS = f"""
* {{ font-family: "Segoe UI", "Noto Sans", sans-serif; font-size: 13px; }}
QWidget {{ background: {C['bg']}; color: {C['text']}; }}
QToolTip {{ background: {C['panel2']}; color: {C['text']}; border: 1px solid {C['border']}; padding: 4px; }}
QLabel {{ background: transparent; }}
QLabel[role="muted"] {{ color: {C['muted']}; }}
QLabel[role="h1"] {{ font-size: 18px; font-weight: 600; }}
QLabel[role="h2"] {{ font-size: 14px; font-weight: 600; }}
QFrame[card="true"] {{ background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 10px; }}
QFrame[card="true"] QLabel, QFrame[card="true"] QCheckBox {{ background: transparent; }}
QFrame[banner="true"] {{ background: #1d2a44; border: 1px solid {C['accent']}; border-radius: 8px; }}
QFrame[banner="warn"] {{ background: #3a2f17; border: 1px solid {C['warn']}; border-radius: 8px; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {C['muted']}; padding: 9px 18px; border: none;
               border-bottom: 2px solid transparent; font-size: 13px; }}
QTabBar::tab:selected {{ color: {C['text']}; border-bottom: 2px solid {C['accent']}; }}
QTabBar::tab:hover {{ color: {C['text']}; }}
QPushButton {{ background: {C['panel2']}; border: 1px solid {C['border']}; border-radius: 7px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {C['accent']}; }}
QPushButton:pressed {{ background: {C['panel']}; }}
QPushButton:disabled {{ color: {C['muted']}; background: {C['panel']}; border-color: {C['panel2']}; }}
QPushButton[kind="primary"] {{ background: {C['accent']}; border-color: {C['accent']}; color: white; font-weight: 600; }}
QPushButton[kind="primary"]:hover {{ background: #6a9dff; }}
QPushButton[kind="primary"]:disabled {{ background: #2a3a5c; color: #7f8aa3; border-color: #2a3a5c; }}
QPushButton[kind="danger"] {{ color: {C['bad']}; }}
QPushButton[kind="danger"]:hover {{ border-color: {C['bad']}; }}
QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{ background: {C['panel']}; border: 1px solid {C['border']};
    border-radius: 7px; padding: 6px 8px; selection-background-color: {C['accent']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {C['accent']}; }}
QComboBox QAbstractItemView {{ background: {C['panel2']}; border: 1px solid {C['border']}; selection-background-color: {C['accent']}; }}
QTableWidget, QListWidget {{ background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 8px;
    gridline-color: transparent; alternate-background-color: #1e222a; selection-background-color: #2b3f66; outline: 0; }}
QTableWidget::item {{ padding: 4px 6px; border: none; }}
QListWidget::item {{ padding: 5px 6px; }}
QHeaderView::section {{ background: {C['panel2']}; color: {C['muted']}; border: none; padding: 7px 8px; font-weight: 600; }}
QProgressBar {{ background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 7px; text-align: center; height: 16px; }}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 6px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {C['border']}; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {C['muted']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {C['border']}; border-radius: 5px; min-width: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QSplitter::handle {{ background: transparent; }}
QMenu {{ background: {C['panel2']}; border: 1px solid {C['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {C['accent']}; }}
"""


def build_qss() -> str:
    d = Path(tempfile.gettempdir()) / "zapret_manager_assets"
    d.mkdir(exist_ok=True)
    check = d / "check.png"
    pm = QPixmap(16, 16)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("white"))
    pen.setWidthF(2.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(3.6, 8.4), QPointF(6.6, 11.4))
    p.drawLine(QPointF(6.6, 11.4), QPointF(12.4, 4.8))
    p.end()
    pm.save(str(check))
    url = check.as_posix()
    box = f"border: 1px solid #5a6270; border-radius: 4px; background: {C['panel']};"
    on = f"background: {C['accent']}; border-color: {C['accent']}; image: url({url});"
    return QSS + f"""
QCheckBox {{ spacing: 9px; background: transparent; }}
QCheckBox::indicator {{ width: 16px; height: 16px; {box} }}
QCheckBox::indicator:hover {{ border-color: {C['accent']}; }}
QCheckBox::indicator:checked {{ {on} }}
QListWidget::indicator {{ width: 15px; height: 15px; {box} }}
QListWidget::indicator:checked {{ {on} }}
"""


def make_icon(state: str = "stopped") -> QIcon:
    color = {"running": C["ok"], "external": C["warn"]}.get(state, C["accent"])
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, 64, 64)
    g.setColorAt(0, QColor(color).lighter(125))
    g.setColorAt(1, QColor(color).darker(140))
    p.setBrush(g)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 15, 15)
    p.setPen(QPen(QColor("white")))
    f = QFont("Segoe UI", 30)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "Z")
    p.end()
    return QIcon(pm)


def card(title: str | None = None, subtitle: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setProperty("card", True)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(8)
    if title:
        lay.addWidget(label(title, "h2"))
    if subtitle:
        lay.addWidget(label(subtitle, "muted", wrap=True))
    return f, lay


def label(text: str, role: str | None = None, wrap: bool = False) -> QLabel:
    l = QLabel(text)
    if role:
        l.setProperty("role", role)
    l.setWordWrap(wrap)
    return l


def button(text: str, kind: str | None = None) -> "QPushButton":
    from PySide6.QtWidgets import QPushButton
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def row(*widgets, stretch_end: bool = True, spacing: int = 8) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setSpacing(spacing)
    for w in widgets:
        h.addWidget(w)
    if stretch_end:
        h.addStretch(1)
    return h


def score_color(score: float) -> str:
    return C["ok"] if score >= 90 else C["warn"] if score >= 60 else C["bad"]
