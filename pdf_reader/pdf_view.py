"""QGraphicsView-based PDF viewer with text selection and context menu."""
from __future__ import annotations

from dataclasses import dataclass

import fitz
from PyQt6.QtCore import QObject, QPoint, QPointF, QRectF, QRunnable, Qt, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QCursor,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QGraphicsObject,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QMenu,
    QWidget,
)

from .i18n import s as _s
from .pdf_document import PdfDocument, Word
from .text_utils import MIN_SENTENCE_LENGTH, search_variants, sentences


_RENDER_POOL: QThreadPool | None = None


def _render_pool() -> QThreadPool:
    """The thread pool used for page rendering, created on first use.

    Deliberately not QThreadPool.globalInstance(): the translator submits there
    too and its network calls have no timeout, so a few stalled translations
    used to starve page rendering completely. Equally deliberately shared by
    every PdfView rather than one pool per view — with a split view, per-view
    pools would oversubscribe the CPU with twice the render threads.
    """
    global _RENDER_POOL
    if _RENDER_POOL is None:
        _RENDER_POOL = QThreadPool()
        _RENDER_POOL.setMaxThreadCount(
            max(2, QThreadPool.globalInstance().maxThreadCount() - 1)
        )
    return _RENDER_POOL


class _RenderSignals(QObject):
    """Carry a finished (or failed) page render back to the main thread."""
    # Both carry (page_index, payload, generation) — keeping the argument order
    # identical means a mixed-up connection fails loudly instead of silently
    # swapping two same-typed ints.
    done = pyqtSignal(int, object, int)    # page_index, QImage, generation
    failed = pyqtSignal(int, str, int)     # page_index, error message, generation


class _PageRenderTask(QRunnable):
    """Render one PDF page off the main thread via an independent fitz handle."""

    def __init__(
        self,
        path: str,
        page_index: int,
        zoom: float,
        k: float,
        generation: int,
        signals: _RenderSignals,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._path = path
        self._page_index = page_index
        self._zoom = zoom
        self._k = k
        self._generation = generation
        self._signals = signals

    def run(self) -> None:  # noqa: D102
        doc = None
        try:
            doc = fitz.open(self._path)
            if doc.needs_pass:
                raise ValueError("Belge parola korumalı.")
            page = doc[self._page_index]
            matrix = fitz.Matrix(self._zoom * self._k, self._zoom * self._k)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = QImage(
                pix.samples, pix.width, pix.height, pix.stride,
                QImage.Format.Format_RGB888,
            ).copy()   # detach from pix buffer before doc.close()
            self._signals.done.emit(self._page_index, img, self._generation)
        except Exception as e:  # noqa: BLE001
            # Must still report back: the view keeps this page in
            # _pending_renders and would never retry it otherwise.
            try:
                self._signals.failed.emit(self._page_index, str(e), self._generation)
            except Exception:  # noqa: BLE001
                # An exception escaping run() is fatal under PyQt (qFatal),
                # so the reporting path must never raise either.
                pass
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:  # noqa: BLE001
                    pass


class ParagraphMarker(QGraphicsObject):
    """Tiny circular badge placed at the start of a paragraph; click to translate."""

    SIZE = 20
    clicked = pyqtSignal(str)

    def __init__(self, paragraph_text: str, parent=None):
        super().__init__(parent)
        self._text = paragraph_text
        self._hovered = False
        self._active = False
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(20)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.SIZE, self.SIZE)

    def paint(self, painter: QPainter, _opt, _w=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._active:
            bg = QColor("#C9A227")          # geleneksel altın — aktif durum
            border = QColor("#7B5E0C")      # koyu altın / bronz çerçeve
            icon_color = QColor("#0D1B4B")  # lacivert T altın üzerine
        elif self._hovered:
            bg = QColor("#0D1B4B")          # çok koyu lacivert
            border = QColor("#E8C84A")      # açık altın çerçeve
            icon_color = QColor("#E8C84A")  # açık altın T
        else:
            bg = QColor(26, 35, 126, 215)   # #1A237E derin indigo, hafif saydam
            border = QColor("#C9A227")       # geleneksel akademik altın
            icon_color = QColor("#C9A227")   # altın T

        # daire arka plan
        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(border, 1.5))
        painter.drawEllipse(QRectF(0.5, 0.5, self.SIZE - 1, self.SIZE - 1))

        # serif T — akademik tipografi stili
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(icon_color))
        painter.drawRect(QRectF(4.0, 4.5, 12.0, 2.0))   # ince geniş çıta (crossbar)
        painter.drawRect(QRectF(9.0, 6.5,  2.0, 7.5))   # ince dar gövde (stem)
        painter.drawRect(QRectF(7.0, 14.0, 6.0, 1.5))   # alt serif (foot)

    def hoverEnterEvent(self, event) -> None:  # noqa: ARG002
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, event) -> None:  # noqa: ARG002
        self._hovered = False
        self.update()

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._text)
            event.accept()
            return
        super().mousePressEvent(event)


class AutoscrollIndicator(QWidget):
    """Small 4-direction joystick overlay shown during middle-click autoscroll."""

    SIZE = 36

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.SIZE
        # Background circle
        p.setPen(QPen(QColor(60, 60, 60, 200), 1.2))
        p.setBrush(QBrush(QColor(255, 255, 255, 230)))
        p.drawEllipse(2, 2, s - 4, s - 4)
        # 4 direction arrows
        pen = QPen(QColor(40, 40, 40), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        cx = cy = s / 2
        arm = s * 0.28
        tip = s * 0.08
        # up
        p.drawLine(int(cx), int(cy - arm), int(cx - tip), int(cy - arm + tip))
        p.drawLine(int(cx), int(cy - arm), int(cx + tip), int(cy - arm + tip))
        # down
        p.drawLine(int(cx), int(cy + arm), int(cx - tip), int(cy + arm - tip))
        p.drawLine(int(cx), int(cy + arm), int(cx + tip), int(cy + arm - tip))
        # left
        p.drawLine(int(cx - arm), int(cy), int(cx - arm + tip), int(cy - tip))
        p.drawLine(int(cx - arm), int(cy), int(cx - arm + tip), int(cy + tip))
        # right
        p.drawLine(int(cx + arm), int(cy), int(cx + arm - tip), int(cy - tip))
        p.drawLine(int(cx + arm), int(cy), int(cx + arm - tip), int(cy + tip))
        # center dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(40, 40, 40)))
        p.drawEllipse(int(cx - 2.5), int(cy - 2.5), 5, 5)

PAGE_GAP = 12  # pixels between pages in scene
RENDER_KEEP_VIEWPORTS = 3  # keep rendered pages within this many viewport heights
RENDER_LOAD_VIEWPORTS = 1   # pre-render pages just outside the visible viewport
MERGED_PARAGRAPH_PAGE_LIMIT = 300
MAX_RENDER_ATTEMPTS = 3      # give up on a page after this many failed renders
RENDER_RETRY_DELAY_MS = 400  # wait between attempts; transient locks clear fast
SELECTION_COLOR    = QColor( 80, 140, 255,  90)
HIGHLIGHT_COLOR    = QColor(255, 230,   0, 110)
SEARCH_COLOR       = QColor(255, 235,   0, 140)
SEARCH_ACTIVE_COLOR= QColor(255, 140,   0, 180)
HOVER_COLOR        = QColor( 50, 210, 180, 130)  # teal — translation-panel hover


@dataclass
class PageLayout:
    index: int
    x_offset: float       # left of page in scene
    y_offset: float       # top of page in scene
    width: float          # scene-space width
    height: float         # scene-space height
    pdf_width: float      # width in PDF points
    pdf_height: float     # height in PDF points


class PdfView(QGraphicsView):
    selection_changed = pyqtSignal(str)
    translate_requested = pyqtSignal(str)
    highlight_requested = pyqtSignal(int, list)  # page_index, list[fitz.Rect]
    underline_requested = pyqtSignal(int, list)  # page_index, list[fitz.Rect]
    delete_annotation_requested = pyqtSignal(int, object)  # page_index, (x, y)
    page_changed = pyqtSignal(int)
    render_failed = pyqtSignal(int, str)     # page_index, error message
    pdf_sentence_hovered = pyqtSignal(str)   # sentence text under cursor
    pdf_sentence_left = pyqtSignal()
    panel_activated = pyqtSignal()           # any mouse press — marks this panel as active

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            QPainter.RenderHint.SmoothPixmapTransform
            | QPainter.RenderHint.Antialiasing
        )
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.doc: PdfDocument | None = None
        self._zoom: float = 1.0
        self._render_scale: float = 2.0   # oversample for crisp rendering
        self._dual_view: bool = False
        self._current_spread_start: int = 0   # leftmost page of active spread
        self._wheel_accum: int = 0            # wheel delta accumulator (dual view)
        self._pages: list[PageLayout | None] = []
        self._page_items: list[QGraphicsPixmapItem | None] = []
        self._page_placeholders: list[QGraphicsRectItem | None] = []
        self._rendered_pages: set[int] = set()
        self._selection_items: list[QGraphicsRectItem] = []
        self._search_items: list[QGraphicsRectItem] = []
        self._search_rects: list[tuple[int, fitz.Rect]] = []  # (page, rect) flat
        self._active_search_index: int = -1

        self._selecting = False
        self._sel_anchor_scene: QPointF | None = None

        self._paragraph_mode: bool = False
        self._paragraph_markers: list[ParagraphMarker] = []
        self._active_paragraph_marker: ParagraphMarker | None = None
        self._eye_filter_color: QColor | None = None
        self._locale: str = "tr"
        self._hover_items: list[QGraphicsRectItem] = []
        # PDF→panel hover. The sentences of the active translation, plus their
        # rects resolved lazily per page (page_index → [(rect, sentence), …]).
        self._context_sentences: list[str] = []
        self._sentence_rects_by_page: dict[int, list[tuple[fitz.Rect, str]]] = {}
        self._last_pdf_hover_sentence: str = ""
        # Always-on hover detection — required for mouseMoveEvent to fire
        # without a button held down.
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

        # Autoscroll (middle-click joystick)
        self._autoscroll_anchor: QPoint | None = None
        self._autoscroll_indicator: AutoscrollIndicator | None = None
        self._autoscroll_timer = QTimer(self)
        self._autoscroll_timer.setInterval(16)  # ~60 fps
        self._autoscroll_timer.timeout.connect(self._tick_autoscroll)
        self._render_update_timer = QTimer(self)
        self._render_update_timer.setSingleShot(True)
        self._render_update_timer.setInterval(30)
        self._render_update_timer.timeout.connect(self._update_visible_pages)
        self._selected_words: list[Word] = []
        self._selected_rects_by_page: dict[int, list[fitz.Rect]] = {}

        # Async rendering support
        self._pending_renders: set[int] = set()       # pages currently in the thread pool
        self._render_generation: int = 0              # bumped on rebuild/zoom to discard stale results
        self._render_pool = _render_pool()
        # page_index → (attempts so far, last error message)
        self._failed_renders: dict[int, tuple[int, str]] = {}
        # One long-lived signal relay shared by every render task. Created on
        # the main thread, so worker-thread emits arrive as queued connections.
        # Deliberately NOT parented to this view: an in-flight task holds a
        # reference to it, and if Qt destroyed it together with the widget
        # (e.g. the split panel being closed mid-render) that task would emit
        # on a dead C++ object. Without a parent the Python reference keeps it
        # alive, and Qt drops the connections by itself once the receiving
        # view is destroyed, so late emits are simply ignored.
        self._render_signals = _RenderSignals()
        self._render_signals.done.connect(self._on_page_ready)
        self._render_signals.failed.connect(self._on_page_failed)

        self.setBackgroundBrush(QBrush(QColor(Qt.GlobalColor.black)))
        self._scene.setBackgroundBrush(QBrush(QColor(Qt.GlobalColor.black)))
        self.verticalScrollBar().valueChanged.connect(self._schedule_visible_render_update)
        self.horizontalScrollBar().valueChanged.connect(self._schedule_visible_render_update)

    # ---------- document ----------
    def load(self, doc: PdfDocument) -> None:
        self.clear()
        self.doc = doc
        self._current_spread_start = 0
        self._rebuild()

    def shutdown(self) -> None:
        """Stop rendering and wait for in-flight tasks.

        Call before this view is torn down (split panel closed, application
        quitting) so no worker is still touching the document afterwards. The
        pool is shared, so this briefly waits on the other panel's tasks too;
        they are re-queued on the next scroll.
        """
        self._render_generation += 1
        self._render_update_timer.stop()
        self._render_pool.clear()        # drop queued tasks that never started
        self._render_pool.waitForDone(3000)
        self._pending_renders.clear()
        self._failed_renders.clear()

    def clear(self) -> None:
        # Discard any in-flight renders before clearing state.
        self._render_generation += 1
        self._pending_renders.clear()
        self._failed_renders.clear()
        self._render_update_timer.stop()

        self._scene.clear()
        self._pages.clear()
        self._page_items.clear()
        self._page_placeholders.clear()
        self._rendered_pages.clear()
        self._selection_items.clear()
        self._search_items.clear()
        self._search_rects.clear()
        self._selected_words.clear()
        self._selected_rects_by_page.clear()
        # Scene.clear() destroys these items; drop dangling Python refs too.
        self._paragraph_markers.clear()
        self._active_paragraph_marker = None
        self._hover_items.clear()
        self._active_search_index = -1
        self._context_sentences = []
        self._sentence_rects_by_page.clear()
        self._last_pdf_hover_sentence = ""
        if self.doc is not None:
            self.doc.close()
            self.doc = None

    def _rebuild(self) -> None:
        assert self.doc is not None
        # Discard any in-flight renders from the previous layout.
        self._render_generation += 1
        self._pending_renders.clear()
        self._failed_renders.clear()

        self._scene.clear()
        self._pages = [None] * self.doc.page_count
        self._page_items = [None] * self.doc.page_count
        self._page_placeholders = [None] * self.doc.page_count
        self._rendered_pages.clear()
        self._selection_items.clear()
        self._search_items.clear()
        # scene.clear() already destroyed these; drop the Python refs so the
        # next _refresh_paragraph_markers doesn't try to remove dead items.
        self._paragraph_markers.clear()
        self._hover_items.clear()   # scene.clear() destroyed them too

        # Dual view lays out only the current spread; single view lays out every
        # page but renders pixmaps lazily as they approach the viewport.
        if self._dual_view:
            s = self._current_spread_start
            indices = [s] + ([s + 1] if s + 1 < self.doc.page_count else [])
            per_row = 2
        else:
            indices = list(range(self.doc.page_count))
            per_row = 1

        scene_sizes: dict[int, tuple[float, float]] = {}
        for i in indices:
            pdf_w, pdf_h = self.doc.page_size(i)
            scene_sizes[i] = (pdf_w * self._zoom, pdf_h * self._zoom)

        rows = [indices[i : i + per_row] for i in range(0, len(indices), per_row)]
        max_row_w = 0.0
        for row in rows:
            max_row_w = max(
                max_row_w,
                sum(scene_sizes[p][0] for p in row) + PAGE_GAP * (len(row) - 1),
            )

        y = 0.0
        for row in rows:
            row_w = sum(scene_sizes[p][0] for p in row) + PAGE_GAP * (len(row) - 1)
            row_h = max(scene_sizes[p][1] for p in row)
            x = (max_row_w - row_w) / 2.0
            for p_idx in row:
                scene_w, scene_h = scene_sizes[p_idx]
                py = y + (row_h - scene_h) / 2.0
                placeholder = self._scene.addRect(
                    QRectF(x, py, scene_w, scene_h),
                    QPen(Qt.PenStyle.NoPen),
                    QBrush(QColor(45, 45, 45)),
                )
                placeholder.setZValue(0)
                self._page_placeholders[p_idx] = placeholder

                pdf_w, pdf_h = self.doc.page_size(p_idx)
                self._pages[p_idx] = PageLayout(
                    index=p_idx,
                    x_offset=x,
                    y_offset=py,
                    width=scene_w,
                    height=scene_h,
                    pdf_width=pdf_w,
                    pdf_height=pdf_h,
                )
                x += scene_w + PAGE_GAP
            y += row_h + PAGE_GAP

        self._scene.setSceneRect(0, 0, max_row_w, max(y - PAGE_GAP, 0))

        # Re-apply search overlays on the newly rendered spread.
        if self._search_rects:
            self._redraw_search_overlays()
        # Re-apply paragraph markers if mode is on.
        if self._paragraph_mode:
            self._refresh_paragraph_markers()
        self._update_visible_pages()

    def _schedule_visible_render_update(self, *_args) -> None:
        if self.doc is not None:
            self._render_update_timer.start()

    def _visible_scene_rect(self, extra_viewports: int = 0) -> QRectF:
        rect = self.mapToScene(self.viewport().rect()).boundingRect()
        if extra_viewports <= 0:
            return rect
        pad_x = self.viewport().width() * 0.5
        pad_y = self.viewport().height() * extra_viewports
        return rect.adjusted(-pad_x, -pad_y, pad_x, pad_y)

    def _page_indices_near_viewport(self, extra_viewports: int) -> set[int]:
        if self.doc is None:
            return set()
        if self._dual_view:
            s = self._current_spread_start
            return {i for i in (s, s + 1) if i < self.doc.page_count}
        visible = self._visible_scene_rect(extra_viewports)
        out: set[int] = set()
        for page in self._pages:
            if page is None:
                continue
            page_rect = QRectF(page.x_offset, page.y_offset, page.width, page.height)
            if visible.intersects(page_rect):
                out.add(page.index)
        return out

    def _ensure_page_rendered(self, page_index: int) -> None:
        """Schedule async rendering for *page_index* if not already rendered/pending."""
        if self.doc is None:
            return
        if page_index in self._rendered_pages or page_index in self._pending_renders:
            return
        # Retry a failed page a couple of times (transient causes like the file
        # being briefly locked during an incremental save are common), then stop
        # so a genuinely broken page can't flood the thread pool.
        attempts, _ = self._failed_renders.get(page_index, (0, ""))
        if attempts >= MAX_RENDER_ATTEMPTS:
            return
        if page_index >= len(self._pages):
            return
        if self._pages[page_index] is None:
            return

        self._pending_renders.add(page_index)
        task = _PageRenderTask(
            str(self.doc.path),
            page_index,
            self._zoom,
            self._render_scale,
            self._render_generation,
            self._render_signals,
        )
        self._render_pool.start(task)

    def _on_page_failed(self, page_index: int, error: str, generation: int) -> None:
        """A render task raised — release the page so it can be retried."""
        if generation != self._render_generation:
            return   # stale failure from before a zoom/rebuild
        self._pending_renders.discard(page_index)
        attempts = self._failed_renders.get(page_index, (0, ""))[0] + 1
        self._failed_renders[page_index] = (attempts, error)
        if attempts < MAX_RENDER_ATTEMPTS:
            # Don't alarm the user yet — schedule the retry ourselves rather
            # than waiting for a scroll, which may never come.
            QTimer.singleShot(RENDER_RETRY_DELAY_MS, self._update_visible_pages)
            return
        self.render_failed.emit(page_index, error)
        # Mark the placeholder so the user can tell an unrendered page from a
        # broken one instead of staring at an identical grey rectangle.
        ph = self._page_placeholders[page_index] if page_index < len(
            self._page_placeholders
        ) else None
        if ph is not None:
            ph.setBrush(QBrush(QColor(70, 40, 40)))
            ph.setToolTip(
                _s(self._locale, "status_render_fail").format(
                    page=page_index + 1, err=error
                )
            )

    def _on_page_ready(self, page_index: int, img: object, generation: int) -> None:
        """Queued from a worker thread — place the rendered page in the scene."""
        if generation != self._render_generation:
            return   # stale result from before a zoom/rebuild
        self._pending_renders.discard(page_index)
        self._failed_renders.pop(page_index, None)
        if self.doc is None:
            return
        layout = self._pages[page_index]
        if layout is None:
            return
        K = self._render_scale
        pix = QPixmap.fromImage(img)  # type: ignore[arg-type]
        item = QGraphicsPixmapItem(pix)
        item.setScale(1.0 / K)
        item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        item.setPos(layout.x_offset, layout.y_offset)
        item.setZValue(1)
        self._scene.addItem(item)
        self._page_items[page_index] = item
        self._rendered_pages.add(page_index)
        # Hide the placeholder now that the real pixmap is in place.
        ph = self._page_placeholders[page_index]
        if ph is not None:
            ph.setVisible(False)
        # Refresh overlays that were waiting for this page to be rendered.
        if self._search_rects:
            self._redraw_search_overlays()

    def _unload_page(self, page_index: int) -> None:
        if page_index >= len(self._page_items):
            return
        item = self._page_items[page_index]
        if item is not None:
            try:
                self._scene.removeItem(item)
            except RuntimeError:
                pass
        self._page_items[page_index] = None
        self._rendered_pages.discard(page_index)
        # Restore the placeholder so the page slot stays visible while
        # it is unloaded (the page may be re-rendered when scrolled back).
        ph = self._page_placeholders[page_index]
        if ph is not None:
            ph.setVisible(True)

    def _update_visible_pages(self) -> None:
        if self.doc is None:
            return
        to_render = self._page_indices_near_viewport(RENDER_LOAD_VIEWPORTS)
        for page_index in sorted(to_render):
            self._ensure_page_rendered(page_index)

        keep = self._page_indices_near_viewport(RENDER_KEEP_VIEWPORTS)
        for page_index in list(self._rendered_pages - keep):
            self._unload_page(page_index)
        # Scrolling a failed page out of range resets its retry budget, so a
        # transient failure (file briefly locked, say) doesn't become permanent.
        # A failed page never enters _rendered_pages, so this can't live in
        # _unload_page — that loop would never reach it.
        for page_index in [p for p in self._failed_renders if p not in keep]:
            self._failed_renders.pop(page_index, None)

        if self._search_rects:
            self._redraw_search_overlays()
        if self._paragraph_mode:
            self._refresh_paragraph_markers()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._schedule_visible_render_update()

    # ---------- split-view: active panel indicator ----------
    def set_active_indicator(self, active: bool) -> None:
        """Draw a blue border when this panel is the active one, remove it otherwise."""
        if active:
            self.setStyleSheet("QGraphicsView { border: 2px solid #4A90D9; }")
        else:
            self.setStyleSheet("")

    # ---------- locale ----------
    def set_locale(self, code: str) -> None:
        self._locale = code

    # ---------- translation-panel hover highlight ----------
    def show_hover_highlight(self, text: str) -> None:
        """Temporarily highlight every occurrence of *text* in the visible PDF."""
        self.clear_hover_highlight()
        if self.doc is None:
            return
        text = text.strip()
        if len(text) < MIN_SENTENCE_LENGTH:
            return
        # Search only around the viewport. A hover highlight is meaningless on
        # a page the user cannot see, and scanning the whole document here used
        # to freeze the UI on large PDFs — this runs on the GUI thread.
        pages = sorted(self._page_indices_near_viewport(RENDER_KEEP_VIEWPORTS))
        if not pages:
            return
        results: dict[int, list[fitz.Rect]] = {}
        # Progressively shorter queries: the PDF text layer often differs from
        # the extracted text in whitespace and hyphenation.
        for variant in search_variants(text):
            results = self.doc.search_pages(variant, pages)
            if results:
                break

        scene_rects: list[QRectF] = []
        for page_idx, rects in results.items():
            page = self._pages[page_idx] if page_idx < len(self._pages) else None
            if page is None:
                continue
            scene_rects.extend(self._pdf_rect_to_scene(page, r) for r in rects)
        self._paint_hover_rects(scene_rects)

    def _paint_hover_rects(self, scene_rects: list[QRectF]) -> None:
        """Replace the teal hover overlay with rectangles already in scene space."""
        self.clear_hover_highlight()
        if not scene_rects:
            return
        pen = QPen(Qt.PenStyle.NoPen)
        brush = QBrush(HOVER_COLOR)
        for sr in scene_rects:
            item = self._scene.addRect(sr, pen, brush)
            item.setZValue(15)
            self._hover_items.append(item)
        # Force immediate repaint so the overlay appears right away.
        self.viewport().update()

    def clear_hover_highlight(self) -> None:
        for item in self._hover_items:
            try:
                self._scene.removeItem(item)
            except RuntimeError:
                pass
        self._hover_items.clear()

    # ---------- PDF→panel sentence hover ----------
    def set_translation_context(self, original: str) -> None:
        """Remember the sentences of *original* so hovering the PDF can drive
        the translation panel highlight.

        Locating them is deferred: rects are resolved one page at a time, the
        first time the cursor actually enters that page. Doing it eagerly meant
        one full-document scan per sentence, which froze the UI on long PDFs.
        """
        self._context_sentences = sentences(original) if original else []
        self._sentence_rects_by_page.clear()
        self._last_pdf_hover_sentence = ""

    def _sentence_rects_for_page(self, page_index: int) -> list[tuple[fitz.Rect, str]]:
        """Rects of the context sentences on one page, computed once and cached."""
        if self.doc is None:
            return []   # not cached: the answer would go stale on load()
        cached = self._sentence_rects_by_page.get(page_index)
        if cached is not None:
            return cached
        found: list[tuple[fitz.Rect, str]] = []
        for sentence in self._context_sentences:
            for variant in search_variants(sentence):
                rects = self.doc.search_pages(variant, (page_index,)).get(page_index)
                if rects:
                    found.extend((r, sentence) for r in rects)
                    break
        self._sentence_rects_by_page[page_index] = found
        return found

    def _visible_page_at(self, scene_pt: QPointF) -> PageLayout | None:
        """The visible page containing *scene_pt*, or None.

        Only checks pages near the viewport. This runs on every mouse move, and
        scanning the whole page list would be O(page count) per event — painful
        on a thousand-page document, and pointless since a page off-screen
        cannot be under the cursor.
        """
        for index in self._page_indices_near_viewport(0):
            page = self._pages[index] if index < len(self._pages) else None
            if page is None:
                continue
            if QRectF(
                page.x_offset, page.y_offset, page.width, page.height
            ).contains(scene_pt):
                return page
        return None

    def _update_pdf_hover(self, viewport_pos: QPoint) -> None:
        """Drive the translation-panel highlight based on the cursor position."""
        if not self._context_sentences:
            return
        scene_pt = self.mapToScene(viewport_pos)
        page = self._visible_page_at(scene_pt)
        sentence, rects = "", []
        if page is not None:
            for rect, text in self._sentence_rects_for_page(page.index):
                if self._pdf_rect_to_scene(page, rect).contains(scene_pt):
                    sentence = text
                    break
            if sentence:
                # Reuse the cached rects instead of searching the document
                # again — the hovered sentence may appear more than once.
                rects = [
                    self._pdf_rect_to_scene(page, r)
                    for r, t in self._sentence_rects_for_page(page.index)
                    if t == sentence
                ]

        if not sentence:
            if self._last_pdf_hover_sentence:
                self._last_pdf_hover_sentence = ""
                self.clear_hover_highlight()
                self.pdf_sentence_left.emit()
            return
        if sentence != self._last_pdf_hover_sentence:
            self._last_pdf_hover_sentence = sentence
            self._paint_hover_rects(rects)
            self.pdf_sentence_hovered.emit(sentence)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._last_pdf_hover_sentence:
            self._last_pdf_hover_sentence = ""
            self.clear_hover_highlight()
            self.pdf_sentence_left.emit()
        super().leaveEvent(event)

    # ---------- eye-protection tint ----------
    def set_eye_filter(self, color: QColor | None) -> None:
        self._eye_filter_color = color
        self.viewport().update()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)
        if self._eye_filter_color is None:
            return
        # Paint over the whole viewport (in viewport coords) regardless of
        # zoom/pan so the tint covers black margins too.
        painter.save()
        painter.resetTransform()
        painter.fillRect(self.viewport().rect(), self._eye_filter_color)
        painter.restore()

    # ---------- paragraph translate mode ----------
    def set_paragraph_mode(self, on: bool) -> None:
        if on == self._paragraph_mode:
            return
        self._paragraph_mode = on
        self._refresh_paragraph_markers()

    def is_paragraph_mode(self) -> bool:
        return self._paragraph_mode

    def _refresh_paragraph_markers(self) -> None:
        # Defensive: if scene was cleared elsewhere, removeItem() on a dead
        # wrapper raises RuntimeError. Skip cleanly in that case.
        if self._paragraph_markers:
            for m in self._paragraph_markers:
                try:
                    self._scene.removeItem(m)
                except RuntimeError:
                    pass
            self._paragraph_markers.clear()
        # Active reference is invalid after rebuild; the marker is gone.
        self._active_paragraph_marker = None
        if not self._paragraph_mode or self.doc is None:
            return
        visible_pages = sorted(self._page_indices_near_viewport(RENDER_LOAD_VIEWPORTS))
        if not visible_pages:
            return

        use_merged = self.doc.page_count <= MERGED_PARAGRAPH_PAGE_LIMIT
        # Merged paragraphs require a full-document walk. Keep that richer
        # behavior for ordinary PDFs, but avoid it for very large files.
        if use_merged and not self.doc.has_paragraphs_cached():
            QGuiApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
            try:
                self.doc.merged_paragraphs()
            finally:
                QGuiApplication.restoreOverrideCursor()
        for page_index in visible_pages:
            page = self._pages[page_index]
            if page is None:
                continue
            paragraphs = (
                self.doc.paragraphs_for_page(page.index)
                if use_merged
                else self.doc.paragraphs(page.index)
            )
            for rect, full_text in paragraphs:
                scene_rect = self._pdf_rect_to_scene(page, rect)
                marker = ParagraphMarker(full_text)
                x = max(
                    page.x_offset + 1,
                    scene_rect.left() - ParagraphMarker.SIZE - 2,
                )
                y = scene_rect.top()
                marker.setPos(x, y)
                marker.clicked.connect(self._on_paragraph_clicked)
                self._scene.addItem(marker)
                self._paragraph_markers.append(marker)

    def _on_paragraph_clicked(self, text: str) -> None:
        sender = self.sender()
        if isinstance(sender, ParagraphMarker):
            if (
                self._active_paragraph_marker is not None
                and self._active_paragraph_marker is not sender
            ):
                try:
                    self._active_paragraph_marker.set_active(False)
                except RuntimeError:
                    pass
            sender.set_active(True)
            self._active_paragraph_marker = sender
        self.translate_requested.emit(text)

    # ---------- rotation ----------
    def rotate(self, delta: int = 90) -> None:
        if self.doc is None:
            return
        self.doc.rotate_all(delta)
        # Cached sentence rects are in PDF coordinates, which rotation changes.
        self._sentence_rects_by_page.clear()
        # Wipe selection/search since coordinates changed.
        self._selected_words.clear()
        self._selected_rects_by_page.clear()
        for item in self._selection_items:
            self._scene.removeItem(item)
        self._selection_items.clear()
        self._search_rects.clear()
        for item in self._search_items:
            self._scene.removeItem(item)
        self._search_items.clear()
        # Refit so the rotated page fills the viewport.
        self._zoom = self._compute_fit_zoom()
        self._rebuild()

    # ---------- view modes ----------
    def set_dual_view(self, on: bool) -> None:
        if on == self._dual_view:
            return
        cur = self.current_page()
        self._dual_view = on
        if self.doc is None:
            return
        if on:
            self._current_spread_start = cur - (cur % 2)
        self._zoom = self._compute_fit_zoom()
        self._rebuild()
        self.page_changed.emit(self.current_page())

    def is_dual_view(self) -> bool:
        return self._dual_view

    def _compute_fit_zoom(self) -> float:
        if self.doc is None:
            return self._zoom
        # Always read fresh dimensions from the doc (handles post-rotation correctly).
        pdf_w, pdf_h = self.doc.page_size(0)
        return self._compute_fit_zoom_for(pdf_w, pdf_h)

    def _compute_fit_zoom_for(self, pdf_w: float, pdf_h: float) -> float:
        if pdf_w <= 0 or pdf_h <= 0:
            return self._zoom
        vp_w = max(1, self.viewport().width() - 20)
        vp_h = max(1, self.viewport().height() - 20)
        if self._dual_view:
            z_w = (vp_w - PAGE_GAP) / (pdf_w * 2)
        else:
            z_w = vp_w / pdf_w
        z_h = vp_h / pdf_h
        return max(0.1, min(z_w, z_h))

    # ---------- zoom ----------
    def set_zoom(self, zoom: float) -> None:
        zoom = max(0.2, min(zoom, 6.0))
        if abs(zoom - self._zoom) < 1e-3:
            return
        self._zoom = zoom
        if self.doc is not None:
            self._rebuild()

    def zoom(self) -> float:
        return self._zoom

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * 1.2)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / 1.2)

    def zoom_fit_width(self) -> None:
        """Fit the width of the spread to the viewport."""
        if self.doc is None:
            return
        pdf_w, _ = self.doc.page_size(0)   # fresh from doc, post-rotation safe
        if pdf_w <= 0:
            return
        vp_w = self.viewport().width() - 20
        if self._dual_view:
            self.set_zoom(max(0.05, (vp_w - PAGE_GAP) / (pdf_w * 2)))
        else:
            self.set_zoom(vp_w / pdf_w)

    def zoom_fit_page(self) -> None:
        """Fit the spread so that both width and height are visible."""
        self.set_zoom(self._compute_fit_zoom())

    # ---------- page navigation ----------
    def current_page(self) -> int:
        if self.doc is None or not self._pages:
            return 0
        if self._dual_view:
            return self._current_spread_start
        center = self.mapToScene(self.viewport().rect().center())
        best_idx = 0
        best_d = float("inf")
        for p in self._pages:
            if p is None:
                continue
            cy = p.y_offset + p.height / 2.0
            d = abs(cy - center.y())
            if d < best_d:
                best_d, best_idx = d, p.index
        return best_idx

    def goto_page(self, page_index: int) -> None:
        if self.doc is None or not self._pages:
            return
        page_index = max(0, min(page_index, self.doc.page_count - 1))
        if self._dual_view:
            spread_start = page_index - (page_index % 2)
            if spread_start != self._current_spread_start:
                self._current_spread_start = spread_start
                self._rebuild()
            return
        p = self._pages[page_index]
        if p is None:
            return
        self.centerOn(p.x_offset + p.width / 2.0, p.y_offset + p.height / 2.0)

    def go_next(self) -> None:
        if self.doc is None:
            return
        if self._dual_view:
            new_start = self._current_spread_start + 2
            if new_start < self.doc.page_count:
                self._current_spread_start = new_start
                self._rebuild()
                self.page_changed.emit(self._current_spread_start)
        else:
            self.goto_page(self.current_page() + 1)
            self.page_changed.emit(self.current_page())

    def go_prev(self) -> None:
        if self.doc is None:
            return
        if self._dual_view:
            new_start = max(self._current_spread_start - 2, 0)
            if new_start != self._current_spread_start:
                self._current_spread_start = new_start
                self._rebuild()
                self.page_changed.emit(self._current_spread_start)
        else:
            self.goto_page(self.current_page() - 1)
            self.page_changed.emit(self.current_page())

    # ---------- selection ----------
    def _scene_to_page(self, scene_pt: QPointF) -> tuple[PageLayout, QPointF] | None:
        for p in self._pages:
            if p is None:
                continue
            rect = QRectF(p.x_offset, p.y_offset, p.width, p.height)
            if rect.contains(scene_pt):
                local_x = scene_pt.x() - p.x_offset
                local_y = scene_pt.y() - p.y_offset
                sx = p.pdf_width / p.width if p.width else 1.0
                sy = p.pdf_height / p.height if p.height else 1.0
                return p, QPointF(local_x * sx, local_y * sy)
        return None

    def _pdf_rect_to_scene(self, page: PageLayout, r: fitz.Rect) -> QRectF:
        sx = page.width / page.pdf_width if page.pdf_width else 1.0
        sy = page.height / page.pdf_height if page.pdf_height else 1.0
        return QRectF(
            page.x_offset + r.x0 * sx,
            page.y_offset + r.y0 * sy,
            (r.x1 - r.x0) * sx,
            (r.y1 - r.y0) * sy,
        )

    def mousePressEvent(self, event) -> None:
        # Any click activates this panel (split view support).
        self.panel_activated.emit()
        # Any click while in autoscroll mode exits it.
        if self._autoscroll_anchor is not None:
            self._stop_autoscroll()
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._start_autoscroll(event.pos())
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            # If the click landed on a paragraph marker, let the scene route it
            # to the item (so its mousePressEvent fires) instead of starting
            # a text selection.
            scene_pt = self.mapToScene(event.pos())
            hit = self._scene.itemAt(scene_pt, self.transform())
            if isinstance(hit, ParagraphMarker):
                super().mousePressEvent(event)
                return
            self._clear_selection()
            self._sel_anchor_scene = scene_pt
            self._selecting = True
            event.accept()
            return
        super().mousePressEvent(event)

    # ---------- autoscroll (middle-click joystick) ----------
    def _start_autoscroll(self, viewport_pos: QPoint) -> None:
        self._autoscroll_anchor = QPoint(viewport_pos)
        self._autoscroll_indicator = AutoscrollIndicator(self.viewport())
        half = AutoscrollIndicator.SIZE // 2
        self._autoscroll_indicator.move(viewport_pos.x() - half, viewport_pos.y() - half)
        self._autoscroll_indicator.show()
        self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
        self.setMouseTracking(True)
        self._autoscroll_timer.start()

    def _stop_autoscroll(self) -> None:
        self._autoscroll_timer.stop()
        if self._autoscroll_indicator is not None:
            self._autoscroll_indicator.deleteLater()
            self._autoscroll_indicator = None
        self._autoscroll_anchor = None
        self.viewport().unsetCursor()

    def _tick_autoscroll(self) -> None:
        if self._autoscroll_anchor is None:
            return
        cur = self.viewport().mapFromGlobal(QCursor.pos())
        dx = cur.x() - self._autoscroll_anchor.x()
        dy = cur.y() - self._autoscroll_anchor.y()
        # Dead zone, then roughly quadratic response for smooth speed control.
        DEAD = 10
        dx = self._autoscroll_speed(dx, DEAD)
        dy = self._autoscroll_speed(dy, DEAD)
        if dx:
            hb = self.horizontalScrollBar()
            hb.setValue(hb.value() + dx)
        if dy:
            vb = self.verticalScrollBar()
            vb.setValue(vb.value() + dy)

    @staticmethod
    def _autoscroll_speed(delta: int, dead: int) -> int:
        mag = abs(delta)
        if mag <= dead:
            return 0
        eff = (mag - dead) / 6.0
        eff = eff * eff * 0.06 + eff * 0.4  # gentle acceleration
        return int(eff) if delta > 0 else -int(eff)

    def keyPressEvent(self, event) -> None:
        if self._autoscroll_anchor is not None and event.key() == Qt.Key.Key_Escape:
            self._stop_autoscroll()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Left:
            self.go_prev()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Right:
            self.go_next()
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._selecting and self._sel_anchor_scene is not None:
            pos = self.mapToScene(event.pos())
            self._update_selection(self._sel_anchor_scene, pos)
            event.accept()
            return
        # Passive hover (no button pressed, not autoscrolling) drives the
        # translation-panel sentence highlight.
        if self._autoscroll_anchor is None:
            self._update_pdf_hover(event.pos())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._selecting:
            self._selecting = False
            event.accept()
            text = self.selected_text()
            self.selection_changed.emit(text)
            return
        super().mouseReleaseEvent(event)

    def _clear_selection(self) -> None:
        for item in self._selection_items:
            self._scene.removeItem(item)
        self._selection_items.clear()
        self._selected_words.clear()
        self._selected_rects_by_page.clear()

    def _update_selection(self, anchor: QPointF, cursor: QPointF) -> None:
        """
        Word-based, reading-order selection. Relies on PyMuPDF emitting words in
        paint order, which for well-structured PDFs matches column-aware reading
        order. This naturally respects multi-column layouts and dual-page view.
        """
        self._clear_selection()
        if self.doc is None or not self._pages:
            return

        anchor_page = self._nearest_page(anchor)
        cursor_page = self._nearest_page(cursor)
        if anchor_page is None or cursor_page is None:
            return

        a_idx = self._find_nearest_word(anchor_page, anchor)
        c_idx = self._find_nearest_word(cursor_page, cursor)
        if a_idx is None or c_idx is None:
            return

        # Order endpoints by (page index, word index in reading order).
        a_key = (anchor_page.index, a_idx)
        c_key = (cursor_page.index, c_idx)
        if a_key <= c_key:
            start_page, start_word_idx = anchor_page, a_idx
            end_page, end_word_idx = cursor_page, c_idx
        else:
            start_page, start_word_idx = cursor_page, c_idx
            end_page, end_word_idx = anchor_page, a_idx

        # Only cross pages that share a column with the endpoints (dual-view safety).
        candidates: list[PageLayout] = []
        for p in self._pages:
            if p is None:
                continue
            if p.index < start_page.index or p.index > end_page.index:
                continue
            if self._same_column(p, start_page) or self._same_column(p, end_page):
                candidates.append(p)
        candidates.sort(key=lambda p: p.index)
        if not candidates:
            return

        selected: list[Word] = []
        for i, page in enumerate(candidates):
            words = self.doc.words(page.index)
            if not words:
                continue
            first = start_word_idx if page.index == start_page.index else 0
            last = end_word_idx if page.index == end_page.index else len(words) - 1
            if first > last:
                continue
            selected.extend(words[first : last + 1])

        # Merge consecutive words on the same line into one rect so that the
        # selection looks continuous (covers inter-word gaps).
        line_rects_by_page: dict[int, list[fitz.Rect]] = {}
        buf: list[fitz.Rect] = []
        buf_key: tuple[int, int, int] | None = None

        def flush() -> None:
            if not buf or buf_key is None:
                return
            x0 = min(r.x0 for r in buf)
            y0 = min(r.y0 for r in buf)
            x1 = max(r.x1 for r in buf)
            y1 = max(r.y1 for r in buf)
            line_rects_by_page.setdefault(buf_key[0], []).append(fitz.Rect(x0, y0, x1, y1))

        for w in selected:
            key = (w.page, w.block, w.line)
            if key != buf_key:
                flush()
                buf = []
                buf_key = key
            buf.append(w.rect)
        flush()

        pen = QPen(Qt.PenStyle.NoPen)
        brush = QBrush(SELECTION_COLOR)
        for page_idx, rects in line_rects_by_page.items():
            p = self._pages[page_idx]
            if p is None:
                continue
            for r in rects:
                rect_item = self._scene.addRect(self._pdf_rect_to_scene(p, r), pen, brush)
                rect_item.setZValue(10)
                self._selection_items.append(rect_item)

        self._selected_words = selected
        self._selected_rects_by_page = line_rects_by_page

    def _find_nearest_word(self, page: PageLayout, scene_pt: QPointF) -> int | None:
        """Index of the word closest to a scene point, preferring the same line."""
        if self.doc is None:
            return None
        words = self.doc.words(page.index)
        if not words:
            return None
        sx = page.pdf_width / page.width if page.width else 1.0
        sy = page.pdf_height / page.height if page.height else 1.0
        px = (scene_pt.x() - page.x_offset) * sx
        py = (scene_pt.y() - page.y_offset) * sy

        best, best_score = 0, float("inf")
        for i, w in enumerate(words):
            cx = (w.x0 + w.x1) / 2.0
            cy = (w.y0 + w.y1) / 2.0
            on_line = w.y0 <= py <= w.y1
            # Heavy y-penalty when cursor isn't on the word's line; this keeps
            # selection anchored to the hovered column even when nearest word by
            # pure distance is in an adjacent column.
            y_pen = 0.0 if on_line else abs(cy - py) * 4.0
            score = abs(cx - px) + y_pen
            if score < best_score:
                best, best_score = i, score
        return best

    @staticmethod
    def _same_column(a: PageLayout, b: PageLayout) -> bool:
        overlap = (
            min(a.x_offset + a.width, b.x_offset + b.width)
            - max(a.x_offset, b.x_offset)
        )
        return overlap > min(a.width, b.width) * 0.5

    def _nearest_page(self, pt: QPointF) -> PageLayout | None:
        for p in self._pages:
            if p is None:
                continue
            if (
                p.x_offset <= pt.x() <= p.x_offset + p.width
                and p.y_offset <= pt.y() <= p.y_offset + p.height
            ):
                return p
        best: PageLayout | None = None
        best_d = float("inf")
        for p in self._pages:
            if p is None:
                continue
            cx = p.x_offset + p.width / 2.0
            cy = p.y_offset + p.height / 2.0
            d = (cx - pt.x()) ** 2 + (cy - pt.y()) ** 2
            if d < best_d:
                best, best_d = p, d
        return best

    def selected_text(self) -> str:
        if not self._selected_words:
            return ""
        # Sort by (page, line, word_no), then join with line breaks between lines.
        ws = sorted(
            self._selected_words,
            key=lambda w: (w.page, w.block, w.line, w.word_no),
        )
        out: list[str] = []
        prev_key: tuple[int, int, int] | None = None
        for w in ws:
            key = (w.page, w.block, w.line)
            if prev_key is None:
                out.append(w.text)
            elif key == prev_key:
                out.append(" " + w.text)
            else:
                out.append(" " if key[:2] == prev_key[:2] else "\n")
                out.append(w.text)
            prev_key = key
        return "".join(out).strip()

    # ---------- context menu ----------
    def contextMenuEvent(self, event) -> None:
        L = self._locale
        text = self.selected_text()
        has_sel = bool(self._selected_rects_by_page)
        menu = QMenu(self)

        highlight = QAction(_s(L, "ctx_highlight"), self)
        highlight.setEnabled(has_sel)
        highlight.triggered.connect(lambda: self._apply_markup("highlight"))
        menu.addAction(highlight)

        underline = QAction(_s(L, "ctx_underline"), self)
        underline.setEnabled(has_sel)
        underline.triggered.connect(lambda: self._apply_markup("underline"))
        menu.addAction(underline)

        # Detect highlight/underline under cursor → offer delete.
        scene_pt = self.mapToScene(event.pos())
        page_info = self._scene_to_page(scene_pt)
        if page_info is not None and self.doc is not None:
            page, pdf_pt = page_info
            pdf_xy = (pdf_pt.x(), pdf_pt.y())
            if self.doc.has_annotation_at(page.index, pdf_xy):
                del_act = QAction(_s(L, "ctx_delete_annot"), self)
                del_act.triggered.connect(
                    lambda: self.delete_annotation_requested.emit(page.index, pdf_xy)
                )
                menu.addAction(del_act)

        menu.addSeparator()
        translate = QAction(_s(L, "ctx_translate"), self)
        translate.setEnabled(bool(text))
        translate.triggered.connect(lambda: self.translate_requested.emit(text))
        menu.addAction(translate)

        copy = QAction(_s(L, "ctx_copy"), self)
        copy.setEnabled(bool(text))
        copy.triggered.connect(lambda: QGuiApplication.clipboard().setText(text))
        menu.addAction(copy)

        menu.exec(event.globalPos())

    def _apply_markup(self, kind: str) -> None:
        signal = self.highlight_requested if kind == "highlight" else self.underline_requested
        for page_index, rects in self._selected_rects_by_page.items():
            signal.emit(page_index, rects)

    def rerender_page(self, page_index: int) -> None:
        """Re-render a single page (after annotation changes)."""
        if self.doc is None or page_index >= len(self._page_items):
            return
        item = self._page_items[page_index]
        if item is None:
            # Explicit user-triggered refresh — always worth another attempt
            # even if earlier renders of this page failed.
            self._failed_renders.pop(page_index, None)
            self._ensure_page_rendered(page_index)
            return
        img = self.doc.render_page(page_index, zoom=self._zoom * self._render_scale)
        item.setPixmap(QPixmap.fromImage(img))

    # ---------- search ----------
    def clear_search(self) -> None:
        for item in self._search_items:
            self._scene.removeItem(item)
        self._search_items.clear()
        self._search_rects.clear()
        self._active_search_index = -1

    def apply_search(self, results: dict[int, list[fitz.Rect]]) -> int:
        self.clear_search()
        for page_index in sorted(results.keys()):
            for r in results[page_index]:
                self._search_rects.append((page_index, r))
        if self._search_rects:
            self.set_active_search(0)
        return len(self._search_rects)

    def _redraw_search_overlays(self) -> None:
        for item in self._search_items:
            self._scene.removeItem(item)
        self._search_items.clear()
        pen = QPen(Qt.PenStyle.NoPen)
        pages_to_draw = self._page_indices_near_viewport(RENDER_LOAD_VIEWPORTS)
        if 0 <= self._active_search_index < len(self._search_rects):
            pages_to_draw.add(self._search_rects[self._active_search_index][0])
        for i, (pi, rect) in enumerate(self._search_rects):
            if pi not in pages_to_draw:
                continue
            if pi >= len(self._pages) or self._pages[pi] is None:
                continue
            color = SEARCH_ACTIVE_COLOR if i == self._active_search_index else SEARCH_COLOR
            item = self._scene.addRect(
                self._pdf_rect_to_scene(self._pages[pi], rect),  # type: ignore[arg-type]
                pen,
                QBrush(color),
            )
            item.setZValue(9)
            self._search_items.append(item)

    def set_active_search(self, idx: int) -> None:
        if not self._search_rects:
            return
        idx %= len(self._search_rects)
        self._active_search_index = idx
        page_index, rect = self._search_rects[idx]
        # Make sure the containing page/spread is rendered.
        if self._dual_view:
            target_spread = page_index - (page_index % 2)
            if target_spread != self._current_spread_start:
                self._current_spread_start = target_spread
                self._rebuild()  # redraws overlays at the end
        page = self._pages[page_index]
        if page is not None:
            self.centerOn(self._pdf_rect_to_scene(page, rect).center())
        self._update_visible_pages()

    def search_next(self) -> None:
        if self._search_rects:
            self.set_active_search(self._active_search_index + 1)

    def search_prev(self) -> None:
        if self._search_rects:
            self.set_active_search(self._active_search_index - 1)

    # ---------- wheel / zoom with Ctrl ----------
    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            elif delta < 0:
                self.zoom_out()
            event.accept()
            return

        # Advance spread only if the whole spread fits the viewport (dual-view fit).
        # Otherwise scroll normally so the user can pan a zoomed-in view.
        if self._dual_view and self._scene_fits_viewport():
            self._wheel_accum += event.angleDelta().y()
            threshold = 120
            while self._wheel_accum <= -threshold:
                self._wheel_accum += threshold
                self.go_next()
            while self._wheel_accum >= threshold:
                self._wheel_accum -= threshold
                self.go_prev()
            event.accept()
            return
        super().wheelEvent(event)

    def _scene_fits_viewport(self) -> bool:
        sr = self._scene.sceneRect()
        vp = self.viewport()
        return sr.height() <= vp.height() + 1 and sr.width() <= vp.width() + 1
