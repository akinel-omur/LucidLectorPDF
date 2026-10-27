/**
 * Pure text helpers — JavaScript port of pdf_reader/text_utils.py.
 *
 * Deliberately free of DOM and PDF.js imports so the sentence logic stays
 * testable on its own, exactly like the Python original.
 */

// A sentence ends at .!?… followed by whitespace.
//
// The Python original stops there, on the argument that a heavier splitter
// buys little for hover highlighting. In practice it buys a lot: academic
// prose is full of "Drs.", "Fig.", "et al." and initials like "A. P. Sarnaik",
// and every one of them cut a sentence short — so the highlight in the panel
// and the one in the page ended mid-clause, at different places, and the
// sentence-to-sentence pairing with the translation drifted. Hence the two
// guards below. This is a deliberate divergence from text_utils.py.
//
// The closing-punctuation part is a second divergence: the Python pattern
// requires the terminator to sit right before the whitespace, so a sentence
// ending on a quote or bracket — `He called it "flow." The next…` — was never
// split at all. Allowing them here matches _SENT_END_PAT in pdf_document.py,
// which has always treated `.")` as a sentence ending.
const SENTENCE_SPLIT = /(?<=[.!?…]['"”’)\]]*)\s+/g;

/** Words that end in a period without ending a sentence. */
const ABBREVIATIONS = new Set([
  // titles and names
  'dr', 'drs', 'prof', 'mr', 'mrs', 'ms', 'st', 'jr', 'sr',
  // references and structure
  'fig', 'figs', 'eq', 'eqs', 'ref', 'refs', 'ch', 'chap', 'sec', 'vol',
  'no', 'nos', 'pp', 'p', 'ed', 'eds', 'edn', 'trans', 'rev', 'suppl',
  // latin and general
  'et', 'al', 'etc', 'eg', 'ie', 'cf', 'vs', 'viz', 'approx', 'ca', 'circa',
  // organisations
  'inc', 'ltd', 'co', 'corp', 'dept', 'univ', 'assoc',
  // units and measures
  'mg', 'ml', 'kg', 'cm', 'mm', 'hr', 'hrs', 'wk', 'mo', 'yr', 'min', 'max',
]);

const WORD_CHAR = /[\p{L}\p{N}]/u;

/**
 * Whether the period at `index` merely ends an abbreviation.
 *
 * Looks at the word immediately before it: a known abbreviation, or a lone
 * capital letter, which is an initial ("A. P. Sarnaik") rather than the end of
 * a thought.
 */
function endsAbbreviation(text, index) {
  if (text[index] !== '.') return false; // only periods are ambiguous
  let start = index;
  while (start > 0 && WORD_CHAR.test(text[start - 1])) start--;
  if (start === index) return false;

  const word = text.slice(start, index);
  if (word.length === 1 && word === word.toUpperCase() && /\p{L}/u.test(word)) {
    return true;
  }
  return ABBREVIATIONS.has(word.toLowerCase());
}

/**
 * Whether the text after `index` starts a new sentence.
 *
 * Sentences do not begin in lower case. When the next word does, the period
 * before it was punctuation inside the sentence, not the end of one.
 */
function startsNewSentence(text, index) {
  const next = text.slice(index).match(/\S/);
  if (!next) return true; // trailing whitespace: nothing follows to judge
  const char = next[0];
  return !(/\p{Ll}/u.test(char));
}

// Shortest run of characters still treated as a sentence. Below this it is a
// page number, a stray heading or a hyphenation artefact, and matching it
// against the PDF produces noise rather than a useful highlight.
export const MIN_SENTENCE_LENGTH = 8;

/**
 * Return [[start, end], …] character offsets for each sentence in `text`.
 *
 * Ranges are contiguous and cover the whole string: each one absorbs the
 * whitespace that follows its terminator. `sentenceAt` depends on that — with
 * a gap, an offset landing between two sentences would match neither and fall
 * through to the whole-text fallback.
 *
 * @param {string} text
 * @returns {Array<[number, number]>}
 */
export function sentenceBoundaries(text) {
  const result = [];
  let start = 0;
  // Fresh regex per call: /g regexes carry lastIndex between calls.
  const re = new RegExp(SENTENCE_SPLIT.source, 'g');
  let m;
  while ((m = re.exec(text)) !== null) {
    const end = m.index + m[0].length;
    // m.index is the first whitespace character; the terminator sits before
    // it, past any closing quote or bracket.
    let terminator = m.index - 1;
    while (terminator > start && /['"”’)\]]/.test(text[terminator])) terminator--;

    if (endsAbbreviation(text, terminator) || !startsNewSentence(text, end)) {
      if (re.lastIndex === m.index) re.lastIndex++;
      continue; // not a sentence end after all — keep going
    }

    result.push([start, end]);
    start = end;
    if (re.lastIndex === m.index) re.lastIndex++; // guard against zero-width
  }
  if (start < text.length) result.push([start, text.length]);
  return result;
}

/**
 * Stripped sentences of `text`, skipping ones shorter than `minLength`
 * characters (page numbers, stray headings, and the like).
 *
 * @param {string} text
 * @param {number} [minLength]
 * @returns {string[]}
 */
export function sentences(text, minLength = MIN_SENTENCE_LENGTH) {
  const out = [];
  for (const [start, end] of sentenceBoundaries(text)) {
    const sentence = text.slice(start, end).trim();
    if (sentence.length >= minLength) out.push(sentence);
  }
  return out;
}

/**
 * The sentence in `text` containing character offset `pos`.
 *
 * @param {string} text
 * @param {number} pos
 * @returns {string}
 */
export function sentenceAt(text, pos) {
  for (const [start, end] of sentenceBoundaries(text)) {
    if (start <= pos && pos < end) return text.slice(start, end).trim();
  }
  return text.trim(); // fallback: treat the whole text as one sentence
}

/**
 * Index (0-based) of the sentence in `text` whose stripped form equals
 * `target`; falls back to the first sentence containing it as a substring.
 *
 * @param {string} text
 * @param {string} target
 * @returns {number|null}
 */
export function sentenceIndexOf(text, target) {
  const needle = target.trim();
  if (!needle) return null;
  const bounds = sentenceBoundaries(text);
  for (let i = 0; i < bounds.length; i++) {
    const [s, e] = bounds[i];
    if (text.slice(s, e).trim() === needle) return i;
  }
  for (let i = 0; i < bounds.length; i++) {
    const [s, e] = bounds[i];
    if (text.slice(s, e).includes(needle)) return i;
  }
  return null;
}

/**
 * Query strings to try when locating `text` inside a PDF, longest first.
 *
 * PDF text layers differ from extracted text in whitespace, hyphenation and
 * ligatures, so an exact match often fails. Falling back to the opening words
 * finds the right line far more often than giving up.
 *
 * @param {string} text
 * @param {number} [maxWords]
 * @returns {string[]}
 */
export function searchVariants(text, maxWords = 8) {
  const trimmed = text.trim();
  if (!trimmed) return [];
  const variants = [trimmed];
  const words = trimmed.split(/\s+/);
  if (words.length > 3) {
    const short = words.slice(0, maxWords).join(' ');
    if (short !== trimmed) variants.push(short);
  }
  return variants;
}

/**
 * Collapse all whitespace runs to single spaces and trim — the normalisation
 * used everywhere a PDF text layer is compared against user-visible text.
 *
 * @param {string} text
 * @returns {string}
 */
export function normalizeWhitespace(text) {
  return text.replace(/\s+/g, ' ').trim();
}
