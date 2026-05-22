"""PyMuPDF wrapper: open, render, search, and add highlight annotations."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from PyQt6.QtGui import QImage


# A block ends a paragraph if it ends with sentence-final punctuation
# (optionally followed by closing quotes/brackets).
_SENT_END_PAT = re.compile(r'[.!?…][\'"”’\)\]]*$')
# Hyphen at the end of a word indicates a soft line/column/page break that
# splits the word. Joining should drop the hyphen.
_HYPHEN_PAT = re.compile(r'\w-$', re.UNICODE)


@dataclass
class Word:
    """A single word on a page with its bounding box (PDF coordinates)."""
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    block: int
    line: int
    word_no: int

    @property
    def rect(self) -> fitz.Rect:
        return fitz.Rect(self.x0, self.y0, self.x1, self.y1)


class PdfDocument:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.doc = fitz.open(self.path)
        self._page_size_cache: dict[int, tuple[float, float]] = {}
        self._words_cache: dict[int, list[Word]] = {}
        self._paragraphs_cache: list[dict] | None = None
        self._paragraphs_by_page: dict[int, list[tuple[fitz.Rect, str]]] | None = None

    def close(self) -> None:
        if self.doc is not None:
            self.doc.close()
            self.doc = None  # type: ignore[assignment]

    @property
    def page_count(self) -> int:
        return self.doc.page_count

    def page_size(self, page_index: int) -> tuple[float, float]:
        if page_index in self._page_size_cache:
            return self._page_size_cache[page_index]
        page = self.doc[page_index]
        size = (page.rect.width, page.rect.height)
        self._page_size_cache[page_index] = size
        return size

    def render_page(self, page_index: int, zoom: float = 1.0) -> QImage:
        page = self.doc[page_index]
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        fmt = QImage.Format.Format_RGB888
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
        return img.copy()  # detach from pix buffer

    def words(self, page_index: int) -> list[Word]:
        if page_index in self._words_cache:
            return self._words_cache[page_index]
        page = self.doc[page_index]
        raw = page.get_text("words")
        result = [
            Word(page_index, w[0], w[1], w[2], w[3], w[4], w[5], w[6], w[7])
            for w in raw
        ]
        self._words_cache[page_index] = result
        return result

    def paragraphs(self, page_index: int) -> list[tuple[fitz.Rect, str]]:
        """Return [(rect, text), ...] for each substantial text block on a page."""
        page = self.doc[page_index]
        blocks = page.get_text("blocks")
        out: list[tuple[fitz.Rect, str]] = []
        for x0, y0, x1, y1, text, _block_no, block_type in blocks:
            if block_type != 0:  # 0 = text, 1 = image
                continue
            clean = " ".join(text.split()).strip()
            if len(clean) < 30:  # skip page numbers, captions, headers
                continue
            out.append((fitz.Rect(x0, y0, x1, y1), clean))
        return out

    def has_paragraphs_cached(self) -> bool:
        return self._paragraphs_cache is not None

    def merged_paragraphs(self) -> list[dict]:
        """
        Walk all pages in reading order and merge blocks that belong to the same
        paragraph but are split across columns or pages. Each result item:
            {"text": <full merged text>, "blocks": [(page_idx, fitz.Rect), ...]}
        Markers can be placed on every block so the user finds the same translation
        wherever a continued paragraph appears.
        """
        if self._paragraphs_cache is not None:
            return self._paragraphs_cache

        result: list[dict] = []
        current: dict | None = None
        # Heuristic threshold: a "current" block of at least this many characters
        # that doesn't end with a sentence terminator is treated as a paragraph
        # continuing into the next block. Shorter blocks (likely headings or
        # captions) stay standalone to avoid swallowing them into paragraphs.
        PARAGRAPH_LIKE = 100

        for pi in range(self.page_count):
            for rect, text in self.paragraphs(pi):
                if not text:
                    continue
                is_cont = False
                if current is not None:
                    tail = current["text"].rstrip()
                    if _HYPHEN_PAT.search(tail):
                        is_cont = True  # word split across the boundary
                    elif not _SENT_END_PAT.search(tail):
                        # Mid-sentence ending → this is a real continuation if
                        # the previous block already looks paragraph-sized. We
                        # no longer require the next block to start with a
                        # lowercase letter; cross-page continuations frequently
                        # begin a new sentence on the new page.
                        if len(current["text"]) >= PARAGRAPH_LIKE:
                            is_cont = True

                if is_cont and current is not None:
                    if _HYPHEN_PAT.search(current["text"].rstrip()):
                        # Drop the hyphen and join without a space.
                        current["text"] = (
                            current["text"].rstrip().rstrip("-") + text.lstrip()
                        )
                    else:
                        current["text"] = current["text"].rstrip() + " " + text.lstrip()
                    current["blocks"].append((pi, rect))
                else:
                    if current is not None:
                        result.append(current)
                    current = {"text": text, "blocks": [(pi, rect)]}

        if current is not None:
            result.append(current)

        self._paragraphs_cache = result
        self._paragraphs_by_page = None  # rebuilt lazily
        return result

    def paragraphs_for_page(
        self, page_index: int
    ) -> list[tuple[fitz.Rect, str]]:
        """Return [(rect, full_paragraph_text), ...] visible on a single page.
        Each entry is one block of a (possibly multi-page) paragraph; full_text
        is the merged text. Used for placing per-block translate markers."""
        if self._paragraphs_by_page is None:
            idx: dict[int, list[tuple[fitz.Rect, str]]] = {}
            for para in self.merged_paragraphs():
                full = para["text"]
                for pi, rect in para["blocks"]:
                    idx.setdefault(pi, []).append((rect, full))
            self._paragraphs_by_page = idx
        return self._paragraphs_by_page.get(page_index, [])

    def search(self, query: str) -> dict[int, list[fitz.Rect]]:
        """Return {page_index: [rects]} for all matches."""
        results: dict[int, list[fitz.Rect]] = {}
        if not query:
            return results
        for i in range(self.page_count):
            page = self.doc[i]
            rects = page.search_for(query, quads=False)
            if rects:
                results[i] = rects
        return results

    # Annotation kinds we manage.
    _ANNOT_TYPES: tuple = (fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_UNDERLINE)

    def add_highlight(
        self,
        page_index: int,
        rects: list[fitz.Rect],
        color: tuple[float, float, float] = (1.0, 0.92, 0.23),
    ) -> int | None:
        return self._add_markup(page_index, rects, color, "highlight")

    def add_underline(
        self,
        page_index: int,
        rects: list[fitz.Rect],
        color: tuple[float, float, float] = (1.0, 0.92, 0.23),
    ) -> int | None:
        return self._add_markup(page_index, rects, color, "underline")

    def _add_markup(
        self,
        page_index: int,
        rects: list[fitz.Rect],
        color: tuple[float, float, float],
        kind: str,
    ) -> int | None:
        if not rects:
            return None
        page = self.doc[page_index]
        quads = [r.quad for r in rects]
        if kind == "underline":
            annot = page.add_underline_annot(quads)
        else:
            annot = page.add_highlight_annot(quads)
        annot.set_colors(stroke=color)
        annot.update()
        return annot.xref

    def has_annotation_at(
        self, page_index: int, pdf_point: tuple[float, float]
    ) -> bool:
        page = self.doc[page_index]
        pt = fitz.Point(*pdf_point)
        for annot in page.annots(types=self._ANNOT_TYPES):
            if annot.rect.contains(pt):
                return True
        return False

    def delete_annotation_at(
        self, page_index: int, pdf_point: tuple[float, float]
    ) -> dict | None:
        """Delete the topmost highlight/underline covering a point."""
        page = self.doc[page_index]
        pt = fitz.Point(*pdf_point)
        for annot in page.annots(types=self._ANNOT_TYPES):
            if not annot.rect.contains(pt):
                continue
            kind = (
                "highlight"
                if annot.type[0] == fitz.PDF_ANNOT_HIGHLIGHT
                else "underline"
            )
            rects = self._extract_rects_from_annot(annot)
            stroke = (annot.colors or {}).get("stroke")
            color = tuple(stroke) if stroke else (1.0, 0.92, 0.23)
            xref = annot.xref
            page.delete_annot(annot)
            return {"kind": kind, "xref": xref, "rects": rects, "color": color}
        return None

    def remove_annotation_by_xref(self, page_index: int, xref: int) -> bool:
        page = self.doc[page_index]
        for annot in page.annots():
            if annot.xref == xref:
                page.delete_annot(annot)
                return True
        return False

    @staticmethod
    def _extract_rects_from_annot(annot) -> list[fitz.Rect]:
        """Reconstruct per-line rects from a highlight annotation's quad vertices."""
        verts = list(annot.vertices or [])
        rects: list[fitz.Rect] = []
        for i in range(0, len(verts), 4):
            pts = verts[i : i + 4]
            if len(pts) != 4:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            rects.append(fitz.Rect(min(xs), min(ys), max(xs), max(ys)))
        if not rects:
            rects.append(fitz.Rect(annot.rect))
        return rects

    def rotate_all(self, delta_degrees: int) -> None:
        """Rotate every page by `delta_degrees` (multiple of 90). Caches invalidated."""
        for i in range(self.page_count):
            page = self.doc[i]
            page.set_rotation((page.rotation + delta_degrees) % 360)
        self._page_size_cache.clear()
        self._words_cache.clear()
        self._paragraphs_cache = None
        self._paragraphs_by_page = None

    def save_incremental(self) -> None:
        """Save annotations back to original file."""
        self.doc.save(self.path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)

    def save_as(self, new_path: str | Path) -> None:
        """Save a clean, compressed copy of the document to a new path."""
        self.doc.save(str(Path(new_path)), garbage=4, deflate=True)
