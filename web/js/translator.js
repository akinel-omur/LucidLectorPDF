/**
 * Translation service — the web counterpart of pdf_reader/translator.py.
 *
 * The desktop app calls deep-translator, which talks to Google's endpoint from
 * Python. A browser cannot do that: the endpoint sends no CORS headers, so the
 * request is blocked before it leaves the page. Instead this module speaks to
 * CORS-enabled services directly, and can be pointed at a self-hosted proxy
 * (see ../server/) when higher quality or higher volume is wanted.
 *
 * Everything else mirrors the Python original: async, chunked to stay under
 * per-request limits, and cached by (text, source, target) so switching
 * languages back and forth costs nothing.
 */

import { sentenceBoundaries } from './text-utils.js';

/** Target languages offered in the UI: display label → ISO 639-1 code. */
export const LANGUAGES = {
  TR: 'tr',
  EN: 'en',
  ES: 'es',
  DE: 'de',
  FR: 'fr',
  RU: 'ru',
};

/** Most frequent function words per language, used to guess the source. */
const STOPWORDS = {
  tr: ['bir', 'bu', 've', 'için', 'ile', 'olarak', 'daha', 'değil', 'çok', 'gibi'],
  en: ['the', 'of', 'and', 'to', 'in', 'that', 'is', 'for', 'with', 'this'],
  de: ['der', 'die', 'und', 'den', 'von', 'nicht', 'mit', 'ist', 'des', 'eine'],
  fr: ['le', 'la', 'les', 'de', 'et', 'des', 'une', 'pour', 'dans', 'est'],
  es: ['el', 'la', 'los', 'de', 'que', 'una', 'para', 'con', 'por', 'es'],
};

/**
 * Guess the source language of `text`.
 *
 * Cheap on purpose: a Cyrillic script check, then a stopword vote. Services
 * that accept `auto` never see this — it exists for MyMemory, which insists on
 * an explicit source language.
 *
 * @param {string} text
 * @returns {string} ISO 639-1 code, defaulting to 'en'
 */
export function detectLanguage(text) {
  if (/[Ѐ-ӿ]/.test(text)) return 'ru';

  const words = text.toLowerCase().match(/[\p{L}]+/gu) || [];
  if (!words.length) return 'en';
  const sample = new Set(words.slice(0, 400));

  let best = 'en';
  let bestScore = -1;
  for (const [lang, list] of Object.entries(STOPWORDS)) {
    let score = list.reduce((acc, w) => acc + (sample.has(w) ? 1 : 0), 0);
    // Turkish-specific letters are a strong signal on their own.
    if (lang === 'tr' && /[ğışçöüĞİŞÇÖÜ]/.test(text)) score += 3;
    if (lang === 'de' && /[äöüßÄÖÜ]/.test(text)) score += 1;
    if (lang === 'fr' && /[àâçéèêëîïôùûœ]/.test(text)) score += 1;
    if (lang === 'es' && /[áéíóúñ¿¡]/.test(text)) score += 1;
    if (score > bestScore) {
      bestScore = score;
      best = lang;
    }
  }
  return best;
}

/**
 * Split `text` into chunks no longer than `size`, preferring sentence
 * boundaries and falling back to word boundaries. Port of `_chunks` in
 * translator.py, made sentence-aware so short-limit services (MyMemory caps a
 * request at 500 characters) do not cut mid-sentence and wreck the output.
 *
 * @param {string} text
 * @param {number} size
 * @returns {string[]}
 */
export function chunk(text, size) {
  if (text.length <= size) return [text];

  const pieces = [];
  for (const [start, end] of sentenceBoundaries(text)) {
    const sentence = text.slice(start, end);
    if (sentence.length <= size) {
      pieces.push(sentence);
      continue;
    }
    // A single sentence longer than the limit: fall back to word boundaries.
    let cursor = 0;
    while (cursor < sentence.length) {
      let stop = Math.min(cursor + size, sentence.length);
      if (stop < sentence.length) {
        const space = sentence.lastIndexOf(' ', stop);
        if (space > cursor) stop = space;
      }
      pieces.push(sentence.slice(cursor, stop));
      cursor = stop;
    }
  }

  // Pack consecutive pieces back together up to the limit — fewer requests.
  const out = [];
  let buffer = '';
  for (const piece of pieces) {
    if (buffer && buffer.length + piece.length > size) {
      out.push(buffer);
      buffer = piece;
    } else {
      buffer += piece;
    }
  }
  if (buffer) out.push(buffer);
  return out.filter((p) => p.trim());
}

class TranslationError extends Error {
  constructor(message, { retryable = false } = {}) {
    super(message);
    this.name = 'TranslationError';
    this.retryable = retryable;
  }
}

async function fetchJson(url, options = {}, timeoutMs = 9000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    if (!response.ok) {
      throw new TranslationError(`HTTP ${response.status}`, {
        retryable: response.status >= 500 || response.status === 429,
      });
    }
    return await response.json();
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new TranslationError('zaman aşımı', { retryable: true });
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Providers, in the order `Translator` falls back through them.
 *
 * `limit` is the per-request character cap. `needsSource` marks services that
 * reject `auto` and must be told the source language.
 */
const PROVIDERS = {
  /**
   * The local server started by start.bat, which forwards to the same endpoint
   * deep-translator uses on the desktop. No key, no CORS problem, no rate
   * limit worth worrying about — so it is tried first. On a static host the
   * route does not exist, the 404 arrives immediately, and the free services
   * below take over.
   */
  local: {
    label: 'Yerel sunucu (serve.py)',
    limit: 4500,
    needsSource: false,
    async translate(text, source, target) {
      const data = await fetchJson(
        '/api/translate',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ q: text, source, target }),
        },
        // Generous: the server chunks long paragraphs and translates in turn.
        30000,
      );
      if (typeof data?.translation !== 'string') {
        throw new TranslationError(data?.error || 'beklenmeyen yanıt');
      }
      return data.translation;
    },
  },

  /** Self-hosted proxy (see ../server/translate.js). Best quality, needs setup. */
  proxy: {
    label: 'Kendi sunucum (proxy)',
    limit: 4500,
    needsSource: false,
    async translate(text, source, target, config) {
      if (!config.proxyUrl) throw new TranslationError('proxy adresi tanımlı değil');
      const data = await fetchJson(config.proxyUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ q: text, source, target }),
      });
      if (!data || typeof data.translation !== 'string') {
        throw new TranslationError('beklenmeyen yanıt');
      }
      return data.translation;
    },
  },

  /** MyMemory: no key, CORS-friendly, ~500 chars per request. */
  mymemory: {
    label: 'MyMemory (anahtarsız)',
    limit: 480,
    needsSource: true,
    async translate(text, source, target, config) {
      const params = new URLSearchParams({
        q: text,
        langpair: `${source}|${target}`,
      });
      // Supplying an email raises the free daily allowance considerably.
      if (config.email) params.set('de', config.email);
      const data = await fetchJson(
        `https://api.mymemory.translated.net/get?${params}`,
      );
      const status = Number(data.responseStatus);
      if (status !== 200) {
        const detail = String(data.responseDetails || '').toLowerCase();
        throw new TranslationError(data.responseDetails || `durum ${status}`, {
          retryable: detail.includes('limit') || detail.includes('quota'),
        });
      }
      return data.responseData?.translatedText ?? '';
    },
  },

  /** Lingva: a CORS-enabled Google Translate front end. Accepts `auto`. */
  lingva: {
    label: 'Lingva',
    limit: 2000,
    needsSource: false,
    async translate(text, source, target, config) {
      const base = config.lingvaUrl || 'https://lingva.ml';
      const url = `${base.replace(/\/$/, '')}/api/v1/${source}/${target}/${encodeURIComponent(text)}`;
      const data = await fetchJson(url);
      if (typeof data.translation !== 'string') {
        throw new TranslationError('beklenmeyen yanıt');
      }
      return data.translation;
    },
  },
};

export const PROVIDER_IDS = Object.keys(PROVIDERS);
export const PROVIDER_LABELS = Object.fromEntries(
  Object.entries(PROVIDERS).map(([id, p]) => [id, p.label]),
);

/**
 * Async, cached, chunked translation with provider fallback.
 *
 * Emits nothing by itself — callers await `translate()`. The desktop version
 * used Qt signals because Qt has no promises; the browser does.
 */
export class Translator {
  /**
   * @param {Object} [options]
   * @param {string} [options.target]   Initial target language code.
   * @param {string[]} [options.order]  Provider ids, highest preference first.
   * @param {Object} [options.config]   Provider config (proxyUrl, email, …).
   */
  constructor({
    target = 'tr',
    order = ['local', 'lingva', 'mymemory'],
    config = {},
  } = {}) {
    /** @type {Map<string, string>} keyed by `${source}|${target}|${text}` */
    this.cache = new Map();
    this.target = target;
    this.order = order;
    this.config = config;
    this.source = 'auto';
    this.lastProvider = null;
    this._sequence = 0;
  }

  setTargetLanguage(code) {
    if (Object.values(LANGUAGES).includes(code)) this.target = code;
    return this.target;
  }

  setSourceLanguage(code) {
    this.source = code || 'auto';
    return this.source;
  }

  setConfig(patch) {
    this.config = { ...this.config, ...patch };
    // A configured proxy is always the best option available.
    if (this.config.proxyUrl && !this.order.includes('proxy')) {
      this.order = ['proxy', ...this.order];
    }
  }

  /**
   * Translate `text` into the current target language.
   *
   * Stale calls resolve to `null`: when the user selects new text mid-request,
   * the earlier promise is abandoned rather than allowed to overwrite the
   * panel with an outdated translation.
   *
   * @param {string} raw
   * @param {(progress: {done: number, total: number}) => void} [onProgress]
   * @returns {Promise<string|null>}
   */
  async translate(raw, onProgress) {
    const token = ++this._sequence;
    return this._translate(raw, onProgress, () => token !== this._sequence);
  }

  /**
   * Translate in the background to warm the cache, and say nothing.
   *
   * Called when the pointer settles on a paragraph badge: by the time the
   * click arrives the answer is usually already here, which removes the whole
   * round trip from the part the reader actually waits through. It never
   * supersedes a real request, and a failure is not worth reporting — the
   * click will try again and report it then.
   *
   * @param {string} raw
   */
  async prefetch(raw) {
    try {
      await this._translate(raw, undefined, () => false);
    } catch {
      /* the click will surface it */
    }
  }

  /**
   * @param {string} raw
   * @param {((p: {done:number,total:number}) => void)|undefined} onProgress
   * @param {() => boolean} superseded  True once this result is no longer wanted.
   */
  async _translate(raw, onProgress, superseded) {
    const text = raw.trim();
    if (!text) return '';

    const source =
      this.source === 'auto' ? detectLanguage(text) : this.source;

    if (source === this.target) return text;

    const key = `${source}|${this.target}|${text}`;
    if (this.cache.has(key)) return this.cache.get(key);

    let lastError = null;
    for (const id of this.order) {
      const provider = PROVIDERS[id];
      if (!provider) continue;
      if (id === 'proxy' && !this.config.proxyUrl) continue;

      try {
        const wire = provider.needsSource || this.source !== 'auto' ? source : 'auto';
        const parts = chunk(text, provider.limit);
        const translated = [];
        for (let i = 0; i < parts.length; i++) {
          const piece = await provider.translate(
            parts[i],
            wire,
            this.target,
            this.config,
          );
          if (superseded()) return null;
          translated.push(piece);
          onProgress?.({ done: i + 1, total: parts.length });
        }
        const result = translated.join(' ').replace(/\s+/g, ' ').trim();
        this.cache.set(key, result);
        this.lastProvider = id;
        return result;
      } catch (err) {
        lastError = err;
        if (superseded()) return null;
        // Try the next provider.
      }
    }

    throw lastError ?? new TranslationError('çeviri servisi yanıt vermedi');
  }
}
