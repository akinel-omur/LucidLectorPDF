/**
 * Paragraph reconstruction — the layer PDF.js does not provide.
 *
 * PyMuPDF hands the desktop app ready-made text *blocks* via
 * `page.get_text("blocks")`. PDF.js returns only a flat stream of positioned
 * text runs, so the structure has to be rebuilt here: runs → lines → columns →
 * blocks. Only then can the cross-column and cross-page merging heuristic from
 * pdf_document.py run on top.
 *
 * The rebuilding is where the judgement lives, and three things in real
 * academic PDFs break the obvious approach:
 *
 *   - Subscripts and superscripts (CO₂, Vᴛ, footnote marks) sit at their own
 *     vertical offset, so clustering lines by baseline distance tears a line
 *     apart at every one of them.
 *   - Two-column pages put unrelated text at the same height, so lines must be
 *     cut at the gutter and then read column by column, not straight down.
 *   - Books separate paragraphs by indenting the first line and nothing else.
 *     Grouping on vertical gaps alone silently welds those paragraphs together.
 */

// A block ends a paragraph if it ends with sentence-final punctuation
// (optionally followed by closing quotes/brackets).
const SENT_END_PAT = /[.!?…]['"”’)\]]*$/;

// A hyphen at the end of a word indicates a soft line/column/page break that
// splits the word. Joining should drop the hyphen.
const HYPHEN_PAT = /[\p{L}\p{N}]-$/u;

// A "current" block of at least this many characters that does not end with a
// sentence terminator is treated as a paragraph continuing into the next
// block. Shorter blocks (likely headings or captions) stay standalone so they
// are not swallowed into a neighbouring paragraph.
const PARAGRAPH_LIKE = 100;

// Blocks shorter than this are page numbers, running headers and captions.
const MIN_BLOCK_CHARS = 30;

// Tuning, all relative to the page's median line height so they hold at any
// font size or zoom.
const ROW_OVERLAP_RATIO = 0.4;   // vertical overlap that keeps runs on one line
const GUTTER_MIN_RATIO = 1.2;    // narrowest band of white that can be a gutter
const GUTTER_ROW_SHARE = 0.08;   // share of rows a gutter may be crossed by
const LINE_GAP_SLACK = 0.35;     // extra gap over the page's own leading = break
const INDENT_RATIO = 0.6;        // indent that marks a new paragraph
const SMALL_RUN_RATIO = 0.75;    // below this share of line height: a sub/superscript
const WIDE_LINE_RATIO = 1.6;     // width at which a line may span every column

/**
 * @typedef {Object} TextRun
 * @property {string} str   Text of the run.
 * @property {number} x     Left edge, PDF points, origin top-left.
 * @property {number} y     Top edge, PDF points, origin top-left.
 * @property {number} w     Width in PDF points.
 * @property {number} h     Height (font size) in PDF points.
 */

/**
 * @typedef {Object} Block
 * @property {string} text
 * @property {number} x0
 * @property {number} y0
 * @property {number} x1
 * @property {number} y1
 */

const median = (nums) => {
  if (!nums.length) return 0;
  const sorted = [...nums].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
};

const overlap = (a0, a1, b0, b1) => Math.min(a1, b1) - Math.max(a0, b0);

/**
 * Group positioned text runs into visual lines, splitting at column gutters.
 *
 * Runs join a line when their vertical extents overlap, rather than when their
 * tops are close. That is what keeps a subscript with the line it belongs to:
 * `CO₂` sits lower and is smaller, so its top is nowhere near the line's, but
 * it still lies inside the line's vertical span.
 *
 * @param {TextRun[]} runs
 * @returns {Block[]} one entry per visual line
 */
export function groupIntoLines(runs) {
  const usable = runs.filter((r) => r.str && r.str.trim());
  if (!usable.length) return [];

  const medH = median(usable.map((r) => r.h)) || 10;

  // Body text defines where the lines are; sub- and superscripts attach to
  // them afterwards. Letting a small run open a row of its own is what tore
  // lines apart: a superscript sits above the text it belongs to, so when it
  // comes first in document order it anchors a row the body text then fails
  // to overlap enough to join.
  const primary = usable.filter((r) => r.h >= medH * SMALL_RUN_RATIO);
  const small = primary.length ? usable.filter((r) => r.h < medH * SMALL_RUN_RATIO) : [];
  const base = primary.length ? primary : usable;

  const rows = [];
  let row = null;
  for (const run of [...base].sort((a, b) => a.y - b.y || a.x - b.x)) {
    const joins =
      row &&
      overlap(row.top, row.bottom, run.y, run.y + run.h) >=
        Math.min(row.height, run.h) * ROW_OVERLAP_RATIO;

    if (joins) {
      row.runs.push(run);
      if (run.h > row.height) {
        row.top = run.y;
        row.bottom = run.y + run.h;
        row.height = run.h;
      }
    } else {
      row = { runs: [run], top: run.y, bottom: run.y + run.h, height: run.h };
      rows.push(row);
    }
  }

  for (const run of small) {
    let best = null;
    let bestOverlap = 0;
    for (const candidate of rows) {
      const ov = overlap(candidate.top, candidate.bottom, run.y, run.y + run.h);
      if (ov > bestOverlap) {
        bestOverlap = ov;
        best = candidate;
      }
    }
    if (best) best.runs.push(run);
    else rows.push({ runs: [run], top: run.y, bottom: run.y + run.h, height: run.h });
  }

  rows.sort((a, b) => a.top - b.top);

  const gutters = detectGutters(rows, medH);
  const lines = [];
  for (const entry of rows) lines.push(...splitAtGutters(entry.runs, gutters));
  return lines.filter((line) => line.text.trim());
}

/**
 * Find the columns' white gutters by looking down the whole page at once.
 *
 * Judging each row on its own does not work. Justified text stretches its
 * word spaces — in a real textbook page they reach 14pt against a 20pt
 * gutter — so no per-row threshold separates the two without also slicing
 * ordinary lines in half.
 *
 * Seen from above, though, the difference is obvious: a gutter is a vertical
 * band of white running the height of the page, while a stretched word space
 * is white in one row and covered in the next. So this counts, for each
 * horizontal position, how many rows put text there, and takes the bands that
 * almost nobody crosses. "Almost" matters: one full-width heading should not
 * hide a gutter that four hundred lines respect.
 *
 * @param {Array<{runs: TextRun[]}>} rows
 * @param {number} medH
 * @returns {Array<[number, number]>} gutter bands in PDF points
 */
function detectGutters(rows, medH) {
  const runs = rows.flatMap((row) => row.runs);
  if (runs.length < 2) return [];

  const minX = Math.min(...runs.map((r) => r.x));
  const maxX = Math.max(...runs.map((r) => r.x + r.w));
  const width = Math.ceil(maxX - minX);
  if (width <= 0) return [];

  const covering = new Uint16Array(width + 1);
  for (const row of rows) {
    // One row contributes at most once per position, so a wide heading counts
    // the same as a single line of body text.
    const seen = new Uint8Array(width + 1);
    for (const run of row.runs) {
      const from = Math.max(0, Math.floor(run.x - minX));
      const to = Math.min(width, Math.ceil(run.x + run.w - minX));
      for (let i = from; i < to; i++) seen[i] = 1;
    }
    for (let i = 0; i <= width; i++) covering[i] += seen[i];
  }

  // No rounding up to 1: on a page with a handful of rows that would make
  // every position "almost uncrossed" and turn ordinary word spaces into
  // gutters.
  const allowed = Math.floor(rows.length * GUTTER_ROW_SHARE);
  const minWidth = medH * GUTTER_MIN_RATIO;
  const gutters = [];
  let start = -1;

  for (let i = 0; i <= width + 1; i++) {
    const clear = i <= width && covering[i] <= allowed;
    if (clear) {
      if (start < 0) start = i;
    } else if (start >= 0) {
      if (i - start >= minWidth) gutters.push([minX + start, minX + i]);
      start = -1;
    }
  }
  return gutters;
}

/** Cut a row wherever one of the page's gutters passes through it. */
function splitAtGutters(runs, gutters) {
  const sorted = [...runs].sort((a, b) => a.x - b.x);
  if (sorted.length < 2 || !gutters.length) return [lineFromRuns(sorted)];

  const lines = [];
  let segment = [sorted[0]];
  for (let i = 1; i < sorted.length; i++) {
    const from = sorted[i - 1].x + sorted[i - 1].w;
    const to = sorted[i].x;
    const crosses = gutters.some(([g0, g1]) => {
      const centre = (g0 + g1) / 2;
      return centre >= from && centre <= to;
    });
    if (crosses) {
      lines.push(lineFromRuns(segment));
      segment = [sorted[i]];
    } else {
      segment.push(sorted[i]);
    }
  }
  lines.push(lineFromRuns(segment));
  return lines;
}

function lineFromRuns(runs) {
  let text = '';
  for (const run of runs) {
    // PDF.js runs often lack the space that visually separates them.
    if (text && !/\s$/.test(text) && !/^\s/.test(run.str)) text += ' ';
    text += run.str;
  }
  return {
    text: text.replace(/\s+/g, ' ').trim(),
    x0: Math.min(...runs.map((r) => r.x)),
    y0: Math.min(...runs.map((r) => r.y)),
    x1: Math.max(...runs.map((r) => r.x + r.w)),
    y1: Math.max(...runs.map((r) => r.y + r.h)),
  };
}

/**
 * Put lines in reading order: down each column, columns left to right, with
 * full-width lines (titles, section headings) closing one band and opening
 * the next.
 *
 * Sorting by position alone interleaves the columns of a two-column page,
 * which then merges paragraphs that merely happen to sit at the same height.
 *
 * "Full width" is judged against the other lines, not against the page: on a
 * single-column page every line spans the text area, and calling them all
 * separators would put each one in its own band and lose the left margin that
 * makes an indent detectable.
 *
 * @returns {Array<Block & {columnLeft: number, isSeparator: boolean}>}
 */
function orderForReading(lines) {
  const medW = median(lines.map((l) => l.x1 - l.x0)) || 1;
  const isWide = (line) => line.x1 - line.x0 > medW * WIDE_LINE_RATIO;

  const narrow = lines.filter((line) => !isWide(line));
  const columns = detectColumns(narrow.length ? narrow : lines);
  // A wide line only separates anything when there are columns to separate.
  const separates = columns.length > 1 ? isWide : () => false;

  const sorted = [...lines].sort((a, b) => a.y0 - b.y0 || a.x0 - b.x0);
  const out = [];
  let band = [];

  const flush = () => {
    if (band.length) out.push(...orderBand(band));
    band = [];
  };

  for (const line of sorted) {
    if (separates(line)) {
      flush();
      out.push({ ...line, columnLeft: line.x0, isSeparator: true });
    } else {
      band.push(line);
    }
  }
  flush();
  return out;
}

/** Cluster lines into columns by horizontal overlap, left to right. */
function detectColumns(lines) {
  const columns = [];
  for (const line of [...lines].sort((a, b) => a.x0 - b.x0)) {
    const target = columns.find((col) => {
      const ov = overlap(col.x0, col.x1, line.x0, line.x1);
      return ov > Math.min(col.x1 - col.x0, line.x1 - line.x0) * 0.5;
    });
    if (target) {
      target.x0 = Math.min(target.x0, line.x0);
      target.x1 = Math.max(target.x1, line.x1);
      target.lines.push(line);
    } else {
      columns.push({ x0: line.x0, x1: line.x1, lines: [line] });
    }
  }
  return columns.sort((a, b) => a.x0 - b.x0);
}

/** Read one band's columns left to right, each top to bottom. */
function orderBand(lines) {
  return detectColumns(lines).flatMap((col) =>
    col.lines
      .sort((a, b) => a.y0 - b.y0)
      // The column's left edge is the unindented margin, which is what makes
      // an indented first line detectable further down.
      .map((line) => ({ ...line, columnLeft: col.x0, isSeparator: false })),
  );
}

/**
 * Group lines into blocks — the equivalent of PyMuPDF's text blocks.
 *
 * A line continues the current block when it follows immediately below, in the
 * same column, and is not indented. An indent starts a new paragraph even with
 * no extra leading, which is how most books separate them.
 *
 * @param {Block[]} lines
 * @returns {Block[]}
 */
export function groupIntoBlocks(lines) {
  if (!lines.length) return [];

  const medH = median(lines.map((l) => l.y1 - l.y0)) || 10;
  const ordered = orderForReading(lines);

  // What "one line below" means on this page, measured rather than assumed.
  // Books set paragraphs apart by a few points of extra space, which a fixed
  // threshold either misses entirely or mistakes for the normal leading; the
  // page's own median gap is the only reliable reference.
  const gaps = [];
  for (let i = 1; i < ordered.length; i++) {
    const gap = ordered[i].y0 - ordered[i - 1].y1;
    if (gap >= -medH * 0.5 && gap < medH * 3) gaps.push(gap);
  }
  const leading = median(gaps);
  const maxGap = Math.max(leading + medH * LINE_GAP_SLACK, medH * 0.5);

  const blocks = [];
  let current = null;
  let previous = null;

  for (const line of ordered) {
    if (!current) {
      current = stripMeta(line);
      previous = line;
      continue;
    }

    const gap = line.y0 - previous.y1;
    const follows = gap >= -medH * 0.5 && gap <= maxGap;
    const ov = overlap(current.x0, current.x1, line.x0, line.x1);
    const sameColumn = ov > Math.min(current.x1 - current.x0, line.x1 - line.x0) * 0.35;
    const indented = line.x0 - line.columnLeft > medH * INDENT_RATIO;
    // A heading spanning the columns belongs to neither the text above nor
    // the text below it.
    const across = line.isSeparator || previous.isSeparator;

    if (follows && sameColumn && !indented && !across) {
      current = mergeLineInto(current, line);
    } else {
      blocks.push(current);
      current = stripMeta(line);
    }
    previous = line;
  }

  if (current) blocks.push(current);
  return blocks;
}

function stripMeta({ text, x0, y0, x1, y1 }) {
  return { text, x0, y0, x1, y1 };
}

function mergeLineInto(block, line) {
  const tail = block.text.replace(/\s+$/, '');
  const text = HYPHEN_PAT.test(tail)
    ? tail.replace(/-$/, '') + line.text.replace(/^\s+/, '')
    : `${tail} ${line.text.replace(/^\s+/, '')}`;
  return {
    text,
    x0: Math.min(block.x0, line.x0),
    y0: Math.min(block.y0, line.y0),
    x1: Math.max(block.x1, line.x1),
    y1: Math.max(block.y1, line.y1),
  };
}

/**
 * Substantial text blocks on one page — the port of `PdfDocument.paragraphs`.
 * Short blocks (page numbers, captions, running heads) are dropped.
 *
 * @param {TextRun[]} runs
 * @returns {Block[]}
 */
export function blocksForPage(runs) {
  return groupIntoBlocks(groupIntoLines(runs)).filter(
    (b) => b.text.length >= MIN_BLOCK_CHARS,
  );
}

/**
 * @typedef {Object} MergedParagraph
 * @property {string} text  The full merged paragraph text.
 * @property {Array<{page:number, rect:[number,number,number,number]}>} blocks
 */

/**
 * Walk pages in reading order and merge blocks belonging to the same paragraph
 * but split across columns or pages. Direct port of
 * `PdfDocument.merged_paragraphs`.
 *
 * A block continues the previous one when the previous text ends mid-word
 * (trailing hyphen) or mid-sentence while already being paragraph-sized. The
 * next block is *not* required to start lowercase: cross-page continuations
 * frequently begin a new sentence on the new page.
 *
 * @param {Block[][]} pageBlocks  blocksForPage() output, indexed by page.
 * @returns {MergedParagraph[]}
 */
export function mergeParagraphs(pageBlocks) {
  const result = [];
  let current = null;

  for (let pi = 0; pi < pageBlocks.length; pi++) {
    for (const block of pageBlocks[pi] || []) {
      const text = block.text;
      if (!text) continue;

      let isCont = false;
      if (current !== null) {
        const tail = current.text.replace(/\s+$/, '');
        if (HYPHEN_PAT.test(tail)) {
          isCont = true; // word split across the boundary
        } else if (!SENT_END_PAT.test(tail)) {
          isCont =
            current.text.length >= PARAGRAPH_LIKE && continuesSentence(text);
        }
      }

      const entry = { page: pi, rect: [block.x0, block.y0, block.x1, block.y1] };

      if (isCont && current !== null) {
        const tail = current.text.replace(/\s+$/, '');
        current.text = HYPHEN_PAT.test(tail)
          ? tail.replace(/-$/, '') + text.replace(/^\s+/, '')
          : `${tail} ${text.replace(/^\s+/, '')}`;
        current.blocks.push(entry);
      } else {
        if (current !== null) result.push(current);
        current = { text, blocks: [entry] };
      }
    }
  }

  if (current !== null) result.push(current);
  return result;
}

/**
 * Whether `text` reads as the continuation of an unfinished sentence.
 *
 * pdf_document.py merges on the previous block alone: if it does not end in a
 * terminator and is paragraph-sized, whatever follows is treated as its
 * continuation. On a book that runs away. A reference list ending "...and
 * secondary measures. Respir" has no terminator, so it swallowed the chapter
 * title on the next page, then the author line, then the first paragraph of
 * the chapter — one badge, four unrelated things, and a translation of all of
 * them at once.
 *
 * The missing test is on the *other* side of the break. A paragraph split
 * mid-sentence resumes mid-sentence, so its continuation starts lower case (or
 * with a digit or bracket, as citations do). A chapter title starts with a
 * capital, and a capital is the signal that something new has begun.
 *
 * The Python comment argues the opposite — that cross-page continuations often
 * begin a new sentence — but a block that ends a sentence properly already
 * fails the terminator test above and never reaches here.
 */
function continuesSentence(text) {
  const first = text.trimStart()[0];
  if (!first) return false;
  if (/\p{Lu}/u.test(first)) return false;   // a capital starts something new
  return true;
}

/**
 * Index merged paragraphs by page so each on-page block can carry a marker
 * that translates the whole (possibly multi-page) paragraph. Port of
 * `PdfDocument.paragraphs_for_page`.
 *
 * @param {MergedParagraph[]} paragraphs
 * @returns {Map<number, Array<{rect:[number,number,number,number], text:string}>>}
 */
export function indexByPage(paragraphs) {
  const index = new Map();
  for (const para of paragraphs) {
    for (const { page, rect } of para.blocks) {
      if (!index.has(page)) index.set(page, []);
      index.get(page).push({ rect, text: para.text });
    }
  }
  return index;
}
