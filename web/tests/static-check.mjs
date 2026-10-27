/**
 * Static consistency checks — no dependencies, no browser.
 *
 * Catches the class of mistake that produces a page which renders but does
 * nothing: a module that fails to parse, an element id the script reaches for
 * that the markup never defines, a translation key missing from one language,
 * a stylesheet or vendor file that is referenced but absent.
 *
 * Run:  node web/tests/static-check.mjs
 */

import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = (rel) => readFileSync(join(WEB, rel), 'utf8');

let problems = 0;
const ok = (msg) => console.log(`  ok   ${msg}`);
const fail = (msg) => {
  problems++;
  console.log(`  FAIL ${msg}`);
};

// 1. Modules that do not need a DOM must import cleanly.
for (const rel of [
  'js/text-utils.js',
  'js/paragraphs.js',
  'js/translator.js',
  'js/i18n.js',
  'js/viewer.js',
]) {
  try {
    await import(pathToFileURL(join(WEB, rel)).href);
    ok(`import ${rel}`);
  } catch (err) {
    fail(`import ${rel}: ${err.message}`);
  }
}

const html = read('index.html');
const app = read('js/app.js');

// 2. Every element id the script looks up must exist in the markup.
const htmlIds = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));
const usedIds = [...app.matchAll(/\$\('([^']+)'\)/g)].map((m) => m[1]);
const missingIds = usedIds.filter((id) => !htmlIds.has(id));
if (missingIds.length) fail(`element ids not in markup: ${missingIds.join(', ')}`);
else ok(`all ${usedIds.length} element ids resolve`);

// 3. Every translation key used must exist in both languages.
const i18n = read('js/i18n.js');
const trBlock = i18n.slice(i18n.indexOf('tr: {'), i18n.indexOf('en: {'));
const enBlock = i18n.slice(i18n.indexOf('en: {'));
const keysIn = (block) => new Set([...block.matchAll(/^\s{4}(\w+):/gm)].map((m) => m[1]));
const tr = keysIn(trBlock);
const en = keysIn(enBlock);
const usedKeys = [
  ...new Set([
    ...[...html.matchAll(/data-i18n(?:-title|-placeholder)?="([^"]+)"/g)].map((m) => m[1]),
    ...[...app.matchAll(/\bs\('([a-z0-9_]+)'/g)].map((m) => m[1]),
  ]),
];
const missTr = usedKeys.filter((k) => !tr.has(k));
const missEn = usedKeys.filter((k) => !en.has(k));
if (missTr.length || missEn.length) {
  fail(`i18n keys missing — tr: [${missTr}] en: [${missEn}]`);
} else {
  ok(`all ${usedKeys.length} i18n keys present in tr and en`);
}

// 4. Everything the page references from disk must be there.
const refs = [
  ...[...html.matchAll(/(?:src|href)="((?!https?:|data:|#)[^"]+)"/g)].map((m) => m[1]),
  'vendor/pdf.worker.min.mjs',
  'vendor/cmaps',
  'vendor/standard_fonts',
];
const missingFiles = refs.filter((rel) => !existsSync(join(WEB, rel)));
if (missingFiles.length) fail(`referenced but missing: ${missingFiles.join(', ')}`);
else ok(`all ${refs.length} referenced files exist`);

// 5. The `hidden` attribute must not be defeated by a layout rule.
//    A bare class selector setting `display` outranks the UA's
//    `[hidden] { display: none }`, which once left the whole toolbar on screen.
const css = read('css/app.css');
if (/\[hidden\]\s*{[^}]*display:\s*none\s*!important/.test(css)) {
  ok('[hidden] is enforced with !important');
} else {
  fail('css lacks an `[hidden] { display: none !important }` rule');
}

console.log(problems ? `\n${problems} problem(s)` : '\nstatic checks clean');
process.exit(problems ? 1 : 0);
