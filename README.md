# LucidLectorPDF

<p align="center">
  <img src="resources/icon.png" width="96" alt="LucidLectorPDF icon"/>
</p>

<p align="center">
  A fast, keyboard-friendly PDF reader for Windows with real-time translation, smart highlighting, and scholar-mode paragraph translation — built with PyQt6 and PyMuPDF.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/PyQt6-UI-41CD52?logo=qt&logoColor=white"/>
  <img src="https://img.shields.io/badge/PyMuPDF-PDF%20engine-orange"/>
  <img src="https://img.shields.io/badge/License-AGPL--3.0-red"/>
  <img src="https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows&logoColor=white"/>
</p>

---

## Features

| Feature | Details |
|---|---|
| 📄 **High-fidelity rendering** | 2× oversampled, smooth pixmap transform |
| 🖥 **Full-screen reading** | F11 — black background, zero distractions |
| 📖 **Dual-page view** | Ctrl+2 — side-by-side spread with snap navigation |
| 🔍 **Full-text search** | Ctrl+F — highlights all matches, jumps with Enter |
| 🟡 **Highlight & underline** | Right-click selection — custom colours per type |
| ↶↷ **Undo / Redo** | Ctrl+Z / Ctrl+Y — for all annotation actions |
| 🗑️ **Delete annotations** | Right-click any existing highlight to remove it |
| 🌐 **Live translation panel** | Translates selected text into 10+ languages via Google Translate |
| 💡 **Hover-to-highlight** | Mouse over a sentence in the translation panel → that sentence glows teal in the PDF |
| ¶ **Paragraph translate mode** | Ctrl+P — tiny badge on every paragraph; click to translate the whole block |
| 🌙 **Eye-care filters** | 8 warm/night/sepia/dim overlays to reduce eye strain |
| 💾 **Auto-save prompt** | On close: overwrite in-place or save a clean copy |
| 📁 **Recent files** | Persisted in Windows registry via QSettings |
| 🔄 **Page rotation** | 90° left/right, all pages, coordinates recalculated |
| 🖱️ **Middle-click autoscroll** | Joystick-style smooth scrolling |

---

## Screenshots

> *Screenshots coming soon.*

---

## Quick Start

```bash
git clone https://github.com/akinel-omur/LucidLectorPDF.git
cd LucidLectorPDF
pip install -r requirements.txt
python main.py
```

**Requirements:** Python 3.11+, Windows (tested on Windows 10/11)

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+O` | Open PDF |
| `Ctrl+S` | Save annotations |
| `Ctrl+F` | Search |
| `Ctrl+P` | Paragraph translate mode |
| `Ctrl+2` | Toggle dual-page view |
| `Ctrl++` / `Ctrl+-` | Zoom in / out |
| `Ctrl+0` | Fit page |
| `Ctrl+Z` / `Ctrl+Y` | Undo / Redo |
| `PgDn` / `PgUp` | Next / previous page |
| `←` / `→` | Previous / next page |
| `F11` / `Esc` | Toggle full-screen |

---

## Build a Standalone `.exe`

```bash
pip install pyinstaller pillow
python tools/make_icon.py          # generates resources/icon.ico
pyinstaller --noconfirm --clean --windowed --onefile ^
    --name "LucidLectorPDF" ^
    --icon "resources/icon.ico" ^
    --add-data "resources/icon.ico;resources" ^
    main.py
```

Output: `dist/LucidLectorPDF.exe` (~70 MB, no installer needed).

---

## Project Structure

```
LucidLectorPDF/
├── main.py                      # Entry point
├── pdf_reader/
│   ├── __init__.py              # Version
│   ├── main_window.py           # QMainWindow — menus, toolbar, wiring
│   ├── pdf_view.py              # QGraphicsView — render, selection, context menu
│   ├── pdf_document.py          # PyMuPDF wrapper — render, search, annotations
│   ├── translator.py            # Async deep-translator + LRU cache
│   ├── translation_popup.py     # Right-side dock panel + sentence hover
│   ├── search_bar.py            # Ctrl+F search bar widget
│   ├── recent_files.py          # QSettings-backed recent files list
│   └── i18n.py                  # UI string translations (tr/en/de/fr/es/ru/…)
├── tools/
│   └── make_icon.py             # Generates icon.ico from icon.png
├── resources/
│   ├── icon.png
│   └── icon.ico
├── requirements.txt
└── LICENSE
```

---

## How the Hover-Highlight Works

1. `TranslationPanel` installs a `QObject` event filter on both `QPlainTextEdit` **viewports** (not the scroll area container).
2. On `MouseMove`, `cursorForPosition()` gives the character offset under the cursor.
3. For the **original-text panel**: a regex-based sentence splitter finds the sentence at that offset.
4. For the **translated-text panel**: the character position is mapped *proportionally* to the original text length (robust against translation sentence-count differences).
5. The sentence text is emitted via `sentence_hovered` → `PdfView.show_hover_highlight()`.
6. `PdfView` searches the PDF for the sentence text (full query first, then first-8-words fallback), paints teal `QGraphicsRectItem`s at Z-value 15, and forces a viewport repaint.
7. `sentence_left` (debounced 180 ms) clears the overlay.

---

## Dependencies

| Library | Purpose | License |
|---|---|---|
| [PyQt6](https://pypi.org/project/PyQt6/) | GUI framework | GPL-3 / Commercial |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | PDF rendering & annotations | AGPL-3.0 |
| [deep-translator](https://github.com/nidhaloff/deep-translator) | Google Translate wrapper | MIT |

---

## License

This project is distributed under the **GNU Affero General Public License v3.0 (AGPL-3.0)** — see [LICENSE](LICENSE).

AGPL-3.0 is chosen because PyMuPDF is also AGPL-3.0, and its copyleft clause requires any combined work to be distributed under the same license. If you need a more permissive license, consider obtaining a [commercial PyMuPDF license](https://artifex.com/licensing/) from Artifex, or replacing PyMuPDF with a BSD/MIT-licensed PDF library such as `pypdfium2`.

---

## Author

**Ömür Akınel** — built with [Claude](https://claude.ai) (Vibe Coding)  
📧 akinel@gmail.com
