/**
 * Application wiring — the web counterpart of pdf_reader/main_window.py.
 *
 * Holds no PDF logic of its own: it connects the viewer, the translator and
 * the DOM, exactly as MainWindow connects PdfView, Translator and the Qt
 * widgets. Preferences persist in localStorage the way the desktop version
 * uses QSettings.
 */

import { PdfViewer } from './viewer.js';
import { BookmarkPanel } from './bookmarks.js';
import { Translator, LANGUAGES } from './translator.js';
import { s, setLocale, applyLocale, getLocale } from './i18n.js';
import { sentences, sentenceIndexOf } from './text-utils.js';

/** Eye-protection tints, straight from EYE_FILTER_COLORS in main_window.py. */
const EYE_FILTERS = {
  off: null,
  hafif: 'rgba(255, 210, 140, 0.35)',
  warm: 'rgba(255, 220, 150, 0.45)',
  sepia: 'rgba(245, 220, 180, 0.55)',
  yesil: 'rgba(180, 220, 180, 0.45)',
  pembe: 'rgba(255, 200, 210, 0.45)',
  gece: 'rgba(255, 190, 140, 0.60)',
  koyu_gece: 'rgba(255, 170, 110, 0.75)',
  karartma: 'rgba(140, 140, 140, 0.55)',
};

const PREFS_KEY = 'lucidlector.prefs';

const $ = (id) => document.getElementById(id);

const el = {
  viewer: $('viewer'),
  dropzone: $('dropzone'),
  fileInput: $('file-input'),
  btnOpen: $('btn-open'),
  grpPages: $('grp-pages'),
  grpZoom: $('grp-zoom'),
  grpTools: $('grp-tools'),
  btnPrev: $('btn-prev'),
  btnNext: $('btn-next'),
  pageInput: $('page-input'),
  pageTotal: $('page-total'),
  btnZoomIn: $('btn-zoom-in'),
  btnZoomOut: $('btn-zoom-out'),
  btnFitPage: $('btn-fit-page'),
  btnFitWidth: $('btn-fit-width'),
  zoomLevel: $('zoom-level'),
  btnFind: $('btn-find'),
  btnBookmarks: $('btn-bookmarks'),
  sidebar: $('sidebar'),
  bookmarkTree: $('bookmark-tree'),
  btnBmExpand: $('btn-bm-expand'),
  btnBmCollapse: $('btn-bm-collapse'),
  btnParagraph: $('btn-paragraph'),
  btnFullscreen: $('btn-fullscreen'),
  btnPanel: $('btn-panel'),
  eyeSelect: $('eye-select'),
  eyeTint: $('eye-tint'),
  searchBar: $('search-bar'),
  searchInput: $('search-input'),
  searchStatus: $('search-status'),
  btnSearchPrev: $('btn-search-prev'),
  btnSearchNext: $('btn-search-next'),
  btnSearchClose: $('btn-search-close'),
  panel: $('panel'),
  panelResizer: $('panel-resizer'),
  panelEmpty: $('panel-empty'),
  panelContent: $('panel-content'),
  textOriginal: $('text-original'),
  textTranslated: $('text-translated'),
  sourceSelect: $('source-select'),
  targetSelect: $('target-select'),
  btnCopy: $('btn-copy'),
  floatingTranslate: $('floating-translate'),
  toast: $('toast'),
  progress: $('progress'),
  progressBar: $('progress-bar'),
  progressLabel: $('progress-label'),
};

const viewer = new PdfViewer(el.viewer);
const bookmarks = new BookmarkPanel(el.bookmarkTree);
const translator = new Translator();

const state = {
  hasDocument: false,
  paragraphMode: false,
  lastOriginal: '',
  lastSentences: [],
  hoverTimer: 0,
  hoverIndex: -1,
};

// -------------------------------------------------------------- preferences

function loadPrefs() {
  try {
    return JSON.parse(localStorage.getItem(PREFS_KEY)) || {};
  } catch {
    return {};
  }
}

function savePrefs(patch) {
  const next = { ...loadPrefs(), ...patch };
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(next));
  } catch {
    /* private mode — preferences simply do not persist */
  }
}

// -------------------------------------------------------------------- chrome

function toast(message, isError = false) {
  el.toast.textContent = message;
  el.toast.classList.toggle('is-error', isError);
  el.toast.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => {
    el.toast.hidden = true;
  }, isError ? 6000 : 3000);
}

function showProgress(label, done, total) {
  el.progress.hidden = false;
  const pct = total ? Math.round((done / total) * 100) : 0;
  el.progressBar.style.setProperty('--p', `${pct}%`);
  el.progressLabel.textContent = `${label} ${pct}%`;
}

function hideProgress() {
  el.progress.hidden = true;
}

function setDocumentChromeVisible(visible) {
  for (const group of [el.grpPages, el.grpZoom, el.grpTools]) {
    group.hidden = !visible;
  }
}

// ------------------------------------------------------------ opening a PDF

async function openFile(file) {
  if (!file) return;
  const isPdf =
    file.type === 'application/pdf' || /\.pdf$/i.test(file.name || '');
  if (!isPdf) {
    toast(s('err_not_pdf'), true);
    return;
  }

  try {
    el.dropzone.hidden = true;
    showProgress(s('loading'), 0, 1);
    const buffer = await file.arrayBuffer();
    await viewer.open(buffer, file.name);
    hideProgress();

    state.hasDocument = true;
    setDocumentChromeVisible(true);
    el.pageTotal.textContent = s('of_pages', { n: viewer.pageCount });
    el.pageInput.max = String(viewer.pageCount);
    document.title = `${file.name} — LucidLector`;
    el.viewer.focus();

    // Show the table of contents when the document has one — for a textbook
    // it is the main way around, and an empty panel is just lost width.
    const hasOutline = await bookmarks.setDocument(viewer.doc);
    setSidebarVisible(hasOutline && loadPrefs().sidebar !== false);
    bookmarks.highlightCurrent(viewer.currentPage);

    // Paragraph badges are the point of the reader, so they are on unless the
    // user turned them off — the preference carries across documents.
    await applyParagraphMode(loadPrefs().paragraph !== false);
  } catch (err) {
    hideProgress();
    el.dropzone.hidden = state.hasDocument;
    const message = /password/i.test(String(err?.message))
      ? s('err_encrypted')
      : s('err_open', { err: err?.message || err });
    toast(message, true);
  }
}

el.btnOpen.addEventListener('click', () => el.fileInput.click());
el.dropzone.addEventListener('click', () => el.fileInput.click());
el.fileInput.addEventListener('change', (e) => {
  openFile(e.target.files?.[0]);
  e.target.value = '';
});

['dragenter', 'dragover'].forEach((type) =>
  window.addEventListener(type, (e) => {
    e.preventDefault();
    el.dropzone.classList.add('is-over');
    if (!state.hasDocument) el.dropzone.hidden = false;
  }),
);
['dragleave', 'drop'].forEach((type) =>
  window.addEventListener(type, (e) => {
    e.preventDefault();
    if (type === 'drop' || e.relatedTarget === null) {
      el.dropzone.classList.remove('is-over');
    }
  }),
);
window.addEventListener('drop', (e) => {
  const file = e.dataTransfer?.files?.[0];
  if (file) openFile(file);
  else if (state.hasDocument) el.dropzone.hidden = true;
});

// ----------------------------------------------------------------- viewer UI

viewer.addEventListener('pagechange', (e) => {
  el.pageInput.value = String(e.detail.page + 1);
  if (!el.sidebar.hidden) bookmarks.highlightCurrent(e.detail.page);
});

viewer.addEventListener('scalechange', (e) => {
  el.zoomLevel.textContent = `${Math.round(e.detail.scale * 100)}%`;
});

viewer.addEventListener('renderfailed', (e) => {
  toast(s('err_open', { err: e.detail.error?.message || 'render' }), true);
});

viewer.addEventListener('paragraphpicked', (e) => {
  translateText(e.detail.text);
});

// Warm the cache while the pointer rests on a badge. Debounced so sweeping
// the mouse across a page of badges does not fire a request per badge.
let prefetchTimer = 0;
viewer.addEventListener('paragraphhovered', (e) => {
  const { text } = e.detail;
  clearTimeout(prefetchTimer);
  prefetchTimer = setTimeout(() => translator.prefetch(text), 150);
});

// ---------------------------------------------------------------- bookmarks

function setSidebarVisible(visible) {
  el.sidebar.hidden = !visible;
  el.btnBookmarks.classList.toggle('is-active', visible);
  savePrefs({ sidebar: visible });
  if (visible && state.hasDocument) bookmarks.highlightCurrent(viewer.currentPage);
}

el.btnBookmarks.addEventListener('click', () => {
  if (!state.hasDocument) return;
  if (el.sidebar.hidden && !bookmarks.hasOutline) {
    toast(s('bookmarks_empty'));
    return;
  }
  setSidebarVisible(el.sidebar.hidden);
});

el.btnBmExpand.addEventListener('click', () => bookmarks.expandAll());
el.btnBmCollapse.addEventListener('click', () => bookmarks.collapseAll());

bookmarks.addEventListener('pagerequested', (e) => {
  viewer.gotoPage(e.detail.page);
  el.viewer.focus();
});

el.btnPrev.addEventListener('click', () => viewer.prevPage());
el.btnNext.addEventListener('click', () => viewer.nextPage());
el.pageInput.addEventListener('change', () => {
  const n = Number(el.pageInput.value);
  if (Number.isFinite(n)) viewer.gotoPage(n - 1);
});

el.btnZoomIn.addEventListener('click', () => viewer.zoomIn());
el.btnZoomOut.addEventListener('click', () => viewer.zoomOut());
el.btnFitPage.addEventListener('click', () => viewer.fitPage());
el.btnFitWidth.addEventListener('click', () => viewer.fitWidth());

// Ctrl+wheel zooms, like the desktop reader's wheelEvent.
el.viewer.addEventListener(
  'wheel',
  (e) => {
    if (!e.ctrlKey || !state.hasDocument) return;
    e.preventDefault();
    if (e.deltaY < 0) viewer.zoomIn();
    else viewer.zoomOut();
  },
  { passive: false },
);

// -------------------------------------------------------------- eye filters

function applyEyeFilter(mode) {
  const color = EYE_FILTERS[mode];
  el.eyeTint.style.background = color || 'transparent';
  el.eyeSelect.value = mode;
  savePrefs({ eye: mode });
}

el.eyeSelect.addEventListener('change', () => applyEyeFilter(el.eyeSelect.value));

// -------------------------------------------------------------- full screen

el.btnFullscreen.addEventListener('click', toggleFullscreen);

function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen?.();
}

// ------------------------------------------------------------------- search

function openSearch() {
  if (!state.hasDocument) return;
  el.searchBar.hidden = false;
  el.btnFind.classList.add('is-active');
  el.searchInput.focus();
  el.searchInput.select();
}

function closeSearch() {
  el.searchBar.hidden = true;
  el.btnFind.classList.remove('is-active');
  el.searchStatus.textContent = '';
  viewer.clearSearch();
  el.viewer.focus();
}

el.btnFind.addEventListener('click', () =>
  el.searchBar.hidden ? openSearch() : closeSearch(),
);
el.btnSearchClose.addEventListener('click', closeSearch);
el.btnSearchNext.addEventListener('click', () => viewer.nextMatch());
el.btnSearchPrev.addEventListener('click', () => viewer.prevMatch());

let searchDebounce = 0;
el.searchInput.addEventListener('input', () => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(runSearch, 250);
});

el.searchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    if (viewer.matches.length) {
      e.shiftKey ? viewer.prevMatch() : viewer.nextMatch();
    } else {
      runSearch();
    }
  } else if (e.key === 'Escape') {
    closeSearch();
  }
});

async function runSearch() {
  const query = el.searchInput.value.trim();
  if (!query) {
    viewer.clearSearch();
    el.searchStatus.textContent = '';
    return;
  }
  const count = await viewer.search(query, ({ done, total }) => {
    if (total > 12) showProgress(s('loading'), done, total);
  });
  hideProgress();
  el.searchStatus.textContent = count
    ? s('search_count', { i: viewer.activeMatch + 1, n: count })
    : s('search_none');
}

viewer.addEventListener('searchstate', (e) => {
  el.searchStatus.textContent = s('search_count', {
    i: e.detail.index + 1,
    n: e.detail.total,
  });
});

// -------------------------------------------------------------- translation

function setPanelVisible(visible) {
  el.panel.hidden = !visible;
  el.panelResizer.hidden = !visible;
  el.btnPanel.classList.toggle('is-active', visible);
  savePrefs({ panel: visible });
}

el.btnPanel.addEventListener('click', () => setPanelVisible(el.panel.hidden));

// ------------------------------------------------------- panel resize handle

const PANEL_MIN = 260;
const PANEL_DEFAULT = 380; // matches --panel-w in css/app.css
const PANEL_MAX_RATIO = 0.7; // never let the panel crowd the page out entirely

/** Clamp to the window so a width saved on a wide screen stays usable. */
function clampPanelWidth(px) {
  const max = Math.max(PANEL_MIN, Math.round(window.innerWidth * PANEL_MAX_RATIO));
  return Math.round(Math.min(max, Math.max(PANEL_MIN, px)));
}

function setPanelWidth(px, { persist = true } = {}) {
  const width = clampPanelWidth(px);
  document.documentElement.style.setProperty('--panel-w', `${width}px`);
  el.panelResizer.setAttribute('aria-valuenow', String(width));
  if (persist) savePrefs({ panelWidth: width });
  // Re-fitting the page is not needed here: the viewer watches its own
  // container with a ResizeObserver and re-runs the active fit mode.
  return width;
}

let dragPointerId = null;

el.panelResizer.addEventListener('pointerdown', (e) => {
  if (e.button !== 0) return;
  dragPointerId = e.pointerId;
  el.panelResizer.setPointerCapture(e.pointerId);
  el.panelResizer.classList.add('is-dragging');
  document.body.classList.add('is-resizing');
  e.preventDefault();
});

el.panelResizer.addEventListener('pointermove', (e) => {
  if (e.pointerId !== dragPointerId) return;
  // The panel is flush with the right edge, so its width is simply whatever
  // remains to the right of the pointer.
  setPanelWidth(window.innerWidth - e.clientX, { persist: false });
});

function endPanelDrag(e) {
  if (e.pointerId !== dragPointerId) return;
  dragPointerId = null;
  el.panelResizer.releasePointerCapture?.(e.pointerId);
  el.panelResizer.classList.remove('is-dragging');
  document.body.classList.remove('is-resizing');
  savePrefs({ panelWidth: Math.round(el.panel.getBoundingClientRect().width) });
}

el.panelResizer.addEventListener('pointerup', endPanelDrag);
el.panelResizer.addEventListener('pointercancel', endPanelDrag);

// Double-click restores the default, the usual escape hatch after a bad drag.
el.panelResizer.addEventListener('dblclick', () => setPanelWidth(PANEL_DEFAULT));

// Keyboard resizing, since the handle is focusable.
el.panelResizer.addEventListener('keydown', (e) => {
  const step = e.shiftKey ? 48 : 16;
  const current = el.panel.getBoundingClientRect().width;
  if (e.key === 'ArrowLeft') {
    e.preventDefault();
    setPanelWidth(current + step);
  } else if (e.key === 'ArrowRight') {
    e.preventDefault();
    setPanelWidth(current - step);
  } else if (e.key === 'Home') {
    e.preventDefault();
    setPanelWidth(PANEL_DEFAULT);
  }
});

window.addEventListener('resize', () => {
  if (el.panel.hidden) return;
  setPanelWidth(el.panel.getBoundingClientRect().width, { persist: false });
});

el.targetSelect.addEventListener('change', () => {
  translator.setTargetLanguage(el.targetSelect.value);
  savePrefs({ target: el.targetSelect.value });
  if (state.lastOriginal) translateText(state.lastOriginal);
});

el.sourceSelect.addEventListener('change', () => {
  translator.setSourceLanguage(el.sourceSelect.value);
  savePrefs({ source: el.sourceSelect.value });
  if (state.lastOriginal) translateText(state.lastOriginal);
});

el.btnCopy.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(el.textTranslated.textContent);
    el.btnCopy.textContent = s('btn_copied');
    setTimeout(() => {
      el.btnCopy.textContent = s('btn_copy');
    }, 1500);
  } catch {
    toast('Pano erişimi reddedildi', true);
  }
});

/**
 * Render text as hoverable sentence spans, so pointing at a sentence in the
 * panel can highlight it in the PDF — the web version of the event-filter
 * machinery in translation_popup.py.
 */
function renderSentences(container, text, { mapToOriginal = false } = {}) {
  container.textContent = '';
  const parts = sentences(text, 1);
  if (!parts.length) {
    container.textContent = text;
    return parts;
  }
  parts.forEach((sentence, index) => {
    const span = document.createElement('span');
    span.className = 'sentence';
    span.textContent = sentence + ' ';
    span.dataset.index = String(index);
    span.dataset.mapped = mapToOriginal ? '1' : '0';
    container.appendChild(span);
  });
  return parts;
}

/**
 * Tint one sentence in the original, its counterpart in the translation, and
 * the matching text in the page — all three at once.
 *
 * Pointing at a sentence is a question about *that* sentence, so all three
 * places that show it should answer. Highlighting only the box under the
 * cursor, which is what a plain `:hover` rule does, leaves the reader to find
 * the counterpart themselves — exactly the work the panel exists to save.
 *
 * The original drives the pairing: `highlight_sentence` in
 * translation_popup.py takes the index in the original and clamps it to the
 * translation's range, since a translator may merge or split sentences.
 *
 * @param {number} originalIndex
 */
function highlightSentencePair(originalIndex) {
  const originalSpans = el.textOriginal.querySelectorAll('.sentence');
  const translatedSpans = el.textTranslated.querySelectorAll('.sentence');

  clearSentencePair({ keepPdf: true });

  originalSpans[originalIndex]?.classList.add('is-hover');
  if (translatedSpans.length) {
    const paired = Math.min(originalIndex, translatedSpans.length - 1);
    translatedSpans[paired]?.classList.add('is-hover');
  }

  const sentence = state.lastSentences[originalIndex];
  if (sentence) viewer.showHoverHighlight(sentence);
}

function clearSentencePair({ keepPdf = false } = {}) {
  document
    .querySelectorAll('.sentence.is-hover')
    .forEach((span) => span.classList.remove('is-hover'));
  if (!keepPdf) viewer.clearHoverHighlight();
}

/** Which sentence of the original a hovered span corresponds to. */
function originalIndexFor(span) {
  const index = Number(span.dataset.index);
  if (span.dataset.mapped !== '1') return index;

  // Translation sentence counts rarely match the original's, so the index is
  // mapped proportionally — the same trick translation_popup.py uses when the
  // hover starts on the translated side.
  const translatedCount =
    el.textTranslated.querySelectorAll('.sentence').length || 1;
  const originalCount = state.lastSentences.length || 1;
  return Math.min(
    originalCount - 1,
    Math.round((index / translatedCount) * originalCount),
  );
}

function handleSentenceHover(event) {
  const span = event.target.closest?.('.sentence');
  clearTimeout(state.hoverTimer);

  if (!span) {
    state.hoverTimer = setTimeout(() => clearSentencePair(), 180);
    return;
  }

  const index = originalIndexFor(span);
  if (index === state.hoverIndex) return; // same sentence, nothing to redo
  state.hoverIndex = index;
  highlightSentencePair(index);
}

el.textOriginal.addEventListener('mousemove', handleSentenceHover);
el.textTranslated.addEventListener('mousemove', handleSentenceHover);
[el.textOriginal, el.textTranslated].forEach((box) =>
  box.addEventListener('mouseleave', () => {
    clearTimeout(state.hoverTimer);
    state.hoverIndex = -1;
    state.hoverTimer = setTimeout(() => clearSentencePair(), 180);
  }),
);

async function translateText(raw) {
  const text = raw.trim();
  if (!text) return;

  setPanelVisible(true);
  el.panelEmpty.hidden = true;
  el.panelContent.hidden = false;

  state.lastOriginal = text;
  state.lastSentences = renderSentences(el.textOriginal, text);
  state.hoverIndex = -1;
  clearSentencePair();

  el.textTranslated.classList.add('is-busy');
  el.textTranslated.textContent = s('translating');

  try {
    const result = await translator.translate(text, ({ done, total }) => {
      if (total > 1) showProgress(s('translating'), done, total);
    });
    hideProgress();
    if (result === null) return; // superseded by a newer selection
    el.textTranslated.classList.remove('is-busy');
    renderSentences(el.textTranslated, result, { mapToOriginal: true });
  } catch (err) {
    hideProgress();
    el.textTranslated.classList.remove('is-busy');
    el.textTranslated.textContent = '';
    const message = String(err?.message || err);
    let notice;
    if (/\b429\b|too many/i.test(message)) notice = s('translate_busy');
    else if (/limit|quota/i.test(message)) notice = s('translate_limit');
    else notice = s('translate_error', { err: message });
    toast(notice, true);
  }
}

// Selecting text in the page offers a translate button next to the selection.
document.addEventListener('mouseup', (e) => {
  if (e.target.closest?.('#floating-translate')) return;
  setTimeout(showTranslateButtonForSelection, 0);
});

function showTranslateButtonForSelection() {
  const selection = window.getSelection();
  const text = selection?.toString().trim() ?? '';
  const insideViewer =
    selection?.anchorNode &&
    el.viewer.contains(
      selection.anchorNode.nodeType === 1
        ? selection.anchorNode
        : selection.anchorNode.parentElement,
    );

  if (!text || text.length < 2 || !insideViewer) {
    el.floatingTranslate.hidden = true;
    return;
  }

  const rect = selection.getRangeAt(0).getBoundingClientRect();
  el.floatingTranslate.hidden = false;
  el.floatingTranslate.style.left = `${rect.left + rect.width / 2 - 34}px`;
  el.floatingTranslate.style.top = `${rect.bottom + 8}px`;
  el.floatingTranslate.dataset.text = text;
}

el.floatingTranslate.addEventListener('click', () => {
  const text = el.floatingTranslate.dataset.text || '';
  el.floatingTranslate.hidden = true;
  translateText(text);
});

el.viewer.addEventListener('scroll', () => {
  el.floatingTranslate.hidden = true;
});

// ------------------------------------------------------------ paragraph mode

/**
 * Turn paragraph badges on or off and remember the choice.
 *
 * Switching on can mean reading the whole document — cross-page paragraph
 * merging needs every page — so progress is reported while that happens.
 */
async function applyParagraphMode(on) {
  state.paragraphMode = on;
  el.btnParagraph.classList.toggle('is-active', on);
  savePrefs({ paragraph: on });
  try {
    await viewer.setParagraphMode(on, ({ done, total }) => {
      if (total > 8) showProgress(s('loading'), done, total);
    });
  } catch (err) {
    toast(s('err_open', { err: err?.message || err }), true);
  } finally {
    hideProgress();
  }
}

el.btnParagraph.addEventListener('click', () => {
  if (!state.hasDocument) return;
  applyParagraphMode(!state.paragraphMode);
});

// -------------------------------------------------------------- keyboard

document.addEventListener('keydown', (e) => {
  const typing =
    e.target instanceof HTMLInputElement ||
    e.target instanceof HTMLTextAreaElement ||
    e.target instanceof HTMLSelectElement;

  if (e.key === 'F11') {
    e.preventDefault();
    toggleFullscreen();
    return;
  }

  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey) {
    switch (e.key.toLowerCase()) {
      case 'o':
        e.preventDefault();
        el.fileInput.click();
        return;
      case 'f':
        e.preventDefault();
        openSearch();
        return;
      case 'p':
        e.preventDefault();
        el.btnParagraph.click();
        return;
      case 'b':
        e.preventDefault();
        el.btnBookmarks.click();
        return;
      case '0':
        e.preventDefault();
        viewer.fitPage();
        return;
      case '+':
      case '=':
        e.preventDefault();
        viewer.zoomIn();
        return;
      case '-':
        e.preventDefault();
        viewer.zoomOut();
        return;
      default:
        return;
    }
  }

  if (typing) return;
  if (!state.hasDocument) return;

  switch (e.key) {
    case 'PageDown':
    case 'ArrowRight':
      e.preventDefault();
      viewer.nextPage();
      break;
    case 'PageUp':
    case 'ArrowLeft':
      e.preventDefault();
      viewer.prevPage();
      break;
    case 'Home':
      e.preventDefault();
      viewer.gotoPage(0);
      break;
    case 'End':
      e.preventDefault();
      viewer.gotoPage(viewer.pageCount - 1);
      break;
    case 'Escape':
      if (document.fullscreenElement) document.exitFullscreen();
      else if (!el.searchBar.hidden) closeSearch();
      break;
    default:
      break;
  }
});

// ---------------------------------------------------------------- UI locale

document.querySelectorAll('.locale-btn').forEach((button) => {
  button.addEventListener('click', () => {
    const code = button.dataset.locale;
    setLocale(code);
    applyLocale();
    viewer.badgeLabel = s('tip_paragraph_badge');
    bookmarks.setLabels({ empty: s('bookmarks_empty') });
    document
      .querySelectorAll('.locale-btn')
      .forEach((b) => b.classList.toggle('is-active', b === button));
    if (state.hasDocument) {
      el.pageTotal.textContent = s('of_pages', { n: viewer.pageCount });
      // Existing badges keep the old tooltip until they are rebuilt.
      document.querySelectorAll('.para-badge').forEach((badge) => {
        badge.title = viewer.badgeLabel;
        badge.setAttribute('aria-label', viewer.badgeLabel);
      });
    }
    savePrefs({ locale: code });
  });
});

// ------------------------------------------------------------------- startup

function boot() {
  const prefs = loadPrefs();

  setLocale(prefs.locale || (navigator.language?.startsWith('tr') ? 'tr' : 'en'));
  applyLocale();
  viewer.badgeLabel = s('tip_paragraph_badge');
  bookmarks.setLabels({ empty: s('bookmarks_empty') });
  document.querySelectorAll('.locale-btn').forEach((b) => {
    b.classList.toggle('is-active', b.dataset.locale === getLocale());
  });

  const target = prefs.target && Object.values(LANGUAGES).includes(prefs.target)
    ? prefs.target
    : 'tr';
  el.targetSelect.value = target;
  translator.setTargetLanguage(target);

  el.sourceSelect.value = prefs.source || 'auto';
  translator.setSourceLanguage(el.sourceSelect.value);

  if (prefs.proxyUrl) translator.setConfig({ proxyUrl: prefs.proxyUrl });
  if (prefs.email) translator.setConfig({ email: prefs.email });

  applyEyeFilter(prefs.eye && prefs.eye in EYE_FILTERS ? prefs.eye : 'off');
  if (Number.isFinite(prefs.panelWidth)) {
    setPanelWidth(prefs.panelWidth, { persist: false });
  }
  setPanelVisible(prefs.panel !== false);
  setDocumentChromeVisible(false);
}

boot();

// Exposed for the browser console and for future settings UI.
window.LucidLector = { viewer, translator, savePrefs, loadPrefs };
