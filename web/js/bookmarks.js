/**
 * Table-of-contents panel — the web counterpart of pdf_reader/bookmark_panel.py.
 *
 * PyMuPDF hands the desktop app a flat `get_toc()` list of
 * `[level, title, page]` rows, already resolved to page numbers. PDF.js gives
 * a nested `getOutline()` tree whose entries point at *destinations* — named
 * references that each have to be resolved to a page index separately. So the
 * shape of the work differs; the behaviour does not.
 */

/**
 * @typedef {Object} OutlineNode
 * @property {string} title
 * @property {number|null} page   0-based, or null when the destination is broken.
 * @property {OutlineNode[]} children
 */

export class BookmarkPanel extends EventTarget {
  /**
   * @param {HTMLElement} container  Element the tree is rendered into.
   */
  constructor(container) {
    super();
    this.container = container;
    /** @type {OutlineNode[]} */
    this.nodes = [];
    /** Flat, document-order list of [page, element] for current-page tracking. */
    this._flat = [];
    this._current = null;
    this.labels = { empty: 'Bu belgede yer işareti yok' };

    this.container.addEventListener('keydown', (event) => this._onKeyDown(event));
  }

  /**
   * Load a document's outline, or clear the panel when passed null.
   *
   * @param {import('../vendor/pdf.min.mjs').PDFDocumentProxy|null} doc
   */
  async setDocument(doc) {
    this.nodes = [];
    this._flat = [];
    this._current = null;
    this.container.textContent = '';

    if (!doc) {
      this._renderEmpty();
      return false;
    }

    let outline = null;
    try {
      outline = await doc.getOutline();
    } catch {
      outline = null; // a malformed outline is not worth failing the open over
    }

    if (!outline || !outline.length) {
      this._renderEmpty();
      return false;
    }

    this.nodes = await resolveOutline(doc, outline);
    this._render();
    return true;
  }

  /** True when the current document has a usable table of contents. */
  get hasOutline() {
    return this.nodes.length > 0;
  }

  /**
   * Select the deepest bookmark whose page is at or before `page`.
   *
   * Deliberately scans the whole list rather than stopping at the first entry
   * past the current page: document order is *usually* monotonic in page
   * number, but a malformed outline breaks that, and an early exit would then
   * settle on the wrong heading. Same reasoning as bookmark_panel.py.
   *
   * @param {number} page  0-based page index.
   */
  highlightCurrent(page) {
    let best = null;
    let bestPage = -1;
    for (const [entryPage, element] of this._flat) {
      if (bestPage <= entryPage && entryPage <= page) {
        best = element;
        bestPage = entryPage;
      }
    }
    if (!best || best === this._current) return;

    this._current?.classList.remove('is-current');
    best.classList.add('is-current');
    this._current = best;

    // Reveal it: an ancestor may be collapsed.
    for (let li = best.closest('li')?.parentElement?.closest('li'); li; ) {
      this._setExpanded(li, true);
      li = li.parentElement?.closest('li');
    }
    best.scrollIntoView({ block: 'nearest' });
  }

  expandAll() {
    this.container
      .querySelectorAll('li.has-children')
      .forEach((li) => this._setExpanded(li, true));
  }

  collapseAll() {
    this.container
      .querySelectorAll('li.has-children')
      .forEach((li) => this._setExpanded(li, false));
  }

  /** @param {{empty: string}} labels */
  setLabels(labels) {
    this.labels = { ...this.labels, ...labels };
    if (!this.hasOutline) this._renderEmpty();
  }

  // ------------------------------------------------------------------ //
  // Rendering
  // ------------------------------------------------------------------ //

  _renderEmpty() {
    this.container.textContent = '';
    const message = document.createElement('p');
    message.className = 'bm-empty';
    message.textContent = this.labels.empty;
    this.container.appendChild(message);
  }

  _render() {
    this.container.textContent = '';
    this.container.appendChild(this._buildList(this.nodes));
    this.collapseAll(); // the desktop panel opens fully collapsed
  }

  _buildList(nodes) {
    const list = document.createElement('ul');
    list.className = 'bm-list';

    for (const node of nodes) {
      const li = document.createElement('li');
      const row = document.createElement('div');
      row.className = 'bm-row';

      if (node.children.length) {
        li.classList.add('has-children');
        const twisty = document.createElement('button');
        twisty.type = 'button';
        twisty.className = 'bm-twisty';
        twisty.tabIndex = -1;
        twisty.setAttribute('aria-hidden', 'true');
        twisty.addEventListener('click', (event) => {
          event.stopPropagation();
          this._setExpanded(li, !li.classList.contains('is-open'));
        });
        row.appendChild(twisty);
      } else {
        const spacer = document.createElement('span');
        spacer.className = 'bm-twisty bm-twisty-empty';
        row.appendChild(spacer);
      }

      const label = document.createElement('button');
      label.type = 'button';
      label.className = 'bm-label';
      label.textContent = node.title;
      if (node.page !== null) {
        label.title = `${node.title} — s. ${node.page + 1}`;
        this._flat.push([node.page, label]);
      } else {
        label.title = node.title;
        label.classList.add('is-dead');
      }

      label.addEventListener('click', () => {
        // Clicking a heading opens its whole subtree, as on the desktop.
        if (li.classList.contains('has-children')) this._setSubtree(li, true);
        if (node.page !== null) {
          this.dispatchEvent(
            new CustomEvent('pagerequested', { detail: { page: node.page } }),
          );
        }
      });

      row.appendChild(label);
      li.appendChild(row);

      if (node.children.length) li.appendChild(this._buildList(node.children));
      list.appendChild(li);
    }

    return list;
  }

  _setExpanded(li, expanded) {
    li.classList.toggle('is-open', expanded);
  }

  /** Expand or collapse an item together with everything under it. */
  _setSubtree(li, expanded) {
    this._setExpanded(li, expanded);
    li.querySelectorAll('li.has-children').forEach((child) =>
      this._setExpanded(child, expanded),
    );
  }

  /** ← and → collapse and expand the whole subtree, matching _BookmarkTree. */
  _onKeyDown(event) {
    const label = document.activeElement?.closest?.('.bm-label');
    const li = label?.closest('li');
    if (!li) return;

    if (event.key === 'ArrowRight') {
      event.preventDefault();
      this._setSubtree(li, true);
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      this._setSubtree(li, false);
    }
  }
}

// ---------------------------------------------------------------------- //
// Destination resolution
// ---------------------------------------------------------------------- //

/**
 * Turn PDF.js outline items into nodes carrying a resolved page index.
 *
 * Every entry needs its destination looked up, and a textbook can have
 * hundreds, so the lookups run together rather than one after another —
 * sequentially this is the difference between a snappy panel and a visible
 * pause after opening.
 */
async function resolveOutline(doc, items) {
  const nodes = await Promise.all(
    items.map(async (item) => ({
      title: (item.title || '').trim() || '—',
      page: await resolvePage(doc, item.dest),
      children: item.items?.length ? await resolveOutline(doc, item.items) : [],
    })),
  );
  return nodes;
}

/**
 * Resolve a destination to a 0-based page index, or null if it cannot be.
 *
 * Outlines in the wild point at named destinations, explicit references and
 * occasionally at nothing at all; a broken entry should grey out, not throw.
 */
async function resolvePage(doc, dest) {
  try {
    const resolved = typeof dest === 'string' ? await doc.getDestination(dest) : dest;
    const target = Array.isArray(resolved) ? resolved[0] : null;
    if (target === null || target === undefined) return null;
    // An explicit destination may carry the page index directly.
    if (typeof target === 'number') return target;
    return await doc.getPageIndex(target);
  } catch {
    return null;
  }
}
