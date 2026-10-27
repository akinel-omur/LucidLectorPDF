/**
 * UI string localisation — TR/EN subset ported from pdf_reader/i18n.py.
 *
 * Usage:
 *   import { s, setLocale } from './i18n.js';
 *   button.textContent = s('act_open');
 */

const STRINGS = {
  tr: {
    // Shell
    app_tagline: 'Akademik PDF okuyucu — anlık çeviri ile',
    drop_title: 'PDF dosyanızı buraya bırakın',
    drop_hint: 'ya da tıklayıp seçin — dosyanız bilgisayarınızdan çıkmaz',
    drop_privacy: 'Tüm işlem tarayıcınızda yapılır. Hiçbir dosya sunucuya yüklenmez.',
    loading: 'Yükleniyor…',

    // Toolbar
    tb_open: 'Aç',
    tip_open: 'PDF aç (Ctrl+O)',
    tip_prev: 'Önceki sayfa (PgUp)',
    tip_next: 'Sonraki sayfa (PgDn)',
    tip_zoom_in: 'Yakınlaştır (Ctrl++)',
    tip_zoom_out: 'Uzaklaştır (Ctrl+-)',
    tip_zoom_fit: 'Sayfayı sığdır (Ctrl+0)',
    tip_zoom_width: 'Genişliğe sığdır',
    tip_find: 'Ara (Ctrl+F)',
    tip_bookmarks: 'Yer işaretleri panelini göster/gizle (Ctrl+B)',
    bookmarks_title: 'Yer İşaretleri',
    bookmarks_empty: 'Bu belgede yer işareti yok',
    bm_expand_all: '＋ Hepsini Aç',
    bm_collapse_all: '－ Hepsini Kapat',
    tip_paragraph: 'Paragraf çeviri modu (Ctrl+P)',
    tip_paragraph_badge: 'Bu paragrafı çevir',
    tip_fullscreen: 'Tam ekran (F11)',
    tip_panel: 'Çeviri panelini göster/gizle',
    tip_panel_resize: 'Paneli yeniden boyutlandır (sürükleyin ya da ok tuşları)',
    of_pages: '/ {n}',

    // Eye filters
    menu_eye: 'Göz Koruması',
    eye_off: 'Kapalı',
    eye_hafif: 'Hafif Sıcak',
    eye_warm: 'Sıcak',
    eye_sepia: 'Sepya',
    eye_yesil: 'Yeşilimsi',
    eye_pembe: 'Pembe',
    eye_gece: 'Gece',
    eye_koyu_gece: 'Koyu Gece',
    eye_karartma: 'Karartma',

    // Search
    search_placeholder: 'Belgede ara…',
    search_none: 'Sonuç yok',
    search_count: '{i} / {n}',
    tip_search_prev: 'Önceki sonuç (Shift+Enter)',
    tip_search_next: 'Sonraki sonuç (Enter)',
    tip_search_close: 'Kapat (Esc)',

    // Translation panel
    panel_title: 'Çeviri',
    panel_original: 'Özgün metin',
    panel_translated: 'Çeviri',
    panel_empty: 'PDF üzerinde bir metin seçin — çevirisi burada görünür.',
    panel_hint_hover: 'Panelde bir cümlenin üzerine gelin, PDF’de nerede olduğu vurgulanır.',
    lbl_target: 'Hedef dil',
    lbl_source: 'Kaynak',
    src_auto: 'Otomatik',
    btn_copy: 'Kopyala',
    btn_copied: 'Kopyalandı',
    btn_translate: 'Çevir',
    translating: 'Çevriliyor…',
    translate_error: 'Çeviri başarısız: {err}',
    translate_limit:
      'Çeviri servisi günlük sınıra takıldı. Ayarlardan farklı bir servis seçebilirsiniz.',
    translate_busy:
      'Çeviri servisi çok fazla istek aldı. Birkaç saniye bekleyip tekrar deneyin.',

    // Errors
    err_open: 'PDF açılamadı: {err}',
    err_encrypted: 'PDF parola korumalı; şifresi çözülmeden açılamıyor.',
    err_not_pdf: 'Bu bir PDF dosyası değil.',
  },

  en: {
    app_tagline: 'A scholarly PDF reader — with live translation',
    drop_title: 'Drop your PDF here',
    drop_hint: 'or click to choose one — your file never leaves your computer',
    drop_privacy: 'Everything runs in your browser. No file is uploaded to any server.',
    loading: 'Loading…',

    tb_open: 'Open',
    tip_open: 'Open PDF (Ctrl+O)',
    tip_prev: 'Previous page (PgUp)',
    tip_next: 'Next page (PgDn)',
    tip_zoom_in: 'Zoom in (Ctrl++)',
    tip_zoom_out: 'Zoom out (Ctrl+-)',
    tip_zoom_fit: 'Fit page (Ctrl+0)',
    tip_zoom_width: 'Fit width',
    tip_find: 'Find (Ctrl+F)',
    tip_bookmarks: 'Show/hide the bookmarks panel (Ctrl+B)',
    bookmarks_title: 'Bookmarks',
    bookmarks_empty: 'This document has no bookmarks',
    bm_expand_all: '＋ Expand all',
    bm_collapse_all: '－ Collapse all',
    tip_paragraph: 'Paragraph translate mode (Ctrl+P)',
    tip_paragraph_badge: 'Translate this paragraph',
    tip_fullscreen: 'Full screen (F11)',
    tip_panel: 'Show/hide translation panel',
    tip_panel_resize: 'Resize the panel (drag, or use the arrow keys)',
    of_pages: '/ {n}',

    menu_eye: 'Eye care',
    eye_off: 'Off',
    eye_hafif: 'Light warm',
    eye_warm: 'Warm',
    eye_sepia: 'Sepia',
    eye_yesil: 'Greenish',
    eye_pembe: 'Pink',
    eye_gece: 'Night',
    eye_koyu_gece: 'Deep night',
    eye_karartma: 'Dim',

    search_placeholder: 'Find in document…',
    search_none: 'No results',
    search_count: '{i} / {n}',
    tip_search_prev: 'Previous match (Shift+Enter)',
    tip_search_next: 'Next match (Enter)',
    tip_search_close: 'Close (Esc)',

    panel_title: 'Translation',
    panel_original: 'Original',
    panel_translated: 'Translation',
    panel_empty: 'Select text in the PDF — its translation appears here.',
    panel_hint_hover:
      'Hover a sentence in the panel to highlight where it sits in the PDF.',
    lbl_target: 'Target',
    lbl_source: 'Source',
    src_auto: 'Auto',
    btn_copy: 'Copy',
    btn_copied: 'Copied',
    btn_translate: 'Translate',
    translating: 'Translating…',
    translate_error: 'Translation failed: {err}',
    translate_limit:
      'The translation service hit its daily limit. You can pick another one in settings.',
    translate_busy:
      'The translation service is being rate limited. Wait a few seconds and try again.',

    err_open: 'Could not open the PDF: {err}',
    err_encrypted: 'This PDF is password protected and cannot be opened.',
    err_not_pdf: 'That is not a PDF file.',
  },
};

export const LOCALES = Object.keys(STRINGS);

let current = 'tr';

/** Set the active UI locale. Unknown codes are ignored. */
export function setLocale(code) {
  if (STRINGS[code]) current = code;
  return current;
}

/** The active UI locale code. */
export function getLocale() {
  return current;
}

/**
 * Look up a string in the active locale, with `{name}` placeholder
 * substitution. Falls back to English, then to the key itself.
 *
 * @param {string} key
 * @param {Record<string, string|number>} [vars]
 */
export function s(key, vars) {
  const text = STRINGS[current]?.[key] ?? STRINGS.en[key] ?? key;
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (m, name) =>
    name in vars ? String(vars[name]) : m,
  );
}

/**
 * Apply the active locale to the document: every element carrying
 * `data-i18n` gets its text content set, `data-i18n-title` its tooltip, and
 * `data-i18n-placeholder` its placeholder.
 *
 * @param {ParentNode} [root]
 */
export function applyLocale(root = document) {
  root.querySelectorAll('[data-i18n]').forEach((el) => {
    el.textContent = s(el.dataset.i18n);
  });
  root.querySelectorAll('[data-i18n-title]').forEach((el) => {
    el.title = s(el.dataset.i18nTitle);
    if (!el.getAttribute('aria-label')) {
      el.setAttribute('aria-label', s(el.dataset.i18nTitle));
    }
  });
  root.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
    el.placeholder = s(el.dataset.i18nPlaceholder);
  });
  document.documentElement.lang = current;
}
