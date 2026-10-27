/**
 * PDF viewer core — the web counterpart of pdf_reader/pdf_view.py.
 *
 * The desktop version drives a QGraphicsView: it lays pages out in a scene,
 * renders them into pixmaps on a thread pool, and unloads the ones that scroll
 * far away. This does the same with DOM nodes and PDF.js: one absolutely-sized
 * `.page` element per page, canvases painted lazily as they approach the
 * viewport and released once they are well behind it, so a 400-page thesis
 * does not sit in memory as 400 bitmaps.
 *
 * Text selection is the one place the web version is simpler: PDF.js can lay
 * transparent, correctly positioned text over the canvas, so the browser's own
 * selection does the job that pdf_view.py implements by hit-testing word boxes.
 */

import * as pdfjsLib from '../vendor/pdf.min.mjs';
import { blocksForPage, mergeParagraphs, indexByPage } from './paragraphs.js';
import { normalizeWhitespace, searchVariants } from './text-utils.js';

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  '../vendor/pdf.worker.min.mjs',
  import.meta.url,
).href;

/** Zoom steps, matching the desktop reader's Ctrl+ / Ctrl- ladder. */
const ZOOM_STEPS = [
  0.25, 0.33, 0.5, 0.67, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0,
];
const MIN_SCALE = ZOOM_STEPS[0];
const MAX_SCALE = ZOOM_STEPS[ZOOM_STEPS.length - 1];

/** How far outside the viewport pages are painted / kept, in viewport heights. */
const RENDER_MARGIN = 1.0;
const KEEP_MARGIN = 3.0;

/** Gap between pages, in CSS pixels. Mirrors PdfView's PAGE_GAP. */
const PAGE_GAP = 16;

/**
 * Above this page count, paragraph markers stop merging across pages.
 *
 * Merging is a whole-document walk: every page has to be read before the first
 * badge can appear. That is a fair trade for a paper, and a bad one for a
 * 600-page book, so large documents fall back to per-page blocks, which are
 * computed for one page at a time and appear instantly. Same limit the desktop
 * reader uses.
 */
const MERGED_PARAGRAPH_PAGE_LIMIT = 300;

/** Diameter of a paragraph badge in CSS pixels, and its gap from the text. */
const BADGE_SIZE = 20;
const BADGE_GAP = 2;

export class PdfViewer extends EventTarget {
  /**
   * @param {HTMLElement} container  Scrolling element that holds the pages.
   */
  constructor(container) {
    super();
    this.container = container;
    this.pagesEl = document.createElement('div');
    this.pagesEl.className = 'pages';
    this.container.appendChild(this.pagesEl);

    /** @type {import('../vendor/pdf.min.mjs').PDFDocumentProxy|null} */
    this.doc = null;
    this.pageCount = 0;
    this.scale = 1.0;
    this.currentPage = 0;
    this.fitMode = 'page'; // 'page' | 'width' | null (manual zoom)

    /** Per-page state: element refs, render task, cached text. */
    this.pages = [];

    /** Search state. */
    this.searchQuery = '';
    this.matches = []; // [{page, rects: [[x0,y0,x1,y1], …]}]
    this.activeMatch = -1;

    /** Extra highlight overlay driven from the translation panel. */
    this.hoverRects = [];

    /** Per-page text, built on demand: page index → {items, text, map}. */
    this._pageTextCache = new Map();
    this._textIndex = null; // set once every page has been read (search needs that)
    this._paragraphIndex = null;
    this._paragraphMode = false;
    this._activeBadge = null;

    /** Tooltip on each paragraph badge; the app sets it from the UI locale. */
    this.badgeLabel = 'Bu paragrafı çevir';
    this._scrollRaf = 0;
    this._generation = 0;

    this._onScroll = this._onScroll.bind(this);
    this.container.addEventListener('scroll', this._onScroll, { passive: true });
    this._resizeObserver = new ResizeObserver(() => this._onResize());
    this._resizeObserver.observe(this.container);
  }

  // ------------------------------------------------------------------ //
  // Document lifecycle
  // ------------------------------------------------------------------ //

  /**
   * Open a PDF from raw bytes.
   *
   * @param {ArrayBuffer|Uint8Array} data
   * @param {string} [name]  File name, for the title bar.
   */
  async open(data, name = '') {
    await this.close();

    const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
    const task = pdfjsLib.getDocument({
      data: bytes,
      // CMaps and the base-14 font data are what make CJK and unembedded-font
      // PDFs render correctly rather than as blank boxes.
      cMapUrl: new URL('../vendor/cmaps/', import.meta.url).href,
      cMapPacked: true,
      standardFontDataUrl: new URL('../vendor/standard_fonts/', import.meta.url).href,
      isEvalSupported: false,
    });
    this.doc = await task.promise;
    this.pageCount = this.doc.numPages;
    this.name = name;

    // Page geometry at scale 1, needed before anything can be laid out.
    this.pageSizes = [];
    for (let i = 0; i < this.pageCount; i++) {
      const page = await this.doc.getPage(i + 1);
      const vp = page.getViewport({ scale: 1 });
      this.pageSizes.push({ width: vp.width, height: vp.height });
    }

    this._buildLayout();
    this.fitPage();
    // fitPage() only paints as a side effect of changing the scale; when the
    // computed fit happens to equal the current scale it returns early, so the
    // first pages are requested explicitly here.
    this._updateVisiblePages();
    this.dispatchEvent(
      new CustomEvent('load', { detail: { pageCount: this.pageCount, name } }),
    );
    this._emitPageChange(0);
    return this.doc;
  }

  /** Release the document and every rendered page. */
  async close() {
    this._generation++;
    for (const page of this.pages) this._unloadPage(page);
    this.pages = [];
    this.pagesEl.textContent = '';
    this._pageTextCache.clear();
    this._textIndex = null;
    this._paragraphIndex = null;
    this._activeBadge = null;
    this.matches = [];
    this.activeMatch = -1;
    this.searchQuery = '';
    if (this.doc) {
      const doc = this.doc;
      this.doc = null;
      await doc.destroy();
    }
    this.pageCount = 0;
  }

  destroy() {
    this.container.removeEventListener('scroll', this._onScroll);
    this._resizeObserver.disconnect();
    return this.close();
  }

  // ------------------------------------------------------------------ //
  // Layout
  // ------------------------------------------------------------------ //

  _buildLayout() {
    this.pagesEl.textContent = '';
    this.pages = this.pageSizes.map((size, index) => {
      const wrap = document.createElement('div');
      wrap.className = 'page-wrap';
      wrap.dataset.page = String(index);

      const page = document.createElement('div');
      page.className = 'page';

      const canvas = document.createElement('canvas');
      canvas.className = 'page-canvas';

      const textLayer = document.createElement('div');
      textLayer.className = 'textLayer';

      const overlay = document.createElement('div');
      overlay.className = 'overlay-layer';

      const paraLayer = document.createElement('div');
      paraLayer.className = 'para-layer';

      const spinner = document.createElement('div');
      spinner.className = 'page-spinner';

      page.append(canvas, textLayer, overlay, paraLayer, spinner);
      wrap.appendChild(page);
      this.pagesEl.appendChild(wrap);

      return {
        index,
        size,
        wrap,
        el: page,
        canvas,
        textLayer,
        overlay,
        paraLayer,
        rendered: false,
        // Set synchronously the moment a render starts. `renderTask` cannot
        // do this job: it only exists after the first await, and two scroll
        // ticks can both get past the guard in that gap and then start two
        // render() calls on one canvas, which PDF.js refuses.
        busy: false,
        // Bumped whenever the page is unloaded, so a render still in flight
        // knows its canvas was reclaimed and declines to commit.
        epoch: 0,
        // Set after a genuine failure, so the retry below cannot spin on a
        // page that will never render.
        failed: false,
        renderTask: null,
        textLayerInstance: null,
      };
    });
    this._applyScaleToLayout();
  }

  _applyScaleToLayout() {
    for (const page of this.pages) {
      const w = Math.floor(page.size.width * this.scale);
      const h = Math.floor(page.size.height * this.scale);
      page.el.style.width = `${w}px`;
      page.el.style.height = `${h}px`;
      page.el.style.setProperty('--scale-factor', String(this.scale));
      page.wrap.style.marginBottom = `${PAGE_GAP}px`;
    }
  }

  // ------------------------------------------------------------------ //
  // Zoom
  // ------------------------------------------------------------------ //

  /**
   * Set the zoom level, keeping the page currently under the viewport's top
   * edge in place.
   *
   * @param {number} scale
   * @param {boolean} [fromFit]  Internal: preserve the active fit mode.
   */
  setScale(scale, fromFit = false) {
    const next = Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
    if (Math.abs(next - this.scale) < 0.001) return;

    const anchor = this.currentPage;
    const before = this.pages[anchor]?.wrap.offsetTop ?? 0;
    const offsetInPage = this.container.scrollTop - before;
    const ratio = next / this.scale;

    this.scale = next;
    if (!fromFit) this.fitMode = null;

    this._generation++;
    for (const page of this.pages) this._unloadPage(page);
    this._applyScaleToLayout();

    const after = this.pages[anchor]?.wrap.offsetTop ?? 0;
    this.container.scrollTop = after + offsetInPage * ratio;

    this._redrawOverlays();
    this._updateVisiblePages();
    this.dispatchEvent(
      new CustomEvent('scalechange', { detail: { scale: this.scale } }),
    );
  }

  zoomIn() {
    const next = ZOOM_STEPS.find((z) => z > this.scale + 0.001);
    this.setScale(next ?? MAX_SCALE);
  }

  zoomOut() {
    const lower = ZOOM_STEPS.filter((z) => z < this.scale - 0.001);
    this.setScale(lower.length ? lower[lower.length - 1] : MIN_SCALE);
  }

  /** Fit a whole page in the viewport — the desktop's Ctrl+0. */
  fitPage() {
    if (!this.pages.length) return;
    const size = this.pageSizes[this.currentPage] ?? this.pageSizes[0];
    const availableW = this.container.clientWidth - 48;
    const availableH = this.container.clientHeight - 32;
    this.fitMode = 'page';
    this.setScale(
      Math.min(availableW / size.width, availableH / size.height),
      true,
    );
  }

  /** Fit the page width to the viewport. */
  fitWidth() {
    if (!this.pages.length) return;
    const size = this.pageSizes[this.currentPage] ?? this.pageSizes[0];
    const availableW = this.container.clientWidth - 48;
    this.fitMode = 'width';
    this.setScale(availableW / size.width, true);
  }

  _onResize() {
    if (!this.pages.length) return;
    if (this.fitMode === 'page') this.fitPage();
    else if (this.fitMode === 'width') this.fitWidth();
    else this._updateVisiblePages();
  }

  // ------------------------------------------------------------------ //
  // Navigation
  // ------------------------------------------------------------------ //

  /** @param {number} index 0-based page index. */
  gotoPage(index) {
    const target = Math.min(this.pageCount - 1, Math.max(0, index));
    const page = this.pages[target];
    if (!page) return;
    this.container.scrollTop = page.wrap.offsetTop - 8;
    this._emitPageChange(target);
  }

  nextPage() {
    this.gotoPage(this.currentPage + 1);
  }

  prevPage() {
    this.gotoPage(this.currentPage - 1);
  }

  _onScroll() {
    if (this._scrollRaf) return;
    this._scrollRaf = requestAnimationFrame(() => {
      this._scrollRaf = 0;
      this._updateVisiblePages();
      this._updateCurrentPage();
    });
  }

  _updateCurrentPage() {
    // The page occupying the most of the viewport is "the" current page —
    // the same rule PdfView.current_page() applies to the scene rect.
    const top = this.container.scrollTop;
    const bottom = top + this.container.clientHeight;
    let best = this.currentPage;
    let bestArea = 0;
    for (const page of this.pages) {
      const pTop = page.wrap.offsetTop;
      const pBottom = pTop + page.wrap.offsetHeight;
      if (pBottom < top || pTop > bottom) continue;
      const area = Math.min(pBottom, bottom) - Math.max(pTop, top);
      if (area > bestArea) {
        bestArea = area;
        best = page.index;
      }
    }
    if (best !== this.currentPage) this._emitPageChange(best);
  }

  _emitPageChange(index) {
    this.currentPage = index;
    this.dispatchEvent(
      new CustomEvent('pagechange', {
        detail: { page: index, pageCount: this.pageCount },
      }),
    );
  }

  // ------------------------------------------------------------------ //
  // Lazy rendering
  // ------------------------------------------------------------------ //

  _updateVisiblePages() {
    if (!this.doc) return;
    const viewH = this.container.clientHeight;
    const top = this.container.scrollTop;
    const renderTop = top - viewH * RENDER_MARGIN;
    const renderBottom = top + viewH * (1 + RENDER_MARGIN);
    const keepTop = top - viewH * KEEP_MARGIN;
    const keepBottom = top + viewH * (1 + KEEP_MARGIN);

    for (const page of this.pages) {
      const pTop = page.wrap.offsetTop;
      const pBottom = pTop + page.wrap.offsetHeight;

      if (pBottom >= renderTop && pTop <= renderBottom) {
        this._renderPage(page);
      } else if (pBottom < keepTop || pTop > keepBottom) {
        this._unloadPage(page);
      }
    }
  }

  async _renderPage(page) {
    // `busy` is set before the first await on purpose. Guarding on
    // `renderTask` alone is not enough: it is only assigned once the page
    // object has been fetched, and a second scroll tick arriving during that
    // await would pass the guard and start a second render() on the same
    // canvas, which PDF.js rejects outright.
    if (page.rendered || page.busy || page.failed) return;
    page.busy = true;

    const generation = this._generation;
    const epoch = page.epoch;
    const stale = () => generation !== this._generation || epoch !== page.epoch;
    page.el.classList.add('is-loading');

    try {
      const pdfPage = await this.doc.getPage(page.index + 1);
      if (stale()) return;

      const viewport = pdfPage.getViewport({ scale: this.scale });
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const canvas = page.canvas;
      const ctx = canvas.getContext('2d', { alpha: false });

      canvas.width = Math.floor(viewport.width * dpr);
      canvas.height = Math.floor(viewport.height * dpr);
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;

      const task = pdfPage.render({
        canvasContext: ctx,
        viewport,
        transform: dpr === 1 ? null : [dpr, 0, 0, dpr, 0, 0],
      });
      page.renderTask = task;
      await task.promise;
      page.renderTask = null;
      if (stale()) return;

      // Transparent, positioned text on top of the bitmap — this is what makes
      // native browser selection work over the page.
      const textContent = await pdfPage.getTextContent();
      if (stale()) return;
      page.textLayer.textContent = '';
      const layer = new pdfjsLib.TextLayer({
        textContentSource: textContent,
        container: page.textLayer,
        viewport,
      });
      await layer.render();
      page.textLayerInstance = layer;

      page.rendered = true;
      page.el.classList.remove('is-loading');
      this._drawOverlayFor(page);
      await this._drawParagraphMarkersFor(page);
    } catch (err) {
      page.renderTask = null;
      page.el.classList.remove('is-loading');
      // A cancelled render is routine — the page scrolled away or the zoom
      // changed — and must not reach the user as an error.
      if (err?.name === 'RenderingCancelledException' || stale()) return;
      page.failed = true;
      this.dispatchEvent(
        new CustomEvent('renderfailed', {
          detail: { page: page.index, error: err },
        }),
      );
    } finally {
      page.busy = false;
      // A render abandoned because the zoom changed or the page was unloaded
      // leaves a blank page behind. Now that the canvas is free, let the
      // scheduler decide whether this page is still wanted.
      if (!page.rendered && !page.failed && this.doc) {
        requestAnimationFrame(() => this._updateVisiblePages());
      }
    }
  }

  _unloadPage(page) {
    // Tell any render still in flight that its canvas has been reclaimed.
    page.epoch++;
    page.failed = false; // a fresh attempt deserves a fresh verdict
    if (page.renderTask) {
      try {
        page.renderTask.cancel();
      } catch {
        /* already finished */
      }
      page.renderTask = null;
    }
    if (page.textLayerInstance) {
      try {
        page.textLayerInstance.cancel();
      } catch {
        /* not started */
      }
      page.textLayerInstance = null;
    }
    if (page.rendered) {
      page.canvas.width = 0;
      page.canvas.height = 0;
      page.textLayer.textContent = '';
      page.overlay.textContent = '';
      page.paraLayer.textContent = '';
    }
    page.rendered = false;
  }

  /** Re-render every currently visible page — used after annotations change. */
  refresh() {
    this._generation++;
    for (const page of this.pages) this._unloadPage(page);
    this._updateVisiblePages();
  }

  // ------------------------------------------------------------------ //
  // Text index — feeds search, paragraph mode and hover highlighting
  // ------------------------------------------------------------------ //

  /**
   * Build (once) a per-page index of positioned text runs plus a normalised
   * string with a character→run map, so a match found in the string can be
   * turned back into rectangles on the page.
   *
   * @param {(p: {done:number,total:number}) => void} [onProgress]
   */
  async ensureTextIndex(onProgress) {
    if (this._textIndex) return this._textIndex;
    const index = [];
    for (let i = 0; i < this.pageCount; i++) {
      index.push(await this.pageText(i));
      onProgress?.({ done: i + 1, total: this.pageCount });
    }
    this._textIndex = index;
    return index;
  }

  /**
   * Text of a single page, extracted once and cached.
   *
   * Kept per-page so paragraph badges can appear on the page being read
   * without first walking the whole document.
   */
  async pageText(pageIndex) {
    const cached = this._pageTextCache.get(pageIndex);
    if (cached) return cached;

    const pdfPage = await this.doc.getPage(pageIndex + 1);
    const viewport = pdfPage.getViewport({ scale: 1 });
    const content = await pdfPage.getTextContent();

    const items = [];
    for (const item of content.items) {
      if (typeof item.str !== 'string') continue;
      const t = pdfjsLib.Util.transform(viewport.transform, item.transform);
      const height = Math.hypot(t[1], t[3]) || item.height || 10;
      items.push({
        str: item.str,
        hasEOL: !!item.hasEOL,
        x: t[4],
        y: t[5] - height,
        w: item.width,
        h: height,
      });
    }

    const entry = { items, ...buildSearchString(items) };
    this._pageTextCache.set(pageIndex, entry);
    return entry;
  }

  /** Positioned text runs for one page (requires the page to have been read). */
  getTextRuns(pageIndex) {
    return this._pageTextCache.get(pageIndex)?.items ?? [];
  }

  /**
   * Merged paragraphs for the whole document, indexed by page. Mirrors
   * `PdfDocument.paragraphs_for_page`, including the cross-page merging.
   */
  async ensureParagraphIndex(onProgress) {
    if (this._paragraphIndex) return this._paragraphIndex;
    await this.ensureTextIndex(onProgress);
    const pageBlocks = this._textIndex.map((p) => blocksForPage(p.items));
    this._paragraphIndex = indexByPage(mergeParagraphs(pageBlocks));
    return this._paragraphIndex;
  }

  /** Whether this document is small enough to merge paragraphs across pages. */
  get usesMergedParagraphs() {
    return this.pageCount <= MERGED_PARAGRAPH_PAGE_LIMIT;
  }

  /**
   * Paragraphs to badge on one page, as `[{rect, text}, …]`.
   *
   * For an ordinary document the text is the *merged* paragraph, so a badge on
   * a paragraph continuing from the previous column or page still translates
   * the whole thing. For a very large one it is the on-page block alone.
   */
  async paragraphsForPage(pageIndex) {
    if (this.usesMergedParagraphs) {
      const index = await this.ensureParagraphIndex();
      return index.get(pageIndex) ?? [];
    }
    const { items } = await this.pageText(pageIndex);
    return blocksForPage(items).map((block) => ({
      rect: [block.x0, block.y0, block.x1, block.y1],
      text: block.text,
    }));
  }

  // ------------------------------------------------------------------ //
  // Search
  // ------------------------------------------------------------------ //

  /**
   * Find every occurrence of `query` in the document and highlight it.
   *
   * @param {string} query
   * @param {(p:{done:number,total:number})=>void} [onProgress]
   * @returns {Promise<number>} number of matches
   */
  async search(query, onProgress) {
    const needle = normalizeWhitespace(query).toLowerCase();
    this.searchQuery = needle;
    this.matches = [];
    this.activeMatch = -1;

    if (!needle) {
      this._redrawOverlays();
      return 0;
    }

    await this.ensureTextIndex(onProgress);

    // Matching without spaces also finds words the text layer has broken up,
    // which is most ligatures and every hyphenated line end.
    const compactNeedle = compactify(needle);
    if (!compactNeedle) {
      this._redrawOverlays();
      return 0;
    }

    for (let pageIndex = 0; pageIndex < this._textIndex.length; pageIndex++) {
      const entry = this._textIndex[pageIndex];
      let from = 0;
      for (;;) {
        const at = entry.compact.indexOf(compactNeedle, from);
        if (at === -1) break;
        this.matches.push({
          page: pageIndex,
          rects: rectsForCompactRange(entry, at, at + compactNeedle.length),
        });
        from = at + compactNeedle.length;
      }
    }

    this._redrawOverlays();
    if (this.matches.length) this.setActiveMatch(0);
    return this.matches.length;
  }

  setActiveMatch(index) {
    if (!this.matches.length) return;
    const count = this.matches.length;
    this.activeMatch = ((index % count) + count) % count;
    const match = this.matches[this.activeMatch];
    this._scrollToRects(match.page, match.rects);
    this._redrawOverlays();
    this.dispatchEvent(
      new CustomEvent('searchstate', {
        detail: { index: this.activeMatch, total: count },
      }),
    );
  }

  nextMatch() {
    this.setActiveMatch(this.activeMatch + 1);
  }

  prevMatch() {
    this.setActiveMatch(this.activeMatch - 1);
  }

  clearSearch() {
    this.searchQuery = '';
    this.matches = [];
    this.activeMatch = -1;
    this._redrawOverlays();
  }

  // ------------------------------------------------------------------ //
  // Hover highlight (translation panel → PDF)
  // ------------------------------------------------------------------ //

  /**
   * Highlight `text` wherever it appears near the viewport — the web
   * equivalent of `PdfView.show_hover_highlight`. Only nearby pages are
   * searched: this runs on mouse movement, so it must stay cheap.
   *
   * @param {string} text
   */
  async showHoverHighlight(text) {
    if (!this.doc || !text) return;
    const pages = this._pagesNearViewport();
    const found = [];

    outer: for (const variant of searchVariants(text)) {
      const needle = compactify(variant);
      if (needle.length < 8) continue;
      for (const pageIndex of pages) {
        const entry = await this.pageText(pageIndex);
        if (!entry) continue;
        const at = entry.compact.indexOf(needle);
        if (at === -1) continue;
        found.push({
          page: pageIndex,
          rects: rectsForCompactRange(entry, at, at + needle.length),
        });
        break outer;
      }
    }

    this.hoverRects = found;
    this._redrawOverlays();
  }

  clearHoverHighlight() {
    if (!this.hoverRects.length) return;
    this.hoverRects = [];
    this._redrawOverlays();
  }

  _pagesNearViewport() {
    const top = this.container.scrollTop - this.container.clientHeight;
    const bottom =
      this.container.scrollTop + this.container.clientHeight * 2;
    const out = [];
    for (const page of this.pages) {
      const pTop = page.wrap.offsetTop;
      const pBottom = pTop + page.wrap.offsetHeight;
      if (pBottom >= top && pTop <= bottom) out.push(page.index);
    }
    return out;
  }

  // ------------------------------------------------------------------ //
  // Overlays
  // ------------------------------------------------------------------ //

  _redrawOverlays() {
    for (const page of this.pages) {
      if (page.rendered) this._drawOverlayFor(page);
    }
  }

  _drawOverlayFor(page) {
    const overlay = page.overlay;
    overlay.textContent = '';
    const scale = this.scale;

    this.matches.forEach((match, i) => {
      if (match.page !== page.index) return;
      const active = i === this.activeMatch;
      for (const rect of match.rects) {
        overlay.appendChild(
          makeBox(rect, scale, active ? 'hl hl-active' : 'hl'),
        );
      }
    });

    for (const hover of this.hoverRects) {
      if (hover.page !== page.index) continue;
      for (const rect of hover.rects) {
        overlay.appendChild(makeBox(rect, scale, 'hl hl-hover'));
      }
    }
  }

  async _drawParagraphMarkersFor(page) {
    if (!this._paragraphMode || !this.doc) return;

    const entries = await this.paragraphsForPage(page.index);
    if (!this._paragraphMode) return; // toggled off while we were reading
    page.paraLayer.textContent = '';

    for (const entry of entries) {
      const [x0, y0] = entry.rect;
      const badge = makeParagraphBadge(this.badgeLabel);
      const { left, top } = badgePosition(x0, y0, this.scale);
      badge.style.left = `${left}px`;
      badge.style.top = `${top}px`;

      // Hovering is the earliest honest signal that this paragraph is the one
      // wanted; starting then usually has the answer ready by the click.
      badge.addEventListener('mouseenter', () => {
        this.dispatchEvent(
          new CustomEvent('paragraphhovered', { detail: { text: entry.text } }),
        );
      });

      badge.addEventListener('click', (event) => {
        event.stopPropagation();
        event.preventDefault();
        this._setActiveBadge(badge);
        this.dispatchEvent(
          new CustomEvent('paragraphpicked', { detail: { text: entry.text } }),
        );
      });

      page.paraLayer.appendChild(badge);
    }
  }

  /** Only one badge reads as selected at a time, as on the desktop. */
  _setActiveBadge(badge) {
    if (this._activeBadge && this._activeBadge !== badge) {
      this._activeBadge.classList.remove('is-active');
    }
    badge.classList.add('is-active');
    this._activeBadge = badge;
  }

  /**
   * Toggle paragraph-translate mode (the desktop's Ctrl+P): a badge at the
   * start of every paragraph translates the whole block, following it across
   * column and page breaks.
   */
  async setParagraphMode(on, onProgress) {
    this._paragraphMode = on;
    this.pagesEl.classList.toggle('paragraph-mode', on);

    if (!on) {
      for (const page of this.pages) page.paraLayer.textContent = '';
      this._activeBadge = null;
      return;
    }

    // Reading the whole document is only needed for cross-page merging.
    if (this.usesMergedParagraphs) await this.ensureParagraphIndex(onProgress);

    await Promise.all(
      this.pages
        .filter((page) => page.rendered)
        .map((page) => this._drawParagraphMarkersFor(page)),
    );
  }

  /** Whether paragraph-translate mode is on. */
  isParagraphMode() {
    return this._paragraphMode;
  }

  _scrollToRects(pageIndex, rects) {
    const page = this.pages[pageIndex];
    if (!page || !rects.length) return;
    const top = Math.min(...rects.map((r) => r[1])) * this.scale;
    const target = page.wrap.offsetTop + top - this.container.clientHeight / 3;
    this.container.scrollTo({ top: Math.max(0, target), behavior: 'smooth' });
  }
}

// ---------------------------------------------------------------------- //
// Helpers
// ---------------------------------------------------------------------- //

/**
 * Flatten positioned runs into one whitespace-normalised string plus a map
 * from each character back to (run index, offset within the run).
 *
 * Exported for the test suite, which exercises it against a real PDF without
 * a browser.
 */
export function buildSearchString(items) {
  let text = '';
  const map = [];
  items.forEach((item, i) => {
    const str = item.str;
    for (let c = 0; c < str.length; c++) {
      if (/\s/.test(str[c])) {
        if (text.endsWith(' ')) continue;
        text += ' ';
      } else {
        text += str[c];
      }
      map.push({ item: i, offset: c });
    }
    if (item.hasEOL && !text.endsWith(' ')) {
      text += ' ';
      map.push({ item: i, offset: str.length });
    }
  });

  // A second view with every space removed, and the way back to the first.
  //
  // Whitespace is the one thing a PDF text layer cannot be trusted about.
  // "modified" set with an fi ligature arrives as three runs — `modi`, `fi`,
  // `ed` — which this function concatenates to "modified", while the paragraph
  // builder puts a space between runs and produces "modi fi ed". Comparing
  // those two fails, and a hover highlight then falls back to the opening
  // words and stops mid-sentence. Comparing without spaces at all makes the
  // question "are these the same words", which is what was being asked.
  let compact = '';
  const compactMap = [];
  for (let i = 0; i < text.length; i++) {
    if (IGNORED_IN_COMPACT.test(text[i])) continue;
    compact += text[i].toLowerCase();
    compactMap.push(i);
  }

  return { text, map, compact, compactMap };
}

/**
 * Characters dropped when comparing text to a page: whitespace, and the
 * hyphens a typesetter puts at a line end. Without the hyphen, "recon-" and
 * "struction" on the next line never match the word the reader sees.
 */
const IGNORED_IN_COMPACT = /[\s\-­‐‑]/;

/** Strip whitespace, hyphens and case, to compare against a page's `compact`. */
export function compactify(text) {
  return text.replace(/[\s\-­‐‑]+/g, '').toLowerCase();
}

/**
 * Rectangles covering characters [start, end) of a page's search string.
 *
 * Character positions inside a run are interpolated from the run's width. PDF
 * text runs carry no per-glyph metrics, so this is an approximation — accurate
 * enough for a highlight box, and it degrades gracefully on proportional
 * fonts because runs are usually short.
 */
/**
 * Rectangles for a match found in a page's space-free `compact` string.
 *
 * `compactMap` carries each compacted character back to its position in the
 * spaced text, from where the existing run map takes over.
 */
export function rectsForCompactRange(entry, start, end) {
  const { compactMap, items, map } = entry;
  if (!compactMap.length || end <= start) return [];
  const from = compactMap[Math.min(start, compactMap.length - 1)];
  const to = compactMap[Math.min(end - 1, compactMap.length - 1)] + 1;
  return rectsForRange(items, map, from, to);
}

export function rectsForRange(items, map, start, end) {
  /** @type {Map<number, [number, number]>} run index → [firstChar, lastChar] */
  const spans = new Map();
  for (let i = start; i < end && i < map.length; i++) {
    const { item, offset } = map[i];
    const existing = spans.get(item);
    if (existing) existing[1] = offset + 1;
    else spans.set(item, [offset, offset + 1]);
  }

  const rects = [];
  for (const [index, [from, to]] of spans) {
    const item = items[index];
    if (!item || !item.w) continue;
    const length = item.str.length || 1;
    const x0 = item.x + (item.w * from) / length;
    const x1 = item.x + (item.w * Math.min(to, length)) / length;
    if (x1 <= x0) continue;
    rects.push([x0, item.y, x1, item.y + item.h]);
  }
  return rects;
}

/**
 * Where a paragraph badge sits, in page-relative CSS pixels.
 *
 * It hangs in the margin to the left of the paragraph, but never off the page:
 * a paragraph flush with the left edge would otherwise push its badge outside
 * the clipped page element and out of sight. Same clamp as ParagraphMarker in
 * pdf_view.py.
 *
 * @param {number} x0     Paragraph left edge, PDF points.
 * @param {number} y0     Paragraph top edge, PDF points.
 * @param {number} scale  Current zoom.
 */
export function badgePosition(x0, y0, scale) {
  return {
    left: Math.max(1, x0 * scale - BADGE_SIZE - BADGE_GAP),
    top: y0 * scale,
  };
}

/**
 * A paragraph badge: gold serif T on a deep indigo disc.
 *
 * Redrawn from ParagraphMarker.paint() in pdf_view.py — same 20px circle and
 * the same three bars forming the T (crossbar, stem, foot), so the web reader
 * looks like the desktop one rather than merely behaving like it.
 */
function makeParagraphBadge(label) {
  const badge = document.createElement('button');
  badge.type = 'button';
  badge.className = 'para-badge';
  badge.title = label;
  badge.setAttribute('aria-label', label);
  badge.innerHTML =
    '<svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">' +
    '<rect x="4" y="4.5" width="12" height="2"/>' +
    '<rect x="9" y="6.5" width="2" height="7.5"/>' +
    '<rect x="7" y="14" width="6" height="1.5"/>' +
    '</svg>';
  return badge;
}

function makeBox(rect, scale, className) {
  const [x0, y0, x1, y1] = rect;
  const box = document.createElement('div');
  box.className = className;
  box.style.left = `${x0 * scale}px`;
  box.style.top = `${y0 * scale}px`;
  box.style.width = `${(x1 - x0) * scale}px`;
  box.style.height = `${(y1 - y0) * scale}px`;
  return box;
}
