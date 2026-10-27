/**
 * Boot smoke test — loads index.html and runs app.js in a simulated DOM.
 *
 * Verifies the wiring that only shows up at runtime: that the application
 * starts at all, that the initial visibility of each region is right, that
 * switching interface language actually rewrites the markup, and that toolbar
 * buttons are safe to click before a document is open.
 *
 * Needs jsdom. If it is not installed the test skips rather than fails:
 *     npm install jsdom
 *
 * Run:  node web/tests/dom-smoke.mjs
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..');

let JSDOM;
try {
  // JSDOM_PATH lets a checkout without its own node_modules borrow one
  // elsewhere: JSDOM_PATH=/path/to/node_modules/jsdom node dom-smoke.mjs
  ({ JSDOM } = await import(process.env.JSDOM_PATH || 'jsdom'));
} catch {
  console.log('  skip dom smoke — jsdom not installed (npm install jsdom)');
  process.exit(0);
}

const dom = new JSDOM(readFileSync(join(WEB, 'index.html'), 'utf8'), {
  url: pathToFileURL(join(WEB, 'index.html')).href,
  pretendToBeVisual: true,
  runScripts: 'outside-only',
});
const { window } = dom;

// Gaps in jsdom that the application legitimately relies on.
window.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
if (!window.navigator.clipboard) {
  Object.defineProperty(window.navigator, 'clipboard', {
    value: { writeText: async () => {} },
  });
}

for (const key of [
  'window', 'document', 'localStorage', 'HTMLInputElement', 'HTMLTextAreaElement',
  'HTMLSelectElement', 'ResizeObserver', 'requestAnimationFrame',
  'cancelAnimationFrame', 'CustomEvent', 'Event', 'getSelection', 'EventTarget',
]) {
  try {
    globalThis[key] = window[key] ?? globalThis[key];
  } catch {
    /* read-only on this Node version — the app does not need it globally */
  }
}
globalThis.window = window;
globalThis.document = window.document;

const failures = [];
window.addEventListener('error', (e) => failures.push(String(e.error || e.message)));
process.on('unhandledRejection', (r) => failures.push(`unhandledRejection: ${r}`));

await import(pathToFileURL(join(WEB, 'js/app.js')).href);
await new Promise((resolve) => setTimeout(resolve, 300));

const doc = window.document;
const check = (name, condition) => {
  console.log(`  ${condition ? 'ok  ' : 'FAIL'} ${name}`);
  if (!condition) failures.push(name);
};
const click = (id) =>
  doc.getElementById(id).dispatchEvent(new window.Event('click', { bubbles: true }));

check('application booted', !!window.LucidLector);
check('dropzone visible before a document', !doc.getElementById('dropzone').hidden);
check(
  'page and zoom groups hidden before a document',
  doc.getElementById('grp-pages').hidden && doc.getElementById('grp-zoom').hidden,
);
check('translation panel visible by default', !doc.getElementById('panel').hidden);
check('boot error bar stays hidden on success', doc.getElementById('boot-error').hidden);

doc.querySelector('.locale-btn[data-locale="tr"]').dispatchEvent(
  new window.Event('click', { bubbles: true }),
);
const trText = doc.querySelector('[data-i18n="drop_title"]').textContent;
doc.querySelector('.locale-btn[data-locale="en"]').dispatchEvent(
  new window.Event('click', { bubbles: true }),
);
const enText = doc.querySelector('[data-i18n="drop_title"]').textContent;
check('language switch rewrites the markup', /PDF dosyan/.test(trText) && /Drop your PDF/.test(enText));
check(
  'active language button tracks the selection',
  doc.querySelector('.locale-btn[data-locale="en"]').classList.contains('is-active'),
);

const before = failures.length;
for (const id of ['btn-find', 'btn-panel', 'btn-paragraph', 'btn-zoom-in', 'btn-prev', 'btn-next']) {
  click(id);
}
await new Promise((resolve) => setTimeout(resolve, 100));
check('toolbar clicks are safe with no document open', failures.length === before);

console.log(failures.length ? `\nfailures:\n${failures.join('\n')}` : '\ndom smoke clean');
process.exit(failures.length ? 1 : 0);
