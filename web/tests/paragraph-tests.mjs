/**
 * Paragraph reconstruction tests.
 *
 * This is the most intricate part of the port — PDF.js gives positioned text
 * runs and nothing else, so lines, columns and paragraphs are all inferred —
 * and every case below is one that was observed breaking on a real document.
 *
 * Two layers: synthetic layouts that pin each rule down in isolation, then the
 * whole pipeline against an actual two-column PDF.
 *
 * Run:  node web/tests/paragraph-tests.mjs [path/to/sample.pdf]
 */

import assert from 'node:assert/strict';
import process from 'node:process';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
  groupIntoLines,
  groupIntoBlocks,
  blocksForPage,
  mergeParagraphs,
  indexByPage,
} from '../js/paragraphs.js';

const HERE = dirname(fileURLToPath(import.meta.url));

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed++;
    process.stdout.write(`  ok   ${name}\n`);
  } catch (err) {
    failed++;
    // Messages can carry whole paragraphs; keep the report readable.
    process.stdout.write(`  FAIL ${name}\n       ${String(err.message).slice(0, 300)}\n`);
  }
}

function section(title) {
  process.stdout.write(`\n${title}\n`);
}

const run = (str, x, y, w, h = 10) => ({ str, x, y, w, h });
const line = (text, x0, y0, x1, y1) => ({ text, x0, y0, x1, y1 });

// ------------------------------------------------------------------- lines

section('lines');

test('a subscript stays on the line it belongs to', () => {
  // "removal of CO₂ during": the 2 is smaller and sits lower, so its top is
  // nowhere near the line's — only their vertical extents overlap.
  const lines = groupIntoLines([
    run('removal of CO', 50, 100, 60),
    run('2', 110, 104, 4, 6),
    run('during', 116, 100, 30),
  ]);
  assert.equal(lines.length, 1, `split into ${lines.length}`);
});

test('a superscript stays on the line it belongs to', () => {
  // The hard direction: the superscript comes first in document order, so a
  // naive pass anchors the line on it and the body text then fails to join.
  const lines = groupIntoLines([
    run('shown earlier', 50, 100, 60),
    run('12', 110, 96, 5, 5),
    run('and later', 116, 100, 40),
  ]);
  assert.equal(lines.length, 1, `split into ${lines.length}`);
});

test('a column gutter cuts a row in two', () => {
  const lines = groupIntoLines([
    run('left column text', 50, 100, 200),
    run('right column text', 320, 100, 200),
  ]);
  assert.equal(lines.length, 2);
  assert.equal(lines[0].text, 'left column text');
  assert.equal(lines[1].text, 'right column text');
});

test('stretched justified spacing does not cut a line', () => {
  // Justified text in a real textbook reaches 14pt word spaces against a 20pt
  // gutter, which is why the gutter is found by looking down the whole page
  // rather than by thresholding each row.
  const runs = [];
  for (let i = 0; i < 6; i++) runs.push(run(`word${i}`, 50 + i * 48, 100, 40));
  assert.equal(groupIntoLines(runs).length, 1);
});

// ------------------------------------------------------------------ blocks

section('blocks');

test('an indent starts a new paragraph with no extra leading', () => {
  // How most books separate paragraphs. Grouping on vertical gaps alone welds
  // these two into one.
  const blocks = groupIntoBlocks([
    line('In producing the eighth edition of the textbook we would like', 50, 100, 250, 110),
    line('to acknowledge the dedication of the original editors and all', 50, 112, 250, 122),
    line('the people who made this reference possible over the years.', 50, 124, 250, 134),
    line('We need to also recognize the current associate editors for', 62, 136, 250, 146),
    line('their tremendous effort in creating this newest edition too.', 50, 148, 250, 158),
  ]);
  assert.equal(blocks.length, 2, `got ${blocks.length}`);
  assert.match(blocks[0].text, /^In producing/);
  assert.match(blocks[1].text, /^We need to also recognize/);
});

test('an unindented paragraph stays whole', () => {
  const blocks = groupIntoBlocks([
    line('Mechanical properties of the respiratory system govern how', 50, 100, 250, 110),
    line('air moves between the alveoli and the outside atmosphere.', 50, 112, 250, 122),
    line('For air to move a pressure gradient is always required.', 50, 124, 250, 134),
  ]);
  assert.equal(blocks.length, 1);
});

test('extra space between paragraphs is measured, not assumed', () => {
  // Leading of 2pt within a paragraph, 8pt between: the break is obvious only
  // relative to the page's own spacing.
  const blocks = groupIntoBlocks([
    line('First paragraph line one running on for a good while here', 50, 100, 250, 110),
    line('first paragraph line two running on for a good while here', 50, 112, 250, 122),
    line('Second paragraph starts here after a little extra spacing', 50, 130, 250, 140),
    line('second paragraph line two running on for a while as well', 50, 142, 250, 152),
  ]);
  assert.equal(blocks.length, 2, `got ${blocks.length}`);
});

test('columns are read downwards, not across', () => {
  const blocks = groupIntoBlocks([
    line('alpha one line here and it continues onward', 50, 100, 240, 110),
    line('beta one line here and it continues onward', 320, 100, 510, 110),
    line('alpha two line here and it continues onward', 50, 112, 240, 122),
    line('beta two line here and it continues onward', 320, 112, 510, 122),
  ]);
  assert.equal(blocks.length, 2, `got ${blocks.length}`);
  assert.match(blocks[0].text, /^alpha one .* alpha two/);
  assert.match(blocks[1].text, /^beta one .* beta two/);
});

test('a full-width heading belongs to neither side of itself', () => {
  const blocks = groupIntoBlocks([
    line('alpha column line one that runs on for a while', 50, 100, 240, 110),
    line('beta column line one that runs on for a while', 320, 100, 510, 110),
    line('SECTION II: Resuscitation and Stabilization of the Patient', 50, 130, 510, 142),
    line('gamma column line after the heading runs onward', 50, 150, 240, 160),
  ]);
  assert.deepEqual(
    blocks.map((b) => b.text.slice(0, 7)),
    ['alpha c', 'beta co', 'SECTION', 'gamma c'],
  );
});

test('page furniture is dropped', () => {
  const blocks = blocksForPage([
    run('7', 300, 700, 5),
    run('This paragraph is definitely long enough to survive.', 50, 100, 300),
  ]);
  assert.equal(blocks.length, 1);
});

// -------------------------------------------------------- whole pipeline

const pdfPath = process.argv[2] || join(HERE, 'sample.pdf');
let bytes = null;
try {
  bytes = new Uint8Array(await readFile(pdfPath));
} catch {
  section(`pipeline skipped — no PDF at ${pdfPath}`);
}

if (bytes) {
  section(`pipeline against ${pdfPath}`);

  const pdfjsLib = await import('../vendor/pdf.min.mjs');
  pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
    '../vendor/pdf.worker.min.mjs',
    import.meta.url,
  ).href;

  const doc = await pdfjsLib.getDocument({ data: bytes, isEvalSupported: false }).promise;

  const pages = [];
  for (let i = 1; i <= doc.numPages; i++) {
    const page = await doc.getPage(i);
    const viewport = page.getViewport({ scale: 1 });
    const content = await page.getTextContent();
    const items = [];
    for (const item of content.items) {
      if (typeof item.str !== 'string') continue;
      const t = pdfjsLib.Util.transform(viewport.transform, item.transform);
      const height = Math.hypot(t[1], t[3]) || item.height || 10;
      items.push({ str: item.str, x: t[4], y: t[5] - height, w: item.width, h: height });
    }
    pages.push({ items, viewport });
  }

  const pageBlocks = pages.map((p) => blocksForPage(p.items));
  const paragraphs = mergeParagraphs(pageBlocks);
  const byPage = indexByPage(paragraphs);

  test('every page yields blocks', () => {
    pageBlocks.forEach((blocks, i) => assert.ok(blocks.length > 0, `page ${i} has none`));
  });

  test('no block straddles the gutter', () => {
    pageBlocks.forEach((blocks, i) => {
      const { width } = pages[i].viewport;
      for (const b of blocks) {
        assert.ok(b.x1 - b.x0 < width * 0.62, `page ${i}: ${(b.x1 - b.x0).toFixed(0)}pt wide`);
      }
    });
  });

  test('both columns are represented', () => {
    const edges = new Set(pageBlocks[0].map((b) => Math.round(b.x0 / 20)));
    assert.ok(edges.size >= 2, `only ${edges.size} distinct left edges`);
  });

  test('neighbouring paragraphs are not welded together', () => {
    // The sample numbers each paragraph [0]..[13]; finding two markers in one
    // paragraph means a break was missed.
    const welded = paragraphs.filter((p) => (p.text.match(/\[\d+\]/g) || []).length > 1);
    assert.equal(welded.length, 0, `${welded.length} paragraphs swallowed a neighbour`);
  });

  test('paragraphs still merge across columns and pages', () => {
    assert.ok(paragraphs.some((p) => p.blocks.length > 1), 'nothing merged');
  });

  test('no hyphen artefact survives merging', () => {
    for (const p of paragraphs) {
      assert.ok(!/\w- \w/.test(p.text), p.text.slice(0, 60));
    }
  });

  test('every badge rect sits on the page it claims', () => {
    for (const [page, entries] of byPage) {
      const { width, height } = pages[page].viewport;
      for (const { rect } of entries) {
        assert.ok(rect[0] >= -1 && rect[2] <= width + 1, 'x off page');
        assert.ok(rect[1] >= -1 && rect[3] <= height + 1, 'y off page');
      }
    }
  });

  const badges = [...byPage.values()].reduce((n, e) => n + e.length, 0);
  process.stdout.write(
    `\n  ${doc.numPages} pages → ${paragraphs.length} paragraphs, ${badges} badges\n`,
  );
  await doc.destroy();
}

process.stdout.write(`\n${passed} passed, ${failed} failed\n`);
process.exit(failed ? 1 : 0);
