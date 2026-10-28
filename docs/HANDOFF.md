# HANDOFF — LucidLectorPDF

Living state of the project. **Whoever works on it last updates this file before pushing.**
Last updated: 2026-10-21 (initial handoff setup).

## Starting a new session (any account, any AI)

1. `git clone https://github.com/akinel-omur/LucidLectorPDF.git` (or `git pull`)
2. Paste this to the assistant:

   > Bu depo LucidLectorPDF (akademik PDF okuyucu, PyQt6 masaüstü + PDF.js web sürümü).
   > Önce `AGENTS.md` ve `docs/HANDOFF.md` dosyalarını oku, ilgili testleri çalıştır, sonra
   > "Sıradaki işler" listesinden devam et: <hedef>. Bitirince HANDOFF.md'yi güncelle,
   > commit et ve push et. Benimle Türkçe konuş.

3. Claude Code reads `CLAUDE.md` automatically; ChatGPT/Codex/Cursor read `AGENTS.md`.
   In a plain chat UI (no repo access), upload `AGENTS.md` + this file + the files being changed.

## Ending a session

Update this file → `scripts\sync.ps1 "kısa mesaj"` (commits and pushes). One-time setup of
GitHub login on a new machine: `git push` once and sign in via the browser prompt, or `gh auth login`.

## Current state

- Version 1.1.0 (tags `v1.0.0`, `v1.1.0`). Desktop app is feature-complete for reading,
  highlighting, translation, paragraph mode, split view, bookmarks, lazy async rendering.
- Web port (`web/`) works for: open, scroll with lazy render, zoom/fit, navigation, selection
  translation, paragraph translate, sentence hover highlight, search, eye-care filters, TR/EN UI.
- **Not yet ported to web:** highlight/underline annotations, undo/redo, saving annotated PDF,
  bookmarks panel, dual-page/split view, recent files.
- Tests: pytest 37 pass; node `run-tests` 35, `paragraph-tests` 17, `static-check` clean.
- All web test suites pass (matching-tests fixed 2026-10-28: the test fixture lacked `items`).

## Sıradaki işler (priority order)

From `docs/KOD_DENETIMI.md` §7 (items 1–7 done):

1. Translation panel should follow the source panel in split view (needs `translate_requested`
   to carry the source panel; signal signature change). Three inconsistent scenarios listed in
   KOD_DENETIMI §9 "Hâlâ açık".
2. `PanelState` dataclass replacing four parallel dicts (§5).
3. UI language vs translation target language separation (§3).
4. Ctrl+F freezes the UI on very large documents (twin of §1.3).
5. Highlight export feature (§6).
6. Smaller open items: §1.9 arrow keys hijack horizontal scroll, §1.11 `RecentFiles.list()`
   hits disk on every menu open; `_sync_view_mode_actions` `blockSignals` caveat if those
   actions ever move to a toolbar.
7. Web port: port annotations/undo/save, bookmarks, recent files (see list above).

## Decisions worth remembering

- AGPL-3.0 because PyMuPDF is AGPL; the web port uses PDF.js (Apache-2.0), so a future relicense
  is no longer blocked by the PDF engine.
- Translation: desktop uses deep-translator (Google). Web: local `serve.py` proxies
  `translate.googleapis.com`; on static hosting falls back to Lingva/MyMemory; optional
  `web/server/translate.js` serverless proxy with `DEEPL_KEY`/`GOOGLE_KEY`.
- Web must be served with correct JS MIME types (`serve.py` pins them); `python -m http.server`
  and `file://` do not work on Windows.
- Line endings: `.gitattributes` normalises to LF. After first adopting it, run once:
  `git add --renormalize . && git commit -m "chore: normalize line endings"`.

## Gotchas

- Sandboxed/remote tools may not run Qt; the desktop UI can only be verified on the owner's
  Windows machine. Pure-logic code lives in `pdf_reader/text_utils.py` so it is testable anywhere.
- `dom-smoke.mjs` needs `jsdom` (`npm install jsdom --no-save`) and skips itself otherwise.
- Never commit `dist/*.exe` or `build/`; attach binaries to GitHub Releases.

## Session log (newest first; one line each)

- 2026-10-28 — Fixed matching-tests fixture; CI now gates on all web suites.
- 2026-10-21 — Added AGENTS.md/CLAUDE.md, this file, scripts, CI; pushed pending local commits
  (bookmark panel, split view, lazy rendering) and the web port + tests.
