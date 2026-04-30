"""Translation panel — shown in a right-side dock widget."""
from __future__ import annotations

import re

from PyQt6.QtCore import QEvent, QObject, QSettings, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .i18n import s as _s

_FONT_KEY = "translationFontSize"
_DEFAULT_SIZE = 11
_MIN_SIZE = 8
_MAX_SIZE = 36


# ---------- sentence helpers ----------

def _sentence_boundaries(text: str) -> list[tuple[int, int]]:
    """Return [(start, end), …] char offsets for each sentence in *text*."""
    result: list[tuple[int, int]] = []
    start = 0
    for m in re.finditer(r'(?<=[.!?…])\s+', text):
        result.append((start, m.start() + 1))   # include trailing punctuation
        start = m.end()
    if start < len(text):
        result.append((start, len(text)))
    return result


def _sentence_at(text: str, pos: int) -> str:
    """Return the sentence in *text* that contains character offset *pos*."""
    for start, end in _sentence_boundaries(text):
        if start <= pos < end:
            return text[start:end].strip()
    return text.strip()   # fallback: whole text is one sentence


def _nth_sentence(text: str, n: int) -> str:
    """Return the *n*-th sentence (0-based) of *text*."""
    bounds = _sentence_boundaries(text)
    if not bounds:
        return text.strip()
    s, e = bounds[min(n, len(bounds) - 1)]
    return text[s:e].strip()



# ---------- eye overlay ----------

class _EyeOverlay(QWidget):
    """Transparent child widget that tints the panel with the eye-filter color."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._color = QColor(0, 0, 0, 0)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setGeometry(parent.rect())
        self.raise_()

    def set_color(self, color: QColor | None) -> None:
        self._color = color if color is not None else QColor(0, 0, 0, 0)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._color.alpha() > 0:
            p = QPainter(self)
            p.fillRect(self.rect(), self._color)


# ---------- main panel ----------

class TranslationPanel(QWidget):
    # Emitted when the mouse hovers over a new sentence (orig text of that sentence).
    sentence_hovered = pyqtSignal(str)
    # Emitted when the mouse leaves the text areas.
    sentence_left = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("PdfReader", "App")
        self._locale = "tr"
        self._target_code: str = "tr"
        self._last_hover_sentence: str = ""

        # Debounce Leave events — Qt fires Leave when crossing widget
        # sub-boundaries or during repaints; wait 180 ms before actually
        # clearing the hover so brief exits don't flicker the highlight.
        self._leave_timer = QTimer(self)
        self._leave_timer.setSingleShot(True)
        self._leave_timer.setInterval(180)
        self._leave_timer.timeout.connect(self._emit_leave)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._orig_label = QLabel("<b>Orijinal:</b>")
        layout.addWidget(self._orig_label)

        self._orig = QPlainTextEdit()
        self._orig.setReadOnly(True)
        self._orig.setMaximumHeight(120)
        self._orig.setMouseTracking(True)
        layout.addWidget(self._orig)

        self._tr_label = QLabel("<b>Türkçe:</b>")
        layout.addWidget(self._tr_label)

        self._tr = QPlainTextEdit()
        self._tr.setReadOnly(True)
        self._tr.setMouseTracking(True)
        layout.addWidget(self._tr, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)

        self._dec_btn = QPushButton("A−")
        self._dec_btn.setFixedWidth(40)
        self._dec_btn.clicked.connect(lambda: self._bump_font(-1))
        btns.addWidget(self._dec_btn)

        self._inc_btn = QPushButton("A+")
        self._inc_btn.setFixedWidth(40)
        self._inc_btn.clicked.connect(lambda: self._bump_font(1))
        btns.addWidget(self._inc_btn)

        self._copy_btn = QPushButton("Kopyala")
        self._copy_btn.clicked.connect(self._copy)
        btns.addWidget(self._copy_btn)
        layout.addLayout(btns)

        size = int(self._settings.value(_FONT_KEY, _DEFAULT_SIZE, type=int))
        self._apply_font_size(size)
        self._apply_locale_labels()

        # Install event filter on the viewports — QPlainTextEdit is a
        # QAbstractScrollArea, so mouse events arrive on viewport(), not the
        # container widget itself.
        self._orig.viewport().installEventFilter(self)
        self._tr.viewport().installEventFilter(self)

        # Eye-protection overlay — created last so it sits on top.
        self._eye_overlay = _EyeOverlay(self)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def set_content(self, original: str, translated: str) -> None:
        self._orig.setPlainText(original)
        self._tr.setPlainText(translated)
        # Clear any lingering hover state when new content arrives.
        self._last_hover_sentence = ""

    def set_target_language(self, code: str) -> None:
        self._target_code = code
        name = _s(self._locale, f"lang_{code}")
        self._tr_label.setText(f"<b>{name}:</b>")

    def set_locale(self, code: str) -> None:
        self._locale = code
        self._apply_locale_labels()
        self.set_target_language(self._target_code)

    def set_eye_filter(self, color: QColor | None) -> None:
        self._eye_overlay.set_color(color)

    # ------------------------------------------------------------------ #
    # Event filter — sentence hover detection
    # ------------------------------------------------------------------ #
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        # obj is a viewport(), map it back to the parent QPlainTextEdit.
        if obj is self._orig.viewport():
            widget = self._orig
        elif obj is self._tr.viewport():
            widget = self._tr
        else:
            return super().eventFilter(obj, event)

        t = event.type()
        if t == QEvent.Type.MouseMove:
            self._leave_timer.stop()          # cancel any pending leave
            self._on_hover(widget, event.pos())  # type: ignore[arg-type]
        elif t == QEvent.Type.Leave:
            self._leave_timer.start()         # debounced — fires _emit_leave after 180 ms
        return super().eventFilter(obj, event)

    def _on_hover(self, widget: QPlainTextEdit, pos) -> None:
        orig_text = self._orig.toPlainText()
        if not orig_text:
            return

        cursor = widget.cursorForPosition(pos)
        char_pos = cursor.position()

        if widget is self._orig:
            sentence = _sentence_at(orig_text, char_pos)
        else:
            # Translated area: map cursor position proportionally to the
            # original text — more robust than index mapping when translation
            # has a different sentence count from the original.
            tr_text = self._tr.toPlainText()
            if not tr_text:
                return
            proportion = char_pos / max(len(tr_text) - 1, 1)
            orig_pos = min(int(proportion * len(orig_text)), len(orig_text) - 1)
            sentence = _sentence_at(orig_text, orig_pos)

        # Minimum length guard — ignore very short fragments (headings, numbers…)
        if len(sentence) < 10:
            return

        if sentence != self._last_hover_sentence:
            self._last_hover_sentence = sentence
            self.sentence_hovered.emit(sentence)

    def _emit_leave(self) -> None:
        if self._last_hover_sentence:
            self._last_hover_sentence = ""
            self.sentence_left.emit()

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _apply_locale_labels(self) -> None:
        self._orig_label.setText(_s(self._locale, "panel_original"))
        self._copy_btn.setText(_s(self._locale, "panel_copy"))
        self._dec_btn.setToolTip(_s(self._locale, "tip_font_dec"))
        self._inc_btn.setToolTip(_s(self._locale, "tip_font_inc"))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._eye_overlay.setGeometry(self.rect())
        self._eye_overlay.raise_()

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._tr.toPlainText())

    def _bump_font(self, delta: int) -> None:
        current = self._tr.font().pointSize()
        if current <= 0:
            current = _DEFAULT_SIZE
        self._apply_font_size(current + delta)

    def _apply_font_size(self, size: int) -> None:
        size = max(_MIN_SIZE, min(_MAX_SIZE, size))
        for editor in (self._tr, self._orig):
            f = editor.font()
            f.setPointSize(size)
            editor.setFont(f)
        self._settings.setValue(_FONT_KEY, size)
