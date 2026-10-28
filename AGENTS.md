# AGENTS.md — LucidLectorPDF

Tool-agnostic project brief for any AI coding assistant (Claude Code, ChatGPT/Codex,
Cursor, Copilot, …). **Read this file, then `docs/HANDOFF.md`, before touching code.**
`CLAUDE.md` simply points here.

## What this is

Academic PDF reader with live translation. Owner: Ömür Akınel (Turkish-speaking; talk to
him in Turkish unless he writes in English; code, identifiers, commit messages in English).

Two implementations of the same reader:

| Part | Stack | Path |
|---|---|---|
| Desktop app (Windows) | Python 3.11+, PyQt6, PyMuPDF, deep-translator | `main.py`, `pdf_reader/` |
| Web port (no build step) | Vanilla ES modules, PDF.js 4.6.82 (vendored) | `web/` |

The web port mirrors the desktop logic: `pdf_reader/text_utils.py` ↔ `web/js/text-utils.js`
(same functions, same tests). **Change one → change the other.**

## Commands

```powershell
# Desktop
pip install -r requirements.txt -r requirements-dev.txt
python main.py [file.pdf]
python -m pytest                      # 37 tests, pure Python (no Qt/PyMuPDF needed)
build.bat                             # PyInstaller → dist\LucidLectorPDF.exe

# Web
web\start.bat                         # serves http://localhost:8000 (needs serve.py; do NOT open index.html via file://)
node web/tests/run-tests.mjs web/tests/sample.pdf
node web/tests/paragraph-tests.mjs
node web/tests/static-check.mjs
node web/tests/matching-tests.mjs
```

One-shot setup on a fresh machine: `scripts\setup.ps1`. Save work to GitHub: `scripts\sync.ps1`.

## Layout

```
main.py                  entry point
pdf_reader/              desktop app (main_window, pdf_view, pdf_document, translator,
                         translation_popup, bookmark_panel, search_bar, recent_files,
                         i18n, text_utils)
web/                     browser port (index.html, js/, css/, vendor/, serve.py, server/)
tests/                   pytest for desktop pure logic
web/tests/               node tests for the web port
docs/                    HANDOFF.md (living state), KOD_DENETIMI.md (code audit, Turkish)
scripts/                 setup.ps1, sync.ps1
```

## Conventions

- Line endings are normalised by `.gitattributes` (LF; `.bat/.cmd/.ps1` stay CRLF).
- `build/`, `dist/`, `*.spec`, `.claude/`, `__pycache__/` are git-ignored. Never commit `.exe`;
  releases go to GitHub Releases.
- UI strings live in `pdf_reader/i18n.py` (desktop) and `web/js/i18n.js` (web). Add a key to
  every language or `static-check.mjs` will flag it.
- Split view: use `self._active_view`, never `self._view`, in `main_window.py` (this bug class
  already bit once; see KOD_DENETIMI §1.1).
- Render work uses its own thread pool, separate from translation (KOD_DENETIMI §1.4).
- Commit style: `feat:`, `fix:`, `perf:`, `docs:`, `chore:`, `test:`. Small, focused commits.
- License is AGPL-3.0 (PyMuPDF is AGPL). Keep it.

## Working agreement for any assistant

1. Start: `git pull`, read `docs/HANDOFF.md`, run the tests that apply.
2. Keep changes scoped to what was asked; do not reformat unrelated files.
3. Before finishing: run tests, then **update `docs/HANDOFF.md`** (done / in progress / next /
   decisions / gotchas) and commit + push (`scripts\sync.ps1`). The next session — possibly
   in a different account or a different AI — only knows what is in the repo.
4. Never commit secrets (API keys, tokens). Translation keys (`DEEPL_KEY`, `GOOGLE_KEY`) are
   environment variables on the serverless function, not files.
