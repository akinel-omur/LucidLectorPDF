"""Tests for pdf_reader.text_utils — pure functions, no Qt or PyMuPDF needed.

Run with:  python -m pytest
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdf_reader.text_utils import (  # noqa: E402
    search_variants,
    sentence_at,
    sentence_boundaries,
    sentence_index_of,
    sentences,
)


TWO = "First sentence. Second sentence."


class TestSentenceBoundaries:
    def test_empty(self):
        assert sentence_boundaries("") == []

    def test_single_without_terminator(self):
        assert sentence_boundaries("no terminator") == [(0, 13)]

    def test_splits_on_terminator(self):
        assert [TWO[s:e].strip() for s, e in sentence_boundaries(TWO)] == [
            "First sentence.",
            "Second sentence.",
        ]

    @pytest.mark.parametrize(
        "text",
        [
            "One. Two. Three.",
            "One.  Two.   Three.",          # multiple spaces
            "One.\r\nTwo.\r\nThree.",       # CRLF, as in many PDF text layers
            "One.\n\nTwo.\n\nThree.",       # blank lines between sentences
            "One. Two. Three",              # no terminator on the last one
        ],
    )
    def test_ranges_are_contiguous_and_complete(self, text):
        # sentence_at() depends on this: with a gap, an offset landing in the
        # separator would belong to no sentence and fall through to the
        # whole-text fallback.
        bounds = sentence_boundaries(text)
        assert bounds[0][0] == 0
        assert bounds[-1][1] == len(text)
        for (_, end), (nxt_start, _) in zip(bounds, bounds[1:]):
            assert end == nxt_start

    @pytest.mark.parametrize("sep", [" ", "  ", "\r\n", "\n\n", " \n "])
    def test_every_offset_maps_to_a_sentence(self, sep):
        text = f"First one.{sep}Second one."
        for pos in range(len(text)):
            # Never the fallback (which would return the whole string).
            assert sentence_at(text, pos) in ("First one.", "Second one.")

    @pytest.mark.parametrize("mark", [".", "!", "?", "…"])
    def test_every_terminator(self, mark):
        assert len(sentence_boundaries(f"One{mark} Two.")) == 2

    def test_boundaries_cover_text_in_order(self):
        text = "A one. B two! C three? D four"
        bounds = sentence_boundaries(text)
        assert all(s < e for s, e in bounds)
        assert [s for s, _ in bounds] == sorted(s for s, _ in bounds)
        assert bounds[-1][1] == len(text)

    def test_newline_counts_as_separator(self):
        assert len(sentence_boundaries("Line one.\nLine two.")) == 2

    def test_no_split_without_whitespace(self):
        # Decimals and abbreviations must not be torn apart.
        assert len(sentence_boundaries("Rate is 3.14 per unit.")) == 1


class TestSentenceAt:
    def test_finds_containing_sentence(self):
        assert sentence_at(TWO, 0) == "First sentence."
        assert sentence_at(TWO, 20) == "Second sentence."

    def test_position_past_end_falls_back(self):
        assert sentence_at(TWO, 999) == TWO

    def test_empty_text(self):
        assert sentence_at("", 0) == ""


class TestSentences:
    def test_strips_and_splits(self):
        assert sentences(TWO, min_length=1) == ["First sentence.", "Second sentence."]

    def test_min_length_filters_short_fragments(self):
        text = "12. This is a long enough sentence."
        assert sentences(text, min_length=8) == ["This is a long enough sentence."]

    def test_default_threshold_drops_page_numbers(self):
        assert sentences("7. A properly long sentence here.") == [
            "A properly long sentence here."
        ]

    def test_empty(self):
        assert sentences("") == []


class TestSentenceIndexOf:
    def test_exact_match(self):
        assert sentence_index_of(TWO, "Second sentence.") == 1

    def test_substring_fallback(self):
        assert sentence_index_of(TWO, "Second") == 1

    def test_tolerates_surrounding_whitespace(self):
        assert sentence_index_of(TWO, "  First sentence.  ") == 0

    def test_missing_returns_none(self):
        assert sentence_index_of(TWO, "Third") is None

    def test_empty_target_returns_none(self):
        assert sentence_index_of(TWO, "   ") is None


class TestSearchVariants:
    def test_empty(self):
        assert search_variants("") == []

    def test_short_text_has_one_variant(self):
        assert search_variants("Three word phrase") == ["Three word phrase"]

    def test_long_text_adds_prefix_variant(self):
        text = " ".join(f"w{i}" for i in range(20))
        variants = search_variants(text, max_words=8)
        assert len(variants) == 2
        assert variants[0] == text
        assert variants[1] == "w0 w1 w2 w3 w4 w5 w6 w7"

    def test_no_duplicate_when_prefix_equals_text(self):
        text = "a b c d"          # 4 words, max_words=8 → prefix == text
        assert search_variants(text, max_words=8) == [text]

    def test_longest_first(self):
        text = " ".join(f"w{i}" for i in range(20))
        lengths = [len(v) for v in search_variants(text)]
        assert lengths == sorted(lengths, reverse=True)
