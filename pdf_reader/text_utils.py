"""Pure text helpers shared by the PDF view and the translation panel.

Kept free of Qt and PyMuPDF imports so the sentence logic can be unit-tested
without a running application.
"""
from __future__ import annotations

import re

# A sentence ends at .!?… followed by whitespace. Deliberately simple: PDF text
# is already noisy, and a heavier splitter (abbreviations, decimals, citations)
# would add failure modes without much gain for hover highlighting.
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?…])\s+')

# Shortest run of characters still treated as a sentence. Anything below this
# is a page number, a stray heading or a hyphenation artefact, and matching it
# against the PDF produces noise rather than a useful highlight.
MIN_SENTENCE_LENGTH = 8


def sentence_boundaries(text: str) -> list[tuple[int, int]]:
    """Return [(start, end), …] character offsets for each sentence in *text*.

    Ranges are contiguous and cover the whole string: each one absorbs the
    whitespace that follows its terminator. :func:`sentence_at` depends on
    that — with a gap, an offset landing between two sentences would match
    neither and fall through to the whole-text fallback. PDF text layers are
    full of multi-character separators (``"\\r\\n"``, double spaces, blank
    lines), so the separator is consumed in full rather than one character at
    a time. Callers that display the text should strip it.
    """
    result: list[tuple[int, int]] = []
    start = 0
    for m in _SENTENCE_SPLIT.finditer(text):
        result.append((start, m.end()))
        start = m.end()
    if start < len(text):
        result.append((start, len(text)))
    return result


def sentences(text: str, min_length: int = MIN_SENTENCE_LENGTH) -> list[str]:
    """Return the stripped sentences of *text*, skipping ones shorter than
    *min_length* characters (page numbers, stray headings, and the like)."""
    out: list[str] = []
    for start, end in sentence_boundaries(text):
        sentence = text[start:end].strip()
        if len(sentence) >= min_length:
            out.append(sentence)
    return out


def sentence_at(text: str, pos: int) -> str:
    """Return the sentence in *text* containing character offset *pos*."""
    for start, end in sentence_boundaries(text):
        if start <= pos < end:
            return text[start:end].strip()
    return text.strip()   # fallback: treat the whole text as one sentence


def sentence_index_of(text: str, target: str) -> int | None:
    """Index (0-based) of the sentence in *text* whose stripped form equals
    *target*; falls back to the first sentence containing it as a substring."""
    target = target.strip()
    if not target:
        return None
    bounds = sentence_boundaries(text)
    for i, (s, e) in enumerate(bounds):
        if text[s:e].strip() == target:
            return i
    for i, (s, e) in enumerate(bounds):
        if target in text[s:e]:
            return i
    return None


def search_variants(text: str, max_words: int = 8) -> list[str]:
    """Query strings to try when locating *text* inside a PDF, longest first.

    PDF text layers differ from extracted text in whitespace, hyphenation and
    ligatures, so an exact match often fails. Falling back to the opening words
    finds the right line far more often than giving up.
    """
    text = text.strip()
    if not text:
        return []
    variants = [text]
    words = text.split()
    if len(words) > 3:
        short = " ".join(words[:max_words])
        if short != text:
            variants.append(short)
    return variants
