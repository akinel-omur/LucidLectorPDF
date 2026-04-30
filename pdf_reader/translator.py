"""Translation helper using deep-translator (Google backend). Async via QThreadPool."""
from __future__ import annotations

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

try:
    from deep_translator import GoogleTranslator
except ImportError:  # pragma: no cover
    GoogleTranslator = None  # type: ignore[assignment]


_MAX_CHUNK = 4500  # Google's per-request cap is 5000; leave headroom

# Supported target languages: display label → ISO code
LANGUAGES: dict[str, str] = {
    "TR": "tr",
    "EN": "en",
    "ES": "es",
    "DE": "de",
    "FR": "fr",
    "RU": "ru",
}


def _chunks(text: str, size: int = _MAX_CHUNK) -> list[str]:
    if len(text) <= size:
        return [text]
    parts, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            sp = text.rfind(" ", start, end)
            if sp > start:
                end = sp
        parts.append(text[start:end])
        start = end
    return parts


class _Signals(QObject):
    done = pyqtSignal(str, str, str)    # original, translated, target_code
    failed = pyqtSignal(str, str)       # original, error message


class _Worker(QRunnable):
    def __init__(self, text: str, target: str, signals: _Signals) -> None:
        super().__init__()
        self.text = text
        self.target = target
        self.signals = signals

    def run(self) -> None:
        try:
            if GoogleTranslator is None:
                raise RuntimeError("deep-translator kurulu değil.")
            tr = GoogleTranslator(source="auto", target=self.target)
            parts = [tr.translate(p) or "" for p in _chunks(self.text)]
            self.signals.done.emit(self.text, " ".join(parts).strip(), self.target)
        except Exception as e:  # noqa: BLE001
            self.signals.failed.emit(self.text, str(e))


class Translator(QObject):
    translated = pyqtSignal(str, str)   # original, translated
    failed = pyqtSignal(str, str)       # original, error message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # Cache keyed by (text, target_code) so different languages don't collide.
        self._cache: dict[tuple[str, str], str] = {}
        self._target: str = "tr"
        self._pool = QThreadPool.globalInstance()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def set_target_language(self, code: str) -> None:
        """Set the translation target language (ISO 639-1 code, e.g. 'en')."""
        if code in LANGUAGES.values():
            self._target = code

    @property
    def target_language(self) -> str:
        return self._target

    def translate(self, text: str) -> None:
        """Translate *text* to the currently selected target language (async)."""
        text = text.strip()
        if not text:
            return
        target = self._target          # capture before thread starts
        key = (text, target)
        if key in self._cache:
            self.translated.emit(text, self._cache[key])
            return
        sig = _Signals()
        sig.done.connect(self._on_done)
        sig.failed.connect(self._on_failed)
        worker = _Worker(text, target, sig)
        # Keep sig alive until the worker thread emits and the slot runs.
        worker._sig_keepalive = sig    # type: ignore[attr-defined]
        self._pool.start(worker)

    # ------------------------------------------------------------------ #
    # Slots
    # ------------------------------------------------------------------ #
    def _on_done(self, original: str, translated: str, target: str) -> None:
        self._cache[(original, target)] = translated
        self.translated.emit(original, translated)

    def _on_failed(self, original: str, err: str) -> None:
        self.failed.emit(original, err)
