"""Main window: menu, toolbar, fullscreen, wiring of components."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import __version__
from .i18n import s as _s

import fitz
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QIcon,
    QKeySequence,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .bookmark_panel import BookmarkPanel
from .pdf_document import PdfDocument
from .pdf_view import PdfView
from .recent_files import RecentFiles
from .search_bar import SearchBar
from .translation_popup import TranslationPanel
from .translator import LANGUAGES, Translator


class MainWindow(QMainWindow):
    # ------------------------------------------------------------------ #
    # Per-panel state helpers (route to whichever panel is currently active)
    # ------------------------------------------------------------------ #
    @property
    def _current_path(self) -> "Path | None":
        return self._panel_paths.get(id(self._active_view))

    @_current_path.setter
    def _current_path(self, val: "Path | None") -> None:
        self._panel_paths[id(self._active_view)] = val

    @property
    def _document_dirty(self) -> bool:
        return self._panel_dirty.get(id(self._active_view), False)

    @_document_dirty.setter
    def _document_dirty(self, val: bool) -> None:
        self._panel_dirty[id(self._active_view)] = val

    @property
    def _undo_stack(self) -> list:
        return self._undo_stacks.setdefault(id(self._active_view), [])

    @property
    def _redo_stack(self) -> list:
        return self._redo_stacks.setdefault(id(self._active_view), [])

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LucidLectorPDF")
        self.resize(1100, 800)

        # Core state
        # Per-panel state (keyed by id(view)); initialised after _view is created
        self._panel_paths: dict[int, "Path | None"] = {}
        self._panel_dirty: dict[int, bool] = {}
        self._undo_stacks: dict[int, list] = {}
        self._redo_stacks: dict[int, list] = {}
        self._settings = QSettings("PdfReader", "App")
        self._highlight_color = self._load_color("highlightColor", "#FFEB3B")
        self._underline_color = self._load_color("underlineColor", "#E53935")
        self._locale: str = "tr"          # set properly in _apply_locale
        self._last_original: str = ""     # for re-translate on lang change
        self._current_eye_mode: str = "off"   # tracked so new panels inherit it

        # Components
        self._view = PdfView(self)
        self._search = SearchBar(self)
        self._translator = Translator(self)
        self._recent = RecentFiles()

        # Split-view support
        self._view2: PdfView | None = None
        self._active_view: PdfView = self._view   # whichever panel received the last click

        # Initialise per-panel state for the primary view
        self._panel_paths[id(self._view)] = None
        self._panel_dirty[id(self._view)] = False
        self._undo_stacks[id(self._view)] = []
        self._redo_stacks[id(self._view)] = []

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._search)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(4)
        self._splitter.setStyleSheet("QSplitter::handle { background: #555; }")
        self._splitter.addWidget(self._view)
        layout.addWidget(self._splitter, 1)
        self.setCentralWidget(container)

        # Right-docked translation panel
        self._translation_panel = TranslationPanel()
        self._translation_dock = QDockWidget("Çeviri", self)
        self._translation_dock.setWidget(self._translation_panel)
        self._translation_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self._translation_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._translation_dock)
        self._translation_dock.hide()
        self.resizeDocks([self._translation_dock], [420], Qt.Orientation.Horizontal)

        # Left-docked bookmark panel
        self._bookmark_panel = BookmarkPanel()
        self._bookmark_dock = QDockWidget("Yer İşaretleri", self)
        self._bookmark_dock.setWidget(self._bookmark_panel)
        self._bookmark_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._bookmark_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._bookmark_dock)
        self._bookmark_dock.hide()
        self.resizeDocks([self._bookmark_dock], [240], Qt.Orientation.Horizontal)

        self._build_menu()
        self._build_toolbar()
        self._build_status()
        self._wire()
        self._update_undo_actions()

        # Restore persisted language and apply locale to all UI
        saved_lang = self._settings.value("targetLanguage", "tr", type=str)
        if saved_lang not in LANGUAGES.values():
            saved_lang = "tr"
        self._apply_locale(saved_lang)

        # Restore persisted eye filter
        saved_eye = self._settings.value("eyeFilter", "off", type=str)
        if saved_eye not in self._eye_actions:
            saved_eye = "off"
        self._eye_actions[saved_eye].setChecked(True)
        self._set_eye_filter(saved_eye)

    # ================================================================== #
    # UI build helpers
    # ================================================================== #
    def _build_menu(self) -> None:
        mb = self.menuBar()

        # ---- File ----
        self._menu_file = mb.addMenu("&Dosya")
        self._act_open_menu = QAction("Aç…", self)
        self._act_open_menu.setShortcut(QKeySequence.StandardKey.Open)
        self._act_open_menu.triggered.connect(self._open_dialog)
        self._menu_file.addAction(self._act_open_menu)

        self._recent_menu = QMenu("Son Açılanlar", self)
        self._menu_file.addMenu(self._recent_menu)

        self._menu_file.addSeparator()
        self._act_save = QAction("Kaydet (vurgular)", self)
        self._act_save.setShortcut(QKeySequence.StandardKey.Save)
        self._act_save.triggered.connect(self._save)
        self._menu_file.addAction(self._act_save)

        self._menu_file.addSeparator()
        self._act_exit = QAction("Çıkış", self)
        self._act_exit.setShortcut(QKeySequence.StandardKey.Quit)
        self._act_exit.triggered.connect(self.close)
        self._menu_file.addAction(self._act_exit)

        # ---- Edit ----
        self._menu_edit = mb.addMenu("&Düzen")
        self._act_undo = QAction("↶ Geri Al", self)
        self._act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self._act_undo.setToolTip("Geri Al (Ctrl+Z)")
        self._act_undo.triggered.connect(self._undo)
        self._menu_edit.addAction(self._act_undo)

        self._act_redo = QAction("↷ İleri Al", self)
        self._act_redo.setShortcuts(
            [QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")]
        )
        self._act_redo.setToolTip("İleri Al (Ctrl+Y)")
        self._act_redo.triggered.connect(self._redo)
        self._menu_edit.addAction(self._act_redo)

        # ---- View ----
        self._menu_view = mb.addMenu("&Görünüm")

        self._act_zoom_in = QAction("Yakınlaştır", self)
        self._act_zoom_in.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")])
        self._act_zoom_in.triggered.connect(lambda: self._active_view.zoom_in())
        self._menu_view.addAction(self._act_zoom_in)

        self._act_zoom_out = QAction("Uzaklaştır", self)
        self._act_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        self._act_zoom_out.triggered.connect(lambda: self._active_view.zoom_out())
        self._menu_view.addAction(self._act_zoom_out)

        self._act_zoom_fit = QAction("Sığdır (sayfa)", self)
        self._act_zoom_fit.setShortcut(QKeySequence("Ctrl+0"))
        self._act_zoom_fit.triggered.connect(lambda: self._active_view.zoom_fit_page())
        self._menu_view.addAction(self._act_zoom_fit)

        self._menu_view.addSeparator()
        self._act_color = QAction("Vurgu Rengi…", self)
        self._act_color.triggered.connect(self._pick_highlight_color)
        self._menu_view.addAction(self._act_color)
        self._update_color_swatch(self._act_color, self._highlight_color)

        self._act_underline_color = QAction("Alt Çizgi Rengi…", self)
        self._act_underline_color.triggered.connect(self._pick_underline_color)
        self._menu_view.addAction(self._act_underline_color)
        self._update_color_swatch(self._act_underline_color, self._underline_color)

        self._menu_view.addSeparator()
        self._menu_eye = self._menu_view.addMenu("Göz Koruması")
        eye_group = QActionGroup(self)
        eye_group.setExclusive(True)
        self._eye_actions: dict[str, QAction] = {}
        # (filter_key, i18n_key, label_tr)
        self._eye_filter_keys: list[tuple[str, str]] = [
            ("off",        "eye_off"),
            ("hafif",      "eye_hafif"),
            ("warm",       "eye_warm"),
            ("sepia",      "eye_sepia"),
            ("yesil",      "eye_yesil"),
            ("pembe",      "eye_pembe"),
            ("gece",       "eye_gece"),
            ("koyu_gece",  "eye_koyu_gece"),
            ("karartma",   "eye_karartma"),
        ]
        for key, i18n_key in self._eye_filter_keys:
            act = QAction(_s("tr", i18n_key), self)
            act.setCheckable(True)
            act.triggered.connect(lambda _checked=False, k=key: self._set_eye_filter(k))
            eye_group.addAction(act)
            self._menu_eye.addAction(act)
            self._eye_actions[key] = act

        self._menu_view.addSeparator()
        self._act_paragraph = QAction("Paragraf Çeviri Modu", self)
        self._act_paragraph.setCheckable(True)
        self._act_paragraph.setShortcut(QKeySequence("Ctrl+P"))
        self._act_paragraph.setToolTip("Paragraf başlarına çeviri butonu ekler (Ctrl+P)")
        self._act_paragraph.toggled.connect(self._view.set_paragraph_mode)
        self._menu_view.addAction(self._act_paragraph)

        self._menu_view.addSeparator()
        self._act_bookmarks = QAction("Yer İşaretleri Paneli", self)
        self._act_bookmarks.setCheckable(True)
        self._act_bookmarks.setShortcut(QKeySequence("Ctrl+B"))
        self._act_bookmarks.setToolTip("Yer işaretleri panelini göster/gizle (Ctrl+B)")
        self._menu_view.addAction(self._act_bookmarks)

        self._menu_view.addSeparator()
        self._act_dual = QAction("İkili Görünüm", self)
        self._act_dual.setCheckable(True)
        self._act_dual.setShortcut(QKeySequence("Ctrl+2"))
        self._act_dual.toggled.connect(self._view.set_dual_view)
        self._menu_view.addAction(self._act_dual)

        self._act_split = QAction("Bölünmüş Görünüm", self)
        self._act_split.setCheckable(True)
        self._act_split.setShortcut(QKeySequence("Ctrl+\\"))
        self._act_split.toggled.connect(self._toggle_split)
        self._menu_view.addAction(self._act_split)

        self._menu_view.addSeparator()
        self._act_full = QAction("Tam Ekran", self)
        self._act_full.setShortcut(QKeySequence(Qt.Key.Key_F11))
        self._act_full.setCheckable(True)
        self._act_full.triggered.connect(self._toggle_fullscreen)
        self._menu_view.addAction(self._act_full)

        self._act_find_menu = QAction("Ara…", self)
        self._act_find_menu.setShortcut(QKeySequence.StandardKey.Find)
        self._act_find_menu.triggered.connect(self._open_search)
        self._menu_view.addAction(self._act_find_menu)

        # ---- Help ----
        self._menu_help = mb.addMenu("&Yardım")
        self._act_about = QAction("Hakkında", self)
        self._act_about.triggered.connect(self._about)
        self._menu_help.addAction(self._act_about)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Ana")
        tb.setMovable(False)
        self.addToolBar(tb)

        self._tb_act_open = QAction("Aç", self)
        self._tb_act_open.triggered.connect(self._open_dialog)
        tb.addAction(self._tb_act_open)

        tb.addSeparator()

        self._tb_act_prev = QAction("◀", self)
        self._tb_act_prev.setShortcut(QKeySequence(Qt.Key.Key_PageUp))
        self._tb_act_prev.triggered.connect(lambda: self._goto_rel(-1))
        tb.addAction(self._tb_act_prev)

        self._page_input = QSpinBox()
        self._page_input.setMinimum(1)
        self._page_input.setMaximum(1)
        self._page_input.setFixedWidth(95)
        self._page_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._page_input.editingFinished.connect(self._goto_from_input)
        tb.addWidget(self._page_input)

        self._page_total_label = QLabel(" / 0  ")
        tb.addWidget(self._page_total_label)

        self._tb_act_next = QAction("▶", self)
        self._tb_act_next.setShortcut(QKeySequence(Qt.Key.Key_PageDown))
        self._tb_act_next.triggered.connect(lambda: self._goto_rel(1))
        tb.addAction(self._tb_act_next)

        tb.addSeparator()

        self._tb_act_zin = QAction("＋", self)
        self._tb_act_zin.triggered.connect(lambda: self._active_view.zoom_in())
        tb.addAction(self._tb_act_zin)

        self._tb_act_zout = QAction("－", self)
        self._tb_act_zout.triggered.connect(lambda: self._active_view.zoom_out())
        tb.addAction(self._tb_act_zout)

        self._tb_act_fit = QAction("Fit", self)
        self._tb_act_fit.triggered.connect(lambda: self._active_view.zoom_fit_page())
        tb.addAction(self._tb_act_fit)

        tb.addSeparator()

        # Mutually-exclusive Tekli / İkili toggles
        view_group = QActionGroup(self)
        view_group.setExclusive(True)

        self._act_single_tb = QAction("Tekli", self)
        self._act_single_tb.setCheckable(True)
        self._act_single_tb.setChecked(True)
        view_group.addAction(self._act_single_tb)
        tb.addAction(self._act_single_tb)

        self._act_dual_tb = QAction("İkili", self)
        self._act_dual_tb.setCheckable(True)
        view_group.addAction(self._act_dual_tb)
        tb.addAction(self._act_dual_tb)

        self._act_single_tb.triggered.connect(lambda: self._set_view_mode(False))
        self._act_dual_tb.triggered.connect(lambda: self._set_view_mode(True))
        self._act_dual.toggled.connect(self._set_view_mode)

        # Split-view toggle
        self._act_split_tb = QAction("⊟ Böl", self)
        self._act_split_tb.setCheckable(True)
        self._act_split_tb.setToolTip("Görünümü ikiye böl (Ctrl+\\)")
        tb.addAction(self._act_split_tb)
        # Sync toolbar ↔ menu without double-firing _toggle_split
        self._act_split_tb.toggled.connect(self._act_split.setChecked)
        self._act_split.toggled.connect(self._act_split_tb.setChecked)

        tb.addSeparator()

        self._tb_act_rot_left = QAction("↺ 90°", self)
        self._tb_act_rot_left.setToolTip("90° sola döndür")
        self._tb_act_rot_left.triggered.connect(lambda: self._rotate_pages(-90))
        tb.addAction(self._tb_act_rot_left)

        self._tb_act_rot_right = QAction("↻ 90°", self)
        self._tb_act_rot_right.setToolTip("90° sağa döndür")
        self._tb_act_rot_right.triggered.connect(lambda: self._rotate_pages(90))
        tb.addAction(self._tb_act_rot_right)

        tb.addSeparator()

        self._act_paragraph_tb = QAction("¶ Paragraf Çev.", self)
        self._act_paragraph_tb.setCheckable(True)
        self._act_paragraph_tb.setToolTip("Paragraf çeviri modu (Ctrl+P)")
        self._act_paragraph_tb.toggled.connect(self._act_paragraph.setChecked)
        self._act_paragraph.toggled.connect(self._act_paragraph_tb.setChecked)
        tb.addAction(self._act_paragraph_tb)

        tb.addSeparator()

        self._tb_act_find = QAction("Ara", self)
        self._tb_act_find.triggered.connect(self._open_search)
        tb.addAction(self._tb_act_find)

        self._act_bookmarks_tb = QAction("🔖 İçindekiler", self)
        self._act_bookmarks_tb.setCheckable(True)
        self._act_bookmarks_tb.setToolTip("Yer işaretleri panelini göster/gizle (Ctrl+B)")
        tb.addAction(self._act_bookmarks_tb)

        tb.addSeparator()
        tb.addAction(self._act_undo)
        tb.addAction(self._act_redo)

        # Language selector — pushed to the far right with a stretching spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        self._lang_combo = QComboBox()
        self._lang_combo.setToolTip("Çeviri dili")
        self._lang_combo.setFixedWidth(62)
        for label, code in LANGUAGES.items():
            self._lang_combo.addItem(label, code)
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        tb.addWidget(self._lang_combo)

        self._toolbar = tb

    def _build_status(self) -> None:
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._status_page = QLabel("")
        self._status_zoom = QLabel("")
        sb.addPermanentWidget(self._status_page)
        sb.addPermanentWidget(self._status_zoom)

    def _wire(self) -> None:
        self._search.search_requested.connect(self._run_search)
        self._search.next_requested.connect(self._view.search_next)
        self._search.prev_requested.connect(self._view.search_prev)
        self._search.closed.connect(self._view.clear_search)

        self._view.translate_requested.connect(self._on_translate)
        self._view.highlight_requested.connect(self._on_highlight)
        self._view.underline_requested.connect(self._on_underline)
        self._view.delete_annotation_requested.connect(self._on_delete_annotation)

        self._translator.translated.connect(self._show_translation)
        self._translator.failed.connect(self._translation_failed)

        self._translation_panel.sentence_hovered.connect(self._view.show_hover_highlight)
        self._translation_panel.sentence_left.connect(self._view.clear_hover_highlight)

        self._view.pdf_sentence_hovered.connect(self._translation_panel.highlight_sentence)
        self._view.pdf_sentence_left.connect(self._translation_panel.clear_sentence_highlight)

        self._view.verticalScrollBar().valueChanged.connect(
            lambda: self._on_scroll(self._view)
        )
        self._view.page_changed.connect(
            lambda p: self._on_page_changed(p, self._view)
        )
        # Mark primary panel as active and show its indicator on startup.
        self._view.panel_activated.connect(lambda: self._set_active_panel(self._view))
        self._view.set_active_indicator(True)

        # Bookmark panel
        self._bookmark_panel.page_requested.connect(
            lambda p: self._active_view.goto_page(p)
        )
        # Sync menu ↔ toolbar ↔ dock visibility
        self._act_bookmarks.toggled.connect(self._bookmark_dock.setVisible)
        self._act_bookmarks_tb.toggled.connect(self._act_bookmarks.setChecked)
        self._act_bookmarks.toggled.connect(self._act_bookmarks_tb.setChecked)
        self._bookmark_dock.visibilityChanged.connect(self._act_bookmarks.setChecked)

    # ================================================================== #
    # Locale
    # ================================================================== #
    def _apply_locale(self, code: str) -> None:
        """Update every localised widget/action to *code*."""
        self._locale = code

        # Sync combo (block signal → no recursion)
        self._lang_combo.blockSignals(True)
        idx = self._lang_combo.findData(code)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        self._lang_combo.blockSignals(False)

        # Translator & panel language
        self._translator.set_target_language(code)
        self._translation_panel.set_target_language(code)
        self._translation_panel.set_locale(code)

        # PDF view context menus (both panels)
        self._view.set_locale(code)
        if self._view2 is not None:
            self._view2.set_locale(code)

        # Dock title
        self._translation_dock.setWindowTitle(_s(code, "dock_title"))

        # ---- Menus ----
        self._menu_file.setTitle(_s(code, "menu_file"))
        self._menu_edit.setTitle(_s(code, "menu_edit"))
        self._menu_view.setTitle(_s(code, "menu_view"))
        self._menu_help.setTitle(_s(code, "menu_help"))

        # File menu
        self._act_open_menu.setText(_s(code, "act_open"))
        self._recent_menu.setTitle(_s(code, "act_recent"))
        self._act_save.setText(_s(code, "act_save"))
        self._act_exit.setText(_s(code, "act_exit"))
        self._refresh_recent_menu()   # rebuilds with localised "(empty)" / "Clear list"

        # Edit menu
        self._act_undo.setText(_s(code, "act_undo"))
        self._act_undo.setToolTip(_s(code, "tip_undo"))
        self._act_redo.setText(_s(code, "act_redo"))
        self._act_redo.setToolTip(_s(code, "tip_redo"))

        # View menu
        self._act_zoom_in.setText(_s(code, "act_zoom_in"))
        self._act_zoom_out.setText(_s(code, "act_zoom_out"))
        self._act_zoom_fit.setText(_s(code, "act_zoom_fit"))
        self._act_color.setText(_s(code, "act_hl_color"))
        self._act_underline_color.setText(_s(code, "act_ul_color"))
        self._menu_eye.setTitle(_s(code, "menu_eye"))
        for key, i18n_key in self._eye_filter_keys:
            self._eye_actions[key].setText(_s(code, i18n_key))
        self._act_paragraph.setText(_s(code, "act_paragraph"))
        self._act_paragraph.setToolTip(_s(code, "tip_paragraph"))
        self._act_dual.setText(_s(code, "act_dual"))
        self._act_bookmarks.setText(_s(code, "act_bookmarks"))
        self._act_bookmarks.setToolTip(_s(code, "tip_bookmarks"))
        self._bookmark_dock.setWindowTitle(_s(code, "dock_bookmarks"))
        self._bookmark_panel.set_locale(code)
        self._act_split.setText(_s(code, "act_split"))
        self._act_split_tb.setText(_s(code, "tb_split"))
        self._act_split_tb.setToolTip(_s(code, "tip_split"))
        self._act_full.setText(_s(code, "act_fullscreen"))
        self._act_find_menu.setText(_s(code, "act_find"))

        # Help menu
        self._act_about.setText(_s(code, "act_about"))

        # ---- Toolbar ----
        self._tb_act_open.setText(_s(code, "tb_open"))
        self._tb_act_fit.setText(_s(code, "tb_fit"))
        self._act_single_tb.setText(_s(code, "tb_single"))
        self._act_dual_tb.setText(_s(code, "tb_dual"))
        self._tb_act_rot_left.setToolTip(_s(code, "tip_rot_left"))
        self._tb_act_rot_right.setToolTip(_s(code, "tip_rot_right"))
        self._act_paragraph_tb.setText(_s(code, "tb_paragraph"))
        self._act_paragraph_tb.setToolTip(_s(code, "tip_paragraph_tb"))
        self._tb_act_find.setText(_s(code, "tb_search"))
        self._lang_combo.setToolTip(_s(code, "tip_lang"))

        if code != self._settings.value("targetLanguage", "tr", type=str):
            self._settings.setValue("targetLanguage", code)

    def _on_language_changed(self, _index: int) -> None:
        code = self._lang_combo.currentData()
        if code == self._locale:
            return
        self._apply_locale(code)
        # Re-translate the currently displayed text in the new language
        if self._last_original:
            self._translator.translate(self._last_original)

    # ================================================================== #
    # Page navigation
    # ================================================================== #
    def _sync_page_input(self) -> None:
        """Update the page spinbox to match the active panel's current page (no signal)."""
        self._page_input.blockSignals(True)
        self._page_input.setValue(self._active_view.current_page() + 1)
        self._page_input.blockSignals(False)

    def _on_page_changed(self, page: int, from_view: "PdfView | None" = None) -> None:
        if from_view is not None and from_view is not self._active_view:
            return
        self._page_input.blockSignals(True)
        self._page_input.setValue(page + 1)
        self._page_input.blockSignals(False)
        self._update_status()
        self._bookmark_panel.highlight_current(page)

    def _on_scroll(self, from_view: "PdfView") -> None:
        """Called when either panel scrolls; update status only for the active one."""
        if from_view is self._active_view:
            self._update_status()

    def _goto_rel(self, delta: int) -> None:
        if self._active_view.doc is None:
            return
        if delta > 0:
            self._active_view.go_next()
        elif delta < 0:
            self._active_view.go_prev()
        self._sync_page_input()
        self._update_status()

    def _goto_from_input(self) -> None:
        if self._active_view.doc is None:
            return
        self._active_view.goto_page(self._page_input.value() - 1)
        self._sync_page_input()
        self._update_status()

    # ================================================================== #
    # File operations
    # ================================================================== #
    def _open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            _s(self._locale, "dlg_open_title"),
            str(Path.home()),
            _s(self._locale, "dlg_open_filter"),
        )
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> None:
        if not self._prompt_save():
            return
        try:
            doc = PdfDocument(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self,
                _s(self._locale, "dlg_open_err_title"),
                _s(self._locale, "dlg_open_err_msg").format(err=e),
            )
            return
        self._active_view.load(doc)
        self._current_path = Path(path)
        self._document_dirty = False
        self._undo_stacks[id(self._active_view)].clear()
        self._redo_stacks[id(self._active_view)].clear()
        self._update_undo_actions()
        self._update_title()
        self._page_input.setMaximum(doc.page_count)
        self._page_input.setValue(1)
        self._page_total_label.setText(f" / {doc.page_count}  ")
        self._recent.add(path)
        self._refresh_recent_menu()
        self._update_status()
        # Update bookmark panel for the newly loaded document
        self._bookmark_panel.set_document(doc)
        # Auto-show the dock if this file has bookmarks (and dock was closed)
        if self._bookmark_dock.isHidden():
            try:
                if doc.doc.get_toc():
                    self._bookmark_dock.show()
            except Exception:  # noqa: BLE001
                pass

    def _update_title(self) -> None:
        """Set window title to reflect currently open files in both panels."""
        p1 = self._panel_paths.get(id(self._view))
        if self._view2 is not None:
            p2 = self._panel_paths.get(id(self._view2))
            if p1 and p2:
                self.setWindowTitle(f"{p1.name} | {p2.name} — LucidLectorPDF")
                return
            if p1:
                self.setWindowTitle(f"{p1.name} — LucidLectorPDF")
                return
        if p1:
            self.setWindowTitle(f"{p1.name} — LucidLectorPDF")
        else:
            self.setWindowTitle("LucidLectorPDF")

    def _refresh_recent_menu(self) -> None:
        self._recent_menu.clear()
        items = self._recent.list()
        if not items:
            empty = QAction(_s(self._locale, "recent_empty"), self)
            empty.setEnabled(False)
            self._recent_menu.addAction(empty)
            return
        for p in items:
            act = QAction(p, self)
            act.triggered.connect(lambda _=False, pp=p: self.open_path(pp))
            self._recent_menu.addAction(act)
        self._recent_menu.addSeparator()
        clear = QAction(_s(self._locale, "recent_clear"), self)
        clear.triggered.connect(self._clear_recent)
        self._recent_menu.addAction(clear)

    def _clear_recent(self) -> None:
        self._recent.clear()
        self._refresh_recent_menu()

    # ================================================================== #
    # Eye filter
    # ================================================================== #
    def _set_eye_filter(self, mode: str) -> None:
        colors: dict[str, QColor] = {
            "hafif":     QColor(255, 210, 140,  30),
            "warm":      QColor(255, 220, 150,  55),
            "sepia":     QColor(245, 220, 180,  75),
            "yesil":     QColor( 80, 200,  80,  38),
            "pembe":     QColor(255, 160, 180,  45),
            "gece":      QColor(255, 130,  60, 110),
            "koyu_gece": QColor(255, 100,  30, 155),
            "karartma":  QColor(  0,   0,   0,  90),
        }
        color = colors.get(mode)
        self._current_eye_mode = mode
        self._view.set_eye_filter(color)
        if self._view2 is not None:
            self._view2.set_eye_filter(color)
        self._translation_panel.set_eye_filter(color)
        self._settings.setValue("eyeFilter", mode)

    # ================================================================== #
    # View mode
    # ================================================================== #
    def _set_view_mode(self, dual: bool) -> None:
        self._view.set_dual_view(dual)
        if self._act_dual.isChecked() != dual:
            self._act_dual.setChecked(dual)
        if dual and not self._act_dual_tb.isChecked():
            self._act_dual_tb.setChecked(True)
        if not dual and not self._act_single_tb.isChecked():
            self._act_single_tb.setChecked(True)

    def _set_active_panel(self, view: "PdfView") -> None:
        """Called when a panel receives a mouse-press; routes actions to it."""
        # Guard: ignore stale signals from a panel that was already removed.
        if view is not self._view and view is not self._view2:
            return
        if view is self._active_view:
            return
        self._active_view = view
        self._view.set_active_indicator(view is self._view)
        if self._view2 is not None:
            self._view2.set_active_indicator(view is self._view2)
        self._sync_page_input()
        self._update_status()
        self._update_undo_actions()
        # Update total-pages label for the newly-active panel's doc
        v = self._active_view
        if v.doc is not None:
            self._page_input.setMaximum(v.doc.page_count)
            self._page_total_label.setText(f" / {v.doc.page_count}  ")
        else:
            self._page_input.setMaximum(1)
            self._page_total_label.setText(" / 0  ")
        # Refresh bookmark panel for the newly active panel's document
        self._bookmark_panel.set_document(self._active_view.doc)
        if self._active_view.doc is not None:
            self._bookmark_panel.highlight_current(self._active_view.current_page())

    def _toggle_split(self, checked: bool) -> None:
        """Open or close the second panel next to the main view."""
        if checked:
            if self._view2 is not None:
                return   # already split
            self._view2 = PdfView(self)
            v2 = self._view2   # stable local reference for lambda captures
            # Navigation / activation signals
            v2.panel_activated.connect(lambda: self._set_active_panel(v2))
            v2.verticalScrollBar().valueChanged.connect(
                lambda: self._on_scroll(v2)
            )
            v2.page_changed.connect(
                lambda p: self._on_page_changed(p, v2)
            )
            # Annotation / translation signals — same handlers as primary view
            v2.translate_requested.connect(self._on_translate)
            v2.highlight_requested.connect(self._on_highlight)
            v2.underline_requested.connect(self._on_underline)
            v2.delete_annotation_requested.connect(self._on_delete_annotation)
            v2.pdf_sentence_hovered.connect(
                self._translation_panel.highlight_sentence
            )
            v2.pdf_sentence_left.connect(
                self._translation_panel.clear_sentence_highlight
            )
            # Apply current UI state to the new panel
            v2.set_locale(self._locale)
            colors: dict[str, "QColor"] = {
                "hafif":     QColor(255, 210, 140,  30),
                "warm":      QColor(255, 220, 150,  55),
                "sepia":     QColor(245, 220, 180,  75),
                "yesil":     QColor( 80, 200,  80,  38),
                "pembe":     QColor(255, 160, 180,  45),
                "gece":      QColor(255, 130,  60, 110),
                "koyu_gece": QColor(255, 100,  30, 155),
                "karartma":  QColor(  0,   0,   0,  90),
            }
            v2.set_eye_filter(colors.get(self._current_eye_mode))
            # Initialise per-panel state for the new panel
            self._panel_paths[id(v2)] = None
            self._panel_dirty[id(v2)] = False
            self._undo_stacks[id(v2)] = []
            self._redo_stacks[id(v2)] = []
            # Add to splitter and open the same file independently so docs are fully decoupled
            self._splitter.addWidget(v2)
            v2.show()
            primary_path = self._panel_paths.get(id(self._view))
            if primary_path is not None:
                try:
                    v2_doc = PdfDocument(str(primary_path))
                    v2.load(v2_doc)
                    self._panel_paths[id(v2)] = primary_path
                except Exception:  # noqa: BLE001
                    pass
            self._update_title()
        else:
            if self._view2 is None:
                return
            self._panel_paths.pop(id(self._view2), None)
            self._panel_dirty.pop(id(self._view2), None)
            self._undo_stacks.pop(id(self._view2), None)
            self._redo_stacks.pop(id(self._view2), None)
            self._view2.clear()
            self._view2.setParent(None)   # type: ignore[arg-type]
            self._view2.deleteLater()
            self._view2 = None
            # Primary panel becomes the only active panel
            self._active_view = self._view
            self._view.set_active_indicator(True)
            self._sync_page_input()
            self._update_status()
            self._update_title()

    def _rotate_pages(self, delta: int = 90) -> None:
        if self._view.doc is None:
            return
        self._view.rotate(delta)
        self._document_dirty = True

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.menuBar().show()
            self._toolbar.show()
            self.statusBar().show()
            self._act_full.setChecked(False)
        else:
            self.menuBar().hide()
            self._toolbar.hide()
            self.statusBar().hide()
            self.showFullScreen()
            self._act_full.setChecked(True)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self._toggle_fullscreen()
            return
        super().keyPressEvent(event)

    # ================================================================== #
    # Search
    # ================================================================== #
    def _open_search(self) -> None:
        self._search.show()
        self._search.focus_input()

    def _run_search(self, query: str) -> None:
        if self._view.doc is None:
            return
        results = self._view.doc.search(query)
        count = self._view.apply_search(results)
        self._search.set_match_count(count)

    # ================================================================== #
    # Translation
    # ================================================================== #
    def _on_translate(self, text: str) -> None:
        if not text:
            return
        self.statusBar().showMessage(_s(self._locale, "status_translating"), 3000)
        self._translator.translate(text)

    def _show_translation(self, original: str, translated: str) -> None:
        self._last_original = original          # remember for re-translate on lang change
        self._view.clear_hover_highlight()      # reset stale hover from previous translation
        self._view.set_translation_context(original)
        self._translation_panel.set_content(original, translated)
        self._translation_dock.show()
        self._translation_dock.raise_()

    def _translation_failed(self, _original: str, err: str) -> None:
        QMessageBox.warning(
            self,
            _s(self._locale, "dlg_trans_fail_title"),
            _s(self._locale, "dlg_trans_fail_msg").format(err=err),
        )

    # ================================================================== #
    # Annotations (highlight + underline)
    # ================================================================== #
    def _rerender_page(self, page_index: int) -> None:
        """Re-render *page_index* in the active view.
        Also mirrors to the other panel if both panels show the same file."""
        self._active_view.rerender_page(page_index)
        other = self._view2 if self._active_view is self._view else self._view
        if (
            other is not None
            and other.doc is not None
            and self._active_view.doc is not None
            and str(other.doc.path) == str(self._active_view.doc.path)
        ):
            other.rerender_page(page_index)

    def _on_highlight(self, page_index: int, rects: list) -> None:
        self._add_annotation("highlight", page_index, rects)

    def _on_underline(self, page_index: int, rects: list) -> None:
        self._add_annotation("underline", page_index, rects)

    def _create_annot(self, kind: str, pi: int, rects: list, color: tuple) -> int | None:
        if self._active_view.doc is None:
            return None
        if kind == "underline":
            return self._active_view.doc.add_underline(pi, rects, color=color)
        return self._active_view.doc.add_highlight(pi, rects, color=color)

    def _add_annotation(self, kind: str, page_index: int, rects: list) -> None:
        color = self._color_for(kind)
        xref = self._create_annot(kind, page_index, rects, color)
        if xref is None:
            return
        self._rerender_page(page_index)
        self._document_dirty = True
        self._undo_stack.append(
            {"op": "add", "kind": kind, "page_index": page_index,
             "xref": xref, "rects": rects, "color": color}
        )
        self._redo_stack.clear()
        self._update_undo_actions()

    def _on_delete_annotation(self, page_index: int, pdf_xy: tuple) -> None:
        if self._active_view.doc is None:
            return
        removed = self._active_view.doc.delete_annotation_at(page_index, pdf_xy)
        if removed is None:
            return
        self._rerender_page(page_index)
        self._document_dirty = True
        self._undo_stack.append({"op": "delete", "page_index": page_index, **removed})
        self._redo_stack.clear()
        self._update_undo_actions()

    def _undo(self) -> None:
        if not self._undo_stack or self._active_view.doc is None:
            return
        action = self._undo_stack.pop()
        pi = action["page_index"]
        if action["op"] == "add":
            self._active_view.doc.remove_annotation_by_xref(pi, action["xref"])
        else:
            action["xref"] = self._create_annot(
                action["kind"], pi, action["rects"], action["color"]
            )
        self._active_view.rerender_page(pi)
        self._redo_stack.append(action)
        self._document_dirty = True
        self._update_undo_actions()

    def _redo(self) -> None:
        if not self._redo_stack or self._active_view.doc is None:
            return
        action = self._redo_stack.pop()
        pi = action["page_index"]
        if action["op"] == "add":
            action["xref"] = self._create_annot(
                action["kind"], pi, action["rects"], action["color"]
            )
        else:
            self._active_view.doc.remove_annotation_by_xref(pi, action["xref"])
        self._active_view.rerender_page(pi)
        self._undo_stack.append(action)
        self._document_dirty = True
        self._update_undo_actions()

    def _update_undo_actions(self) -> None:
        self._act_undo.setEnabled(bool(self._undo_stack))
        self._act_redo.setEnabled(bool(self._redo_stack))

    # ================================================================== #
    # Color helpers
    # ================================================================== #
    def _load_color(self, key: str, default_hex: str) -> tuple[float, float, float]:
        saved = self._settings.value(key, default_hex, type=str)
        qc = QColor(saved)
        if not qc.isValid():
            qc = QColor(default_hex)
        return (qc.redF(), qc.greenF(), qc.blueF())

    def _pick_highlight_color(self) -> None:
        self._pick_color(
            _s(self._locale, "act_hl_color").rstrip("…"),
            "highlightColor", "_highlight_color",
        )
        self._update_color_swatch(self._act_color, self._highlight_color)

    def _pick_underline_color(self) -> None:
        self._pick_color(
            _s(self._locale, "act_ul_color").rstrip("…"),
            "underlineColor", "_underline_color",
        )
        self._update_color_swatch(self._act_underline_color, self._underline_color)

    def _pick_color(self, title: str, settings_key: str, attr: str) -> None:
        initial = QColor.fromRgbF(*getattr(self, attr))
        chosen = QColorDialog.getColor(initial, self, title)
        if not chosen.isValid():
            return
        rgb = (chosen.redF(), chosen.greenF(), chosen.blueF())
        setattr(self, attr, rgb)
        self._settings.setValue(settings_key, chosen.name())

    def _update_color_swatch(
        self, action: QAction, color: tuple[float, float, float]
    ) -> None:
        pix = QPixmap(16, 16)
        pix.fill(QColor.fromRgbF(*color))
        action.setIcon(QIcon(pix))

    def _color_for(self, kind: str) -> tuple[float, float, float]:
        return self._underline_color if kind == "underline" else self._highlight_color

    # ================================================================== #
    # Save
    # ================================================================== #
    def _do_save_incremental(self) -> bool:
        """Save in-place; show status on success. Returns True on success."""
        try:
            self._active_view.doc.save_incremental()  # type: ignore[union-attr]
            self._document_dirty = False
            self.statusBar().showMessage(_s(self._locale, "status_saved"), 2500)
            return True
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, _s(self._locale, "dlg_save_err_title"), str(e))
            return False

    def _save(self) -> None:
        if self._active_view.doc is None or not self._document_dirty:
            self.statusBar().showMessage(_s(self._locale, "status_no_change"), 2500)
            return
        self._do_save_incremental()

    def _prompt_save(self) -> bool:
        if self._active_view.doc is None or not self._document_dirty or self._current_path is None:
            return True

        msg = QMessageBox(self)
        msg.setWindowTitle(_s(self._locale, "dlg_save_title"))
        msg.setText(
            _s(self._locale, "dlg_save_text").format(name=self._current_path.name)
        )
        msg.setInformativeText(_s(self._locale, "dlg_save_info"))
        overwrite_btn = msg.addButton(
            _s(self._locale, "dlg_save_overwrite"), QMessageBox.ButtonRole.AcceptRole
        )
        save_as_btn = msg.addButton(
            _s(self._locale, "dlg_save_as"), QMessageBox.ButtonRole.AcceptRole
        )
        skip_btn = msg.addButton(
            _s(self._locale, "dlg_save_skip"), QMessageBox.ButtonRole.DestructiveRole
        )
        cancel_btn = msg.addButton(
            _s(self._locale, "dlg_save_cancel"), QMessageBox.ButtonRole.RejectRole
        )
        msg.setDefaultButton(overwrite_btn)
        msg.exec()
        clicked = msg.clickedButton()

        if clicked is cancel_btn:
            return False
        if clicked is skip_btn:
            return True
        if clicked is save_as_btn:
            suggested = self._current_path.with_name(
                self._current_path.stem + "_highlighted.pdf"
            )
            new_path, _ = QFileDialog.getSaveFileName(
                self,
                _s(self._locale, "dlg_saveas_title"),
                str(suggested),
                _s(self._locale, "dlg_open_filter"),
            )
            if not new_path:
                return False
            try:
                self._active_view.doc.save_as(new_path)
                self._document_dirty = False
                self.statusBar().showMessage(
                    _s(self._locale, "status_saved_as").format(path=new_path), 3000
                )
                return True
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(
                    self, _s(self._locale, "dlg_save_err_title"), str(e)
                )
                return False
        # overwrite
        return self._do_save_incremental()

    def closeEvent(self, event) -> None:
        # Prompt save for both panels (primary first, then secondary if present)
        saved_active = self._active_view
        for view in [v for v in [self._view, self._view2] if v is not None]:
            self._active_view = view
            if not self._prompt_save():
                self._active_view = saved_active
                event.ignore()
                return
        self._active_view = saved_active
        super().closeEvent(event)

    # ================================================================== #
    # Status bar
    # ================================================================== #
    def _update_status(self) -> None:
        v = self._active_view
        if v.doc is None:
            self._status_page.setText("")
            self._status_zoom.setText("")
            return
        cur = v.current_page() + 1
        total = v.doc.page_count
        self._status_page.setText(
            _s(self._locale, "status_page").format(cur=cur, total=total) + "   "
        )
        self._status_zoom.setText(f"{int(v.zoom() * 100)}%   ")

    # ================================================================== #
    # About
    # ================================================================== #
    def _about(self) -> None:
        months = {
            "tr": ["Ocak","Şubat","Mart","Nisan","Mayıs","Haziran",
                   "Temmuz","Ağustos","Eylül","Ekim","Kasım","Aralık"],
            "en": ["January","February","March","April","May","June",
                   "July","August","September","October","November","December"],
            "es": ["enero","febrero","marzo","abril","mayo","junio",
                   "julio","agosto","septiembre","octubre","noviembre","diciembre"],
            "de": ["Januar","Februar","März","April","Mai","Juni",
                   "Juli","August","September","Oktober","November","Dezember"],
            "fr": ["janvier","février","mars","avril","mai","juin",
                   "juillet","août","septembre","octobre","novembre","décembre"],
            "ru": ["января","февраля","марта","апреля","мая","июня",
                   "июля","августа","сентября","октября","ноября","декабря"],
        }
        now = datetime.now()
        month_list = months.get(self._locale, months["en"])
        date_str = f"{month_list[now.month - 1]} {now.year}"
        QMessageBox.about(
            self,
            _s(self._locale, "act_about"),
            f"<h3>LucidLectorPDF v{__version__}</h3>"
            f"<p><b>{date_str}</b></p>"
            f"<p>Ömür Akınel — Vibe Coding</p>"
            f"<p>📧 <a href='mailto:akinel@gmail.com'>akinel@gmail.com</a></p>"
            f"<p style='color:#888'>PyQt6 · PyMuPDF · deep-translator</p>",
        )
