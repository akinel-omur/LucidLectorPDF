"""Bookmark / outline panel — displays a PDF's table of contents."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class BookmarkPanel(QWidget):
    """Left-side panel that shows a PDF's table of contents tree."""

    page_requested = pyqtSignal(int)  # 0-based page index

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Tree
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(14)
        self._tree.setAnimated(True)
        self._tree.setStyleSheet("""
            QTreeWidget {
                background: #1e1e1e;
                color: #ccc;
                border: none;
                font-size: 13px;
            }
            QTreeWidget::item {
                padding: 3px 4px;
            }
            QTreeWidget::item:hover {
                background: #2a2a2a;
            }
            QTreeWidget::item:selected {
                background: #2d5a8e;
                color: #fff;
            }
            QTreeWidget::branch {
                background: #1e1e1e;
            }
        """)
        self._tree.itemClicked.connect(self._on_clicked)
        lay.addWidget(self._tree)

        # Empty-state label (shown when the PDF has no TOC)
        self._empty = QLabel("Bu belgede yer işareti yok")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.setStyleSheet(
            "color: #555; padding: 24px; background: #1e1e1e; font-size: 13px;"
        )
        lay.addWidget(self._empty)

        self._show_state(empty=True)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def set_document(self, doc: object | None) -> None:
        """Load the TOC from *doc* (a PdfDocument) or clear if None."""
        self._tree.clear()
        if doc is None:
            self._show_state(empty=True)
            return

        try:
            toc = doc.doc.get_toc()   # [[level, title, page_1based], ...]
        except Exception:             # noqa: BLE001
            toc = []

        if not toc:
            self._show_state(empty=True)
            return

        self._show_state(empty=False)

        # Build the tree — keep a stack of (level, item) to find parents
        stack: list[tuple[int, QTreeWidgetItem]] = []
        for entry in toc:
            level: int = entry[0]
            title: str = (entry[1] or "").strip() or "—"
            page_1: int = entry[2]
            page_0 = max(page_1 - 1, 0)   # convert to 0-based

            item = QTreeWidgetItem([title])
            item.setData(0, Qt.ItemDataRole.UserRole, page_0)
            item.setToolTip(0, f"{title}  —  s. {max(page_1, 1)}")

            # Pop stack until we find the parent level
            while stack and stack[-1][0] >= level:
                stack.pop()

            if stack:
                stack[-1][1].addChild(item)
            else:
                self._tree.addTopLevelItem(item)

            stack.append((level, item))

        self._tree.expandAll()

    def highlight_current(self, page: int) -> None:
        """Select the deepest bookmark whose page is ≤ *page* (0-based).

        Called whenever the active PDF panel changes page so the tree
        tracks the reader's position.
        """
        if not self._tree.isVisible():
            return

        # Collect (page, item) pairs in document order via DFS
        items: list[tuple[int, QTreeWidgetItem]] = []
        self._collect(self._tree.invisibleRootItem(), items)

        best: QTreeWidgetItem | None = None
        for item_page, item in items:
            if item_page <= page:
                best = item
            # items are in ascending page order; stop early once we've gone past
            elif item_page > page:
                break

        if best is None:
            return
        self._tree.blockSignals(True)
        self._tree.setCurrentItem(best)
        self._tree.scrollToItem(best, QTreeWidget.ScrollHint.PositionAtCenter)
        self._tree.blockSignals(False)

    def set_locale(self, code: str) -> None:
        """Update the empty-state message for *code*."""
        from .i18n import s as _s
        self._empty.setText(_s(code, "bookmarks_empty"))

    def set_eye_filter(self, color: object | None) -> None:
        """Not used visually; kept for API symmetry with other panels."""

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #
    def _show_state(self, *, empty: bool) -> None:
        self._tree.setVisible(not empty)
        self._empty.setVisible(empty)

    def _on_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        page = item.data(0, Qt.ItemDataRole.UserRole)
        if page is not None:
            self.page_requested.emit(int(page))

    def _collect(
        self,
        parent: QTreeWidgetItem,
        out: list[tuple[int, QTreeWidgetItem]],
    ) -> None:
        for i in range(parent.childCount()):
            child = parent.child(i)
            p = child.data(0, Qt.ItemDataRole.UserRole)
            if p is not None:
                out.append((int(p), child))
            self._collect(child, out)
