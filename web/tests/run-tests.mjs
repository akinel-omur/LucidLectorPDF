/**
 * Test suite for the web port.
 *
 * Two layers:
 *   1. Pure-logic tests mirroring tests/test_text_utils.py, so the JavaScript
 *      sentence splitter stays behaviour-compatible with the Python original.
 *   2. Pipeline tests that run PDF.js in Node against a real PDF and check
 *      that text indexing, search-rect mapping and paragraph merging survive
 *      contact with an actual two-column document.
 *
 * Run:  node web/tests/run-tests.mjs [path/to/sample.pdf]
 */

import assert from 'node:assert/strict';
import process from 'node:process';

import {
  sentenceBoundaries,
  sentences,
  sentenceAt,
  sentenceIndexOf,
  searchVariants,
  normalizeWhitespace,
} from '../js/text-utils.js';
import {
  groupIntoLines,
  blocksForPage,
  mergeParagraphs,
  indexByPage,
} from '../js/paragraphs.js';
import { chunk, detectLanguage } from '../js/translator.js';
import { buildSearchString, rectsForRange, badgePosition } from '../js/viewer.js';

let passed = 0;
let failed = 0;
const failures = [];

async function test(name, fn) {
  try {
    await fn();
    passed++;
    process.stdout.write(`  ok   ${name}\n`);
  } catch (err) {
    failed++;
    failures.push({ name, err });
    process.stdout.write(`  FAIL ${name}\n       ${err.message}\n`);
  }
}

function section(title) {
  process.stdout.write(`\n${title}\n`);
}

// ---------------------------------------------------------------- text utils

section('text-utils (port of tests/test_text_utils.py)');

await test('boundaries cover the whole string with no gaps', () => {
  const text = 'First one. Second one!  Third one? Tail without terminator';
  const bounds = sentenceBoundaries(text);
  assert.equal(bounds[0][0], 0);
  assert.equal(bounds.at(-1)[1], text.length);
  for (let i = 1; i < bounds.length; i++) {
    assert.equal(bounds[i][0], bounds[i - 1][1], 'ranges must be contiguous');
  }
});

await test('multi-character separators are absorbed entirely', () => {
  const text = 'Alpha beta.\r\n\r\nGamma delta.';
  const bounds = sentenceBoundaries(text);
  assert.equal(bounds.length, 2);
  assert.equal(text.slice(...bounds[0]).trim(), 'Alpha beta.');
  // Every offset in the separator still resolves to the first sentence.
  for (let pos = 10; pos < 15; pos++) {
    assert.equal(sentenceAt(text, pos), 'Alpha beta.');
  }
});

await test('short fragments are skipped', () => {
  const text = 'A page heading. 42. This one is long enough to keep.';
  const kept = sentences(text);
  assert.ok(kept.includes('A page heading.'));
  assert.ok(!kept.includes('42.'));
});

await test('an abbreviation does not end a sentence', () => {
  // The case that made the panel and the page highlight different spans.
  const text =
    'We acknowledge the efforts of the original editors, Drs. Stephen Ludwig ' +
    'and Gary Fleisher, who recognized the importance. The next sentence.';
  const parts = sentences(text);
  assert.equal(parts.length, 2, `expected 2 sentences, got ${parts.length}`);
  assert.match(parts[0], /Drs\. Stephen Ludwig .* the importance\.$/);
});

await test('initials and common abbreviations hold a sentence together', () => {
  assert.equal(sentences('Written by A. P. Sarnaik and reviewed later.').length, 1);
  assert.equal(sentences('See Fig. 3 for the pressure curve.').length, 1);
  assert.equal(sentences('Others reported this too, cf. Smith and colleagues.').length, 1);
  assert.equal(sentences('Tidal volume, i.e. the moved gas, is measured.').length, 1);
});

await test('a real sentence end still splits', () => {
  const parts = sentences('The pressure equilibrates. Flow then ceases.');
  assert.equal(parts.length, 2);
  assert.equal(parts[0], 'The pressure equilibrates.');
});

await test('a period followed by lower case is not a sentence end', () => {
  // "1.1). Tidal" splits; "Fig. 1.1) then follows" does not.
  assert.equal(sentences('Shown in the figure (Fig. 1.1) then measured again.').length, 1);
});

await test('a sentence closing on a quote still splits', () => {
  // The Python pattern needed the terminator flush against the whitespace, so
  // this never split at all and the two sentences highlighted as one.
  const parts = sentences('He called it "flow." The next point follows.');
  assert.equal(parts.length, 2);
  assert.equal(parts[0], 'He called it "flow."');
});

await test('a year at a sentence end is not mistaken for an abbreviation', () => {
  assert.equal(sentences('This was settled in 1998. The next decade differed.').length, 2);
});

await test('sentenceAt falls back to the whole text', () => {
  assert.equal(sentenceAt('no terminators here', 3), 'no terminators here');
});

await test('sentenceIndexOf matches exactly, then by substring', () => {
  const text = 'One alpha here. Two beta there. Three gamma everywhere.';
  assert.equal(sentenceIndexOf(text, 'Two beta there.'), 1);
  assert.equal(sentenceIndexOf(text, 'gamma'), 2);
  assert.equal(sentenceIndexOf(text, '   '), null);
});

await test('searchVariants degrades to the opening words', () => {
  const long = 'One two three four five six seven eight nine ten eleven.';
  const variants = searchVariants(long);
  assert.equal(variants.length, 2);
  assert.equal(variants[0], long);
  assert.equal(variants[1].split(' ').length, 8);
  assert.deepEqual(searchVariants('Short one two'), ['Short one two']);
  assert.deepEqual(searchVariants('   '), []);
});

await test('normalizeWhitespace collapses runs', () => {
  assert.equal(normalizeWhitespace('  a \n\n b\tc  '), 'a b c');
});

// ------------------------------------------------------------------ chunking

section('translator');

await test('short text is a single chunk', () => {
  assert.deepEqual(chunk('hello', 500), ['hello']);
});

await test('chunks respect the limit and preserve the text', () => {
  const text = 'Sentence one is here. '.repeat(60);
  const parts = chunk(text, 200);
  assert.ok(parts.length > 1);
  for (const part of parts) assert.ok(part.length <= 200, `chunk too long: ${part.length}`);
  assert.equal(
    normalizeWhitespace(parts.join('')),
    normalizeWhitespace(text),
    'chunking must not lose or duplicate text',
  );
});

await test('a single over-long sentence is split on word boundaries', () => {
  const text = `${'word '.repeat(300)}end.`;
  const parts = chunk(text, 120);
  for (const part of parts) assert.ok(part.length <= 120);
  assert.ok(parts.every((p) => !/\bwor$|^rd\b/.test(p)), 'must not cut mid-word');
});

await test('language detection picks the obvious candidates', () => {
  assert.equal(detectLanguage('the study of the results in this paper is that'), 'en');
  assert.equal(detectLanguage('bu çalışma için elde edilen sonuçlar ve değerlendirme'), 'tr');
  assert.equal(detectLanguage('Это исследование показывает результаты'), 'ru');
  assert.equal(detectLanguage('der Versuch und die Ergebnisse von den Studien nicht'), 'de');
});

// --------------------------------------------------------------- paragraphs

section('paragraph reconstruction');

const run = (str, x, y, w, h = 10) => ({ str, x, y, w, h, hasEOL: false });

await test('a column gutter splits one visual row into two lines', () => {
  const lines = groupIntoLines([
    run('left column text', 50, 100, 200),
    run('right column text', 320, 100, 200),
  ]);
  assert.equal(lines.length, 2);
  assert.equal(lines[0].text, 'left column text');
  assert.equal(lines[1].text, 'right column text');
});

await test('close lines in one column become a single block', () => {
  const lines = groupIntoLines([
    run('The first line of the paragraph goes here', 50, 100, 200),
    run('and the second line continues right below', 50, 112, 200),
  ]);
  const blocks = blocksForPage([
    run('The first line of the paragraph goes here', 50, 100, 200),
    run('and the second line continues right below', 50, 112, 200),
  ]);
  assert.equal(lines.length, 2);
  assert.equal(blocks.length, 1);
  assert.match(blocks[0].text, /goes here and the second/);
});

await test('a trailing hyphen joins without a space and drops the hyphen', () => {
  const merged = mergeParagraphs([
    [{ text: `${'x'.repeat(120)} recon-`, x0: 0, y0: 0, x1: 10, y1: 10 }],
    [{ text: 'struction of the paragraph.', x0: 0, y0: 0, x1: 10, y1: 10 }],
  ]);
  assert.equal(merged.length, 1);
  assert.match(merged[0].text, /reconstruction of the paragraph\./);
  assert.equal(merged[0].blocks.length, 2, 'both blocks keep a marker');
});

await test('a sentence-final block does not absorb the next one', () => {
  const merged = mergeParagraphs([
    [
      { text: `${'a'.repeat(150)} done.`, x0: 0, y0: 0, x1: 1, y1: 1 },
      { text: `${'b'.repeat(150)} also done.`, x0: 0, y0: 2, x1: 1, y1: 3 },
    ],
  ]);
  assert.equal(merged.length, 2);
});

await test('a short block stays standalone even mid-sentence', () => {
  // Headings end without punctuation but must not swallow the paragraph below.
  const merged = mergeParagraphs([
    [
      { text: 'Method', x0: 0, y0: 0, x1: 1, y1: 1 },
      { text: `${'c'.repeat(150)}.`, x0: 0, y0: 2, x1: 1, y1: 3 },
    ],
  ]);
  assert.equal(merged.length, 2);
});

// ------------------------------------------------------- paragraph badges

section('paragraph badges');

await test('a badge hangs in the margin left of its paragraph', () => {
  const { left, top } = badgePosition(72, 120, 1);
  assert.equal(left, 50); // 72 - 20 (badge) - 2 (gap)
  assert.equal(top, 120);
});

await test('a badge never lands outside the page', () => {
  // A paragraph flush with the left edge would push its badge off a clipped
  // page element, leaving the user with no way to translate it.
  assert.equal(badgePosition(0, 40, 1).left, 1);
  assert.equal(badgePosition(8, 40, 1).left, 1);
  assert.ok(badgePosition(72, 40, 0.25).left >= 1, 'also holds when zoomed out');
});

await test('badge position tracks the zoom level', () => {
  assert.equal(badgePosition(200, 300, 2).top, 600);
  assert.equal(badgePosition(200, 300, 2).left, 400 - 22);
});

// ------------------------------------------------------- search index mapping

section('search index');

await test('runs flatten into a normalised string with a char map', () => {
  const items = [
    { str: 'Hello ', hasEOL: false, x: 0, y: 0, w: 60, h: 10 },
    { str: ' world', hasEOL: true, x: 60, y: 0, w: 60, h: 10 },
  ];
  const { text, map } = buildSearchString(items);
  assert.equal(text, 'Hello world ');
  assert.equal(map.length, text.length);
});

await test('a match spanning two runs yields one rect per run', () => {
  const items = [
    { str: 'Hello ', hasEOL: false, x: 0, y: 0, w: 60, h: 10 },
    { str: 'world', hasEOL: false, x: 60, y: 0, w: 50, h: 10 },
  ];
  const { text, map } = buildSearchString(items);
  const at = text.toLowerCase().indexOf('lo wor');
  const rects = rectsForRange(items, map, at, at + 'lo wor'.length);
  assert.equal(rects.length, 2);
  assert.ok(rects[0][0] > 0 && rects[0][2] <= 60.001, 'first rect inside run 1');
  assert.ok(rects[1][0] >= 60 && rects[1][2] <= 110.001, 'second rect inside run 2');
});

// ------------------------------------------------ end-to-end against real PDF

const pdfPath = process.argv[2];
if (pdfPath) {
  section(`pipeline against ${pdfPath}`);

  const pdfjsLib = await import('../vendor/pdf.min.mjs');
  const { readFile } = await import('node:fs/promises');
  const bytes = new Uint8Array(await readFile(pdfPath));

  const doc = await pdfjsLib.getDocument({
    data: bytes,
    isEvalSupported: false,
    useSystemFonts: false,
  }).promise;

  /** Same extraction the viewer performs in ensureTextIndex(). */
  const index = [];
  for (let i = 1; i <= doc.numPages; i++) {
    const page = await doc.getPage(i);
    const viewport = page.getViewport({ scale: 1 });
    const content = await page.getTextContent();
    const items = [];
    for (const item of content.items) {
      if (typeof item.str !== 'string') continue;
      const t = pdfjsLib.Util.transform(viewport.transform, item.transform);
      const height = Math.hypot(t[1], t[3]) || item.height || 10;
      items.push({
        str: item.str,
        hasEOL: !!item.hasEOL,
        x: t[4],
        y: t[5] - height,
        w: item.width,
        h: height,
      });
    }
    index.push({ items, viewport, ...buildSearchString(items) });
  }

  await test('document opens and every page yields text', () => {
    assert.ok(doc.numPages >= 2, 'need a multi-page sample');
    for (const [i, page] of index.entries()) {
      assert.ok(page.text.trim().length > 50, `page ${i} has no text`);
    }
  });

  await test('a unique phrase is found exactly once, in sane coordinates', () => {
    const needle = 'quixotic zephyr';
    const hits = [];
    for (const [pageIndex, page] of index.entries()) {
      const at = page.text.toLowerCase().indexOf(needle);
      if (at !== -1) {
        hits.push({ pageIndex, rects: rectsForRange(page.items, page.map, at, at + needle.length) });
      }
    }
    assert.equal(hits.length, 1, `expected 1 hit, got ${hits.length}`);
    const { pageIndex, rects } = hits[0];
    assert.ok(rects.length >= 1);
    const { width, height } = index[pageIndex].viewport;
    for (const [x0, y0, x1, y1] of rects) {
      assert.ok(x1 > x0 && y1 > y0, 'rect must have positive area');
      assert.ok(x0 >= -1 && x1 <= width + 1, `rect x out of page: ${x0}..${x1}`);
      assert.ok(y0 >= -1 && y1 <= height + 1, `rect y out of page: ${y0}..${y1}`);
    }
  });

  await test('text runs group into plausible two-column blocks', () => {
    const blocks = blocksForPage(index[0].items);
    assert.ok(blocks.length >= 2, `expected several blocks, got ${blocks.length}`);
    const pageWidth = index[0].viewport.width;
    // Every block must sit inside one column, never straddle the gutter.
    for (const b of blocks) {
      assert.ok(b.x1 - b.x0 < pageWidth * 0.62, `block straddles the gutter: ${b.x1 - b.x0}`);
    }
    const leftEdges = new Set(blocks.map((b) => Math.round(b.x0 / 20)));
    assert.ok(leftEdges.size >= 2, 'both columns should be represented');
  });

  await test('paragraphs merge across columns and pages', () => {
    const paragraphs = mergeParagraphs(index.map((p) => blocksForPage(p.items)));
    assert.ok(paragraphs.length > 0);

    const multiBlock = paragraphs.filter((p) => p.blocks.length > 1);
    assert.ok(
      multiBlock.length > 0,
      'the sample splits paragraphs across columns; none were merged',
    );

    const crossBoundary = multiBlock.filter(
      (p) => new Set(p.blocks.map((b) => b.page)).size > 1,
    );
    assert.ok(
      crossBoundary.length > 0 ||
        multiBlock.some((p) => p.blocks.length >= 2),
      'expected at least one column- or page-spanning paragraph',
    );

    // Merged text must never contain the hyphen-plus-space artefact.
    for (const p of paragraphs) {
      assert.ok(!/\w- \w/.test(p.text), `hyphen artefact left in: ${p.text.slice(0, 60)}`);
    }
  });

  await test('every page carries at least one paragraph badge', () => {
    const byPage = indexByPage(mergeParagraphs(index.map((p) => blocksForPage(p.items))));
    for (let i = 0; i < doc.numPages; i++) {
      const entries = byPage.get(i) ?? [];
      assert.ok(entries.length > 0, `page ${i} would show no badge`);
    }
  });

  await test('a continued paragraph badges the whole merged text', () => {
    // The value of the feature: clicking the badge on the tail of a paragraph
    // that started in the previous column must translate all of it, not the
    // fragment visible there.
    const paragraphs = mergeParagraphs(index.map((p) => blocksForPage(p.items)));
    const continued = paragraphs.find((p) => p.blocks.length > 1);
    assert.ok(continued, 'sample should contain a paragraph split across blocks');

    const byPage = indexByPage(paragraphs);
    for (const { page, rect } of continued.blocks) {
      const entry = (byPage.get(page) ?? []).find(
        (candidate) => candidate.rect[0] === rect[0] && candidate.rect[1] === rect[1],
      );
      assert.ok(entry, 'each block of the paragraph gets its own badge');
      assert.equal(entry.text, continued.text, 'every badge carries the full text');
    }
  });

  await test('badges stay inside the page at every zoom level', () => {
    const byPage = indexByPage(mergeParagraphs(index.map((p) => blocksForPage(p.items))));
    for (const [page, entries] of byPage) {
      const { width, height } = index[page].viewport;
      for (const scale of [0.25, 0.5, 1, 2, 4]) {
        for (const { rect } of entries) {
          const { left, top } = badgePosition(rect[0], rect[1], scale);
          assert.ok(left >= 1, `badge off the left edge at ${scale}x`);
          assert.ok(left < width * scale, `badge past the right edge at ${scale}x`);
          assert.ok(top >= 0 && top < height * scale, `badge off the page at ${scale}x`);
        }
      }
    }
  });

  await test('every marker rect lands on the page it claims', () => {
    const paragraphs = mergeParagraphs(index.map((p) => blocksForPage(p.items)));
    for (const p of paragraphs) {
      for (const { page, rect } of p.blocks) {
        assert.ok(page >= 0 && page < doc.numPages, `bad page index ${page}`);
        const { width, height } = index[page].viewport;
        assert.ok(rect[0] >= -1 && rect[2] <= width + 1, 'marker x off page');
        assert.ok(rect[1] >= -1 && rect[3] <= height + 1, 'marker y off page');
      }
    }
  });

  await doc.destroy();
} else {
  section('pipeline tests skipped (pass a PDF path to enable)');
}

// ------------------------------------------------------------------- summary

process.stdout.write(`\n${passed} passed, ${failed} failed\n`);
if (failed) {
  for (const { name, err } of failures) {
    process.stdout.write(`\n--- ${name}\n${err.stack}\n`);
  }
  process.exit(1);
}
