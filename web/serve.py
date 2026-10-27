"""Static server for the LucidLector web reader.

`python -m http.server` is not reliable here. On Windows, Python's mimetypes
module consults the registry, where .js is frequently registered as text/plain.
Browsers refuse to execute an ES module served with a non-JavaScript MIME type,
so the whole application silently fails to start: the page renders, but no
script ever runs.

This server pins the content types instead of asking the operating system,
serves requests on threads, and steps to the next free port if an older server
is still holding the usual one.

It also answers POST /api/translate. The browser cannot call a translation
service directly -- those endpoints send no CORS headers, so the request never
leaves the page -- which left the web reader depending on slow, rate-limited
public mirrors. Going through this server instead reaches Google the same way
the desktop app does, with no API key and no setup.

Not quite the same door, though. deep-translator, which the desktop app uses,
requests the mobile page translate.google.com/m and scrapes the result out of
the HTML. This asks translate.googleapis.com/translate_a/single, which answers
in JSON: same service, no HTML parsing to break when the markup changes, and no
BeautifulSoup dependency.

Usage:
    python serve.py [port]
"""
from __future__ import annotations

import http.client
import http.server
import json
import threading
import time
import socketserver
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_PORT = 8000
PORT_ATTEMPTS = 12

# Google's endpoint takes the text in the query string, so requests are kept
# well inside the practical URL length limit.
TRANSLATE_CHUNK = 1500
TRANSLATE_TIMEOUT = 20
TRANSLATE_MAX_CHARS = 20000
# Google throttles bursts. Paragraph mode makes bursts easy -- a few clicks in
# a row, each several chunks -- so a 429 is expected rather than exceptional,
# and worth waiting out instead of failing in the reader's face.
TRANSLATE_RETRIES = 3
TRANSLATE_BACKOFF = (1.5, 4.0, 9.0)
# Long paragraphs go out together rather than one after another. Kept small:
# the point is to overlap two or three waits, not to hand Google a burst.
TRANSLATE_WORKERS = 3
TRANSLATE_HOST = "translate.googleapis.com"
CACHE_MAX = 500

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".pdf": "application/pdf",
    ".bcmap": "application/octet-stream",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


def _split(text, size):
    """Split on sentence ends where possible, on spaces otherwise."""
    if len(text) <= size:
        return [text]
    parts, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind(". "), window.rfind("? "), window.rfind("! "))
            if cut < size // 2:
                cut = window.rfind(" ")
            if cut > 0:
                end = start + cut + 1
        parts.append(text[start:end])
        start = end
    return [p for p in parts if p.strip()]


# Translations already fetched, newest last. The reader caches too, but only
# for as long as the page is open; this survives a reload, and paragraph mode
# means the same paragraph gets asked for again more often than you would
# think.
_cache = {}
_cache_lock = threading.Lock()

# One HTTPS connection per worker thread, reused. A fresh TLS handshake on
# every paragraph costs more than the translation itself on a distant link.
_connections = threading.local()


def _cached(key):
    with _cache_lock:
        return _cache.get(key)


def _remember(key, value):
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[key] = value


def _fetch(path):
    """GET `path` from Google, reusing this thread's connection."""
    for attempt in (0, 1):
        connection = getattr(_connections, "conn", None)
        if connection is None:
            connection = http.client.HTTPSConnection(TRANSLATE_HOST, timeout=TRANSLATE_TIMEOUT)
            _connections.conn = connection
        try:
            connection.request("GET", path, headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "*/*",
            })
            response = connection.getresponse()
            body = response.read()
            if response.status != 200:
                raise urllib.error.HTTPError(
                    path, response.status, response.reason, response.headers, None
                )
            return body
        except urllib.error.HTTPError:
            raise
        except (http.client.HTTPException, OSError):
            # A pooled connection can be closed by the far end between uses;
            # that is not a failure, it just needs redialling once.
            try:
                connection.close()
            except Exception:
                pass
            _connections.conn = None
            if attempt:
                raise
    raise RuntimeError("unreachable")


def google_translate(text, source, target):
    """Translate through Google's unofficial JSON endpoint.

    Same service the desktop app reaches through deep-translator, via the JSON
    endpoint rather than the scraped mobile page. Unofficial either way: no key,
    no quota, and no promise it will keep working. Fine for reading your own
    papers; for anything you publish, put a real API behind server/translate.js.
    """
    key = (text, source, target)
    hit = _cached(key)
    if hit is not None:
        return hit

    parts = _split(text, TRANSLATE_CHUNK)
    if len(parts) == 1:
        result = _translate_chunk(parts[0], source, target)
    else:
        with ThreadPoolExecutor(max_workers=min(TRANSLATE_WORKERS, len(parts))) as pool:
            pieces = list(pool.map(lambda p: _translate_chunk(p, source, target), parts))
        result = " ".join(pieces).strip()

    _remember(key, result)
    return result


def _translate_chunk(part, source, target):
    """One request, retried through a rate limit."""
    query = urllib.parse.urlencode({
        "client": "gtx",
        "sl": source or "auto",
        "tl": target,
        "dt": "t",
        "q": part,
    })
    path = "/translate_a/single?" + query

    last = None
    for attempt in range(TRANSLATE_RETRIES):
        try:
            payload = json.loads(_fetch(path).decode("utf-8", "replace"))
            segments = payload[0] or []
            return "".join(s[0] for s in segments if s and s[0])
        except urllib.error.HTTPError as err:
            last = err
            if err.code not in (429, 503) or attempt == TRANSLATE_RETRIES - 1:
                raise
            time.sleep(TRANSLATE_BACKOFF[min(attempt, len(TRANSLATE_BACKOFF) - 1)])
    raise last


class Server(socketserver.ThreadingTCPServer):
    """Threaded on purpose.

    A browser opens several connections at once to fetch a module graph, and
    it keeps speculative ones open. A single-threaded server answers one at a
    time, so those idle connections stall every request behind them: the page
    loads, the modules never arrive, and nothing reports an error because
    nothing failed -- it is simply still waiting.
    """

    daemon_threads = True
    allow_reuse_address = False  # never silently steal a port in use


class Handler(http.server.SimpleHTTPRequestHandler):

    protocol_version = "HTTP/1.1"  # keep-alive; requires an accurate Content-Length

    def guess_type(self, path):
        # Never defer to mimetypes for the types that matter. On Windows it
        # reads the registry, where .js is often text/plain, and a browser
        # will not execute an ES module served with that type.
        ext = Path(str(path)).suffix.lower()
        if ext in CONTENT_TYPES:
            return CONTENT_TYPES[ext]
        return super().guess_type(path)

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/api/translate":
            self.send_error(404, "Unknown endpoint")
            return

        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= 128 * 1024:
            self.send_error(400, "Bad request body")
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            text = str(payload.get("q") or "")
            source = str(payload.get("source") or "auto")
            target = str(payload.get("target") or "tr")
        except (ValueError, UnicodeDecodeError):
            self.send_error(400, "Malformed JSON")
            return

        if not text.strip():
            self._send_json(400, {"error": "q is required"})
            return
        if len(text) > TRANSLATE_MAX_CHARS:
            self._send_json(413, {"error": "text too long"})
            return

        try:
            self._send_json(200, {"translation": google_translate(text, source, target)})
        except urllib.error.HTTPError as err:
            # Pass the throttle through as a throttle: the reader shows a
            # "wait a moment" message for 429 and a failure for anything else.
            status = 429 if err.code in (429, 503) else 502
            self._send_json(status, {"error": "Google: HTTP %d" % err.code})
        except (urllib.error.URLError, OSError, ValueError, IndexError) as err:
            self._send_json(502, {"error": "%s: %s" % (type(err).__name__, err)})

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        # Without this the browser serves a stale module from cache after an
        # edit, which is maddening while developing.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-LucidLector-Server", "1")
        super().end_headers()

    def log_message(self, fmt, *args):
        status = str(args[1]) if len(args) > 1 else ""
        if status.startswith(("4", "5")):
            super().log_message(fmt, *args)


def bind(first_port):
    """Bind first_port, or the next few if something already holds it.

    An older `python -m http.server` left running in another window is the
    common case. It serves this same folder with the wrong MIME types, so
    quietly reusing its port would make the app look broken. Moving to a free
    port instead means the browser lands on a server that works.
    """
    handler = partial(Handler, directory=str(ROOT))
    for port in range(first_port, first_port + PORT_ATTEMPTS):
        try:
            return Server(("127.0.0.1", port), handler), port
        except OSError:
            print("Port %d dolu, sonraki deneniyor..." % port)
    return None, None


def main():
    requested = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT

    server, port = bind(requested)
    if server is None:
        print("Bos port bulunamadi. Acik sunucu pencerelerini kapatip tekrar deneyin.")
        return 1

    url = "http://localhost:%d/" % port
    print("")
    print("  LucidLector Web  ->  %s" % url)
    print("  Durdurmak icin Ctrl+C")
    print("")

    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nKapatiliyor.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
