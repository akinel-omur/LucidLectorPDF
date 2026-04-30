"""Ctrl+F search bar."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)


class SearchBar(QWidget):
    search_requested = pyqtSignal(str)
    next_requested = pyqtSignal()
    prev_requested = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Ara…")
        self._input.returnPressed.connect(self._on_return)
        layout.addWidget(self._input, 1)

        self._count = QLabel("")
        layout.addWidget(self._count)

        prev_btn = QPushButton("◀")
        prev_btn.setFixedWidth(30)
        prev_btn.clicked.connect(self.prev_requested.emit)
        layout.addWidget(prev_btn)

        next_btn = QPushButton("▶")
        next_btn.setFixedWidth(30)
        next_btn.clicked.connect(self.next_requested.emit)
        layout.addWidget(next_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedWidth(30)
        close_btn.clicked.connect(self._close)
        layout.addWidget(close_btn)

        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc.activated.connect(self._close)

        self.hide()

    def focus_input(self) -> None:
        self._input.setFocus()
        self._input.selectAll()

    def set_match_count(self, count: int) -> None:
        self._count.setText(f"{count} sonuç" if count else "bulunamadı")

    def _on_return(self) -> None:
        text = self._input.text().strip()
        if text:
            self.search_requested.emit(text)

    def _close(self) -> None:
        self.hide()
        self.closed.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._close()
            return
        if event.key() in (Qt.Key.Key_F3,):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.prev_requested.emit()
            else:
                self.next_requested.emit()
            return
        super().keyPressEvent(event)
