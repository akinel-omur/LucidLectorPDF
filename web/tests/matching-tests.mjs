/**
 * Text-matching tests: locating panel text back inside the page.
 *
 * Every case here is a way a PDF text layer disagrees with itself about where
 * words begin and end. The reader has to reconcile two views of the same
 * sentence — the paragraph text shown in the panel, and the positioned runs on
 * the page — and a mismatch shows up as a highlight that stops mid-sentence.
 *
 * Run:  node web/tests/matching-tests.mjs
 */

import assert from 'node:assert/strict';
import process from 'node:process';

import {
  buildSearchString,
  compactify,
  rectsForCompactRange,
} from '../js/viewer.js';

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed++;
    process.stdout.write(`  ok   ${name}\n`);
  } catch (err) {
    failed++;
    process.stdout.write(`  FAIL ${name}\n       ${String(err.message).slice(0, 300)}\n`);
  }
}

const item = (str, x, w) => ({ str, hasEOL: false, x, y: 100, w, h: 10 });

// "modified" set with an fi ligature: three runs, no spaces between them,
// while the paragraph builder renders the same text as "modi fi ed".
const ligature = buildSearchString([
  item('The rhythmicity is controlled by neurons in the brainstem which can be modi', 50, 300),
  item('fi', 350, 6),
  item('ed by higher brain centers, and chemoreceptors in the carotid body.', 356, 260),
]);

test('runs concatenate without an invented space', () => {
  assert.ok(ligature.text.includes('modified'));
});

test('the panel spelling "modi fi ed" finds the page text', () => {
  const needle = compactify(
    'The rhythmicity is controlled by neurons in the brainstem which can be ' +
    'modi fi ed by higher brain centers, and chemoreceptors in the carotid body.',
  );
  assert.notEqual(ligature.compact.indexOf(needle), -1);
});

test('the highlight covers every run of the match', () => {
  // The bug this guards: the full sentence failed to match, the search fell
  // back to its opening words, and the highlight stopped at the ligature.
  const needle = compactify('brainstem which can be modi fi ed by higher brain');
  const at = ligature.compact.indexOf(needle);
  assert.notEqual(at, -1);
  const rects = rectsForCompactRange(ligature, at, at + needle.length);
  assert.equal(rects.length, 3, `got ${rects.length} rects`);
  assert.ok(rects[2][2] > 400, 'must reach the third run');
});

test('searching a whole word finds its split spelling', () => {
  assert.notEqual(ligature.compact.indexOf(compactify('modified')), -1);
});

test('a hyphenated line end reads as one word', () => {
  const entry = buildSearchString([
    item('recon-', 50, 30),
    item('struction of the airway', 50, 120),
  ]);
  assert.notEqual(entry.compact.indexOf(compactify('reconstruction')), -1, entry.compact);
});

test('rectangles stay inside the runs they came from', () => {
  const needle = compactify('rhythmicity');
  const at = ligature.compact.indexOf(needle);
  const rects = rectsForCompactRange(ligature, at, at + needle.length);
  assert.equal(rects.length, 1);
  assert.ok(rects[0][0] >= 50 && rects[0][2] <= 350.001);
});

test('an empty match yields no rectangles', () => {
  assert.deepEqual(rectsForCompactRange(ligature, 5, 5), []);
});

process.stdout.write(`\n${passed} passed, ${failed} failed\n`);
process.exit(failed ? 1 : 0);
