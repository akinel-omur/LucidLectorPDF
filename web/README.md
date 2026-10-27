# LucidLector Web

The browser version of LucidLectorPDF. Same reader, no installation — and the
PDF never leaves the machine it is opened on.

## Running it

```
web\start.bat
```

That runs `serve.py`, which serves this folder on `http://localhost:8000/` and
opens a browser. Add a port number to use a different one: `start.bat 8080`.

Opening `index.html` directly from disk will *not* work: browsers refuse to
load ES modules and web workers over `file://`.

`python -m http.server` will not do either. On Windows it reads MIME types from
the registry, where `.js` is often mapped to `text/plain`, and a browser
refuses to execute an ES module served with a non-JavaScript type. The page
then renders while no script ever runs. `serve.py` pins the content types
instead of asking the operating system.

Any static host works for deployment — GitHub Pages, Netlify, Vercel. There is
no build step and no backend; upload the folder as it stands.

## What is here

```
web/
├── index.html            Shell: toolbar, viewer, translation panel
├── css/app.css           Layout and theme
├── js/
│   ├── app.js            Wiring — the counterpart of main_window.py
│   ├── viewer.js         Rendering, zoom, navigation, search — pdf_view.py
│   ├── paragraphs.js     Runs → lines → blocks → merged paragraphs
│   ├── translator.js     Chunked, cached translation with provider fallback
│   ├── text-utils.js     Sentence splitting — a direct port of text_utils.py
│   └── i18n.js           TR/EN interface strings
├── vendor/               PDF.js 4.6.82 plus its CMaps and standard fonts
├── serve.py              Local server: pinned MIME types, threads, /api/translate
├── server/translate.js   Optional translation proxy for static hosting (see below)
└── tests/run-tests.mjs   Node test suite, no browser required
```

## How it maps to the desktop app

| Desktop (PyQt6 + PyMuPDF) | Web |
|---|---|
| `QGraphicsView` scene with page items | Absolutely sized `.page` elements |
| `PdfDocument.render_page` (PyMuPDF pixmap) | `PDFPageProxy.render` onto a canvas |
| Word-box hit testing for selection | PDF.js text layer + native browser selection |
| `page.get_text("blocks")` | `paragraphs.js` rebuilds blocks from text runs |
| `merged_paragraphs()` | `mergeParagraphs()` — same heuristic, ported |
| `text_utils.py` | `text-utils.js` — same functions, same tests |
| deep-translator (Google) | CORS-friendly services, or `server/translate.js` |
| `QSettings` | `localStorage` |

PDF.js has no equivalent of PyMuPDF's text blocks, so `paragraphs.js` rebuilds
that layer before the ported heuristic — the one that joins a paragraph broken
across a column or page break by looking at trailing hyphens and sentence-final
punctuation — can run at all. Four things in real documents make that harder
than it sounds, and each has a test in `paragraph-tests.mjs`:

Runs join a line by **vertical overlap**, not by how close their tops are.
A subscript in CO₂ sits lower and smaller; a footnote marker sits higher. Both
have tops far from the line they belong to, and clustering on that tears the
line apart at every one of them.

Column gutters are found by **looking down the whole page**, not row by row.
Justified text stretches its word spaces — 14pt in the sample against a 20pt
gutter — so no per-row threshold separates the two. Seen from above the
difference is plain: a gutter is white all the way down, a word space is white
in one row and covered in the next.

Paragraph breaks are measured against **the page's own leading**. Books set
paragraphs apart by a few points; a fixed threshold either misses that or
mistakes ordinary leading for a break.

An **indented first line** starts a new paragraph even with no extra space at
all, which is how most books separate them.

## Translation

When the reader is served by `serve.py`, translation goes through
`POST /api/translate` on that same local server, which forwards to Google. No
key, no setup, and no CORS problem — the browser cannot call that endpoint
itself, but the server can.

It reaches the same service the desktop app does, by a different door.
deep-translator requests `translate.google.com/m` and scrapes the translation
out of the HTML; `serve.py` asks `translate.googleapis.com/translate_a/single`,
which answers in JSON. Both are unofficial: no key, no quota, no guarantee.
That is fine for reading your own papers. For anything published, put a real
API behind `server/translate.js`.

On a static host that route does not exist. The 404 comes back immediately and
the app falls through to free, CORS-enabled services (Lingva, then MyMemory).
Those need no key either, but they are rate-limited and weaker on academic
prose.

Four things keep the wait short. Hovering a paragraph badge starts the
translation, so the click usually lands on an answer that is already back —
this is the one that matters, because it removes the round trip from the part
you actually wait through. The server keeps one HTTPS connection per thread
rather than shaking hands with Google again for every paragraph. Long
paragraphs go out as two or three overlapping requests instead of one after
another. And both the server and the browser cache by (text, source, target),
so a paragraph read twice, or a language switched back, costs nothing.

For the desktop app's translation quality, deploy `server/translate.js` as a
serverless function and point the app at it:

```js
LucidLector.savePrefs({ proxyUrl: 'https://your-app.vercel.app/api/translate' })
```

Set `DEEPL_KEY` on the function for the best academic results (500k characters
a month free), or `GOOGLE_KEY` for Cloud Translation.

## Tests

```
node web/tests/run-tests.mjs web/tests/sample.pdf   # logic + full pipeline
node web/tests/paragraph-tests.mjs                  # layout reconstruction
node web/tests/matching-tests.mjs                   # panel text ↔ page text
node web/tests/static-check.mjs                     # markup/script consistency
node web/tests/dom-smoke.mjs                        # boots the app in jsdom
```

`run-tests.mjs` runs PDF.js under Node against a real two-column document and
checks that text indexing, search-rectangle mapping and paragraph merging all
hold up. `static-check.mjs` catches the mistakes that produce a page which
renders but does nothing — a module that will not parse, an element id the
script reaches for that the markup never defines, a translation key present in
one language only. `dom-smoke.mjs` needs jsdom (`npm install jsdom`) and skips
itself when it is absent.

## Status

Working: opening (drag-drop or picker), continuous scroll with lazy page
rendering, zoom and fit modes, page navigation, text selection, selection
translation, paragraph-translate mode, sentence hover highlighting, full-text
search, eye-care filters, full screen, TR/EN interface, keyboard shortcuts.

Not yet ported: highlight and underline annotations, undo/redo, saving an
annotated PDF, the bookmarks panel, dual-page and split views, recent files.

## Licence

AGPL-3.0, as with the rest of the project. Note that the web version does not
use PyMuPDF — PDF.js is Apache-2.0 — so a future relicence is no longer blocked
by the PDF engine.
