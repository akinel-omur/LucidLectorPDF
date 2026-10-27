/**
 * Optional translation proxy.
 *
 * The browser cannot call Google Translate directly — the endpoint sends no
 * CORS headers, so the request never leaves the page. Without a proxy the app
 * falls back to the CORS-enabled services in js/translator.js, which are free
 * but rate-limited and weaker on academic prose. Deploying this function and
 * pointing the app at it restores the desktop reader's translation quality.
 *
 * Deploy as a serverless function (Vercel, Netlify, Cloudflare Workers all
 * accept this shape), then in the browser console:
 *
 *     LucidLector.savePrefs({ proxyUrl: 'https://your-app.vercel.app/api/translate' })
 *
 * and reload. js/translator.js prefers the proxy over everything else.
 *
 * Set DEEPL_KEY to use DeepL (best for academic text, 500k chars/month free)
 * or GOOGLE_KEY for Cloud Translation. With neither, it uses Google's public
 * web endpoint — fine for personal use, not for a service you publish.
 */

const ALLOWED_ORIGINS = process.env.ALLOWED_ORIGINS?.split(',').map((o) => o.trim());
const MAX_CHARS = 5000;

export default async function handler(request, response) {
  const origin = request.headers.origin || '';
  const allowed =
    !ALLOWED_ORIGINS || ALLOWED_ORIGINS.includes('*') || ALLOWED_ORIGINS.includes(origin);

  response.setHeader('Access-Control-Allow-Origin', allowed ? origin || '*' : 'null');
  response.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  response.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (request.method === 'OPTIONS') return response.status(204).end();
  if (request.method !== 'POST') return response.status(405).json({ error: 'POST only' });
  if (!allowed) return response.status(403).json({ error: 'origin not allowed' });

  const { q, source = 'auto', target = 'tr' } = request.body ?? {};
  if (typeof q !== 'string' || !q.trim()) {
    return response.status(400).json({ error: 'q is required' });
  }
  if (q.length > MAX_CHARS) {
    return response.status(413).json({ error: `q exceeds ${MAX_CHARS} characters` });
  }
  if (!/^[a-z]{2}(-[A-Za-z]{2,4})?$/.test(target)) {
    return response.status(400).json({ error: 'invalid target language' });
  }

  try {
    const translation = await translate(q, source, target);
    return response.status(200).json({ translation });
  } catch (err) {
    return response.status(502).json({ error: String(err.message || err) });
  }
}

async function translate(q, source, target) {
  if (process.env.DEEPL_KEY) return viaDeepL(q, source, target);
  if (process.env.GOOGLE_KEY) return viaGoogleCloud(q, source, target);
  return viaGoogleWeb(q, source, target);
}

async function viaDeepL(q, source, target) {
  const host = process.env.DEEPL_KEY.endsWith(':fx')
    ? 'https://api-free.deepl.com'
    : 'https://api.deepl.com';
  const body = new URLSearchParams({ text: q, target_lang: target.toUpperCase() });
  if (source && source !== 'auto') body.set('source_lang', source.toUpperCase());

  const res = await fetch(`${host}/v2/translate`, {
    method: 'POST',
    headers: {
      Authorization: `DeepL-Auth-Key ${process.env.DEEPL_KEY}`,
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body,
  });
  if (!res.ok) throw new Error(`DeepL ${res.status}`);
  const data = await res.json();
  return data.translations?.[0]?.text ?? '';
}

async function viaGoogleCloud(q, source, target) {
  const url = `https://translation.googleapis.com/language/translate/v2?key=${process.env.GOOGLE_KEY}`;
  const payload = { q, target, format: 'text' };
  if (source && source !== 'auto') payload.source = source;

  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Google ${res.status}`);
  const data = await res.json();
  return data.data?.translations?.[0]?.translatedText ?? '';
}

/** The unofficial endpoint deep-translator uses from the desktop app. */
async function viaGoogleWeb(q, source, target) {
  const params = new URLSearchParams({
    client: 'gtx',
    sl: source === 'auto' ? 'auto' : source,
    tl: target,
    dt: 't',
    q,
  });
  const res = await fetch(`https://translate.googleapis.com/translate_a/single?${params}`);
  if (!res.ok) throw new Error(`Google web ${res.status}`);
  const data = await res.json();
  // Response shape: [[[chunk, original, …], …], …]
  return (data?.[0] ?? []).map((part) => part[0]).join('');
}
