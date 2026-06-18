/**
 * app.js — CC Dashboard UI driver
 *
 * Reads window.CCDASH_DATA and drives:
 *   - Live clock (#clock)
 *   - Summary panel count animations (#summary .panel)
 *   - Card grid rendering (#grid)
 *   - Kind filter chips (#filters .chip)
 *   - Search (#search)
 *   - Detail drawer (#detail)
 *   - Keyboard shortcuts (/ and Escape)
 *   - Boot overlay dismissal (#boot)
 *
 * Inlined into index.html LAST, after data script and hud.js.
 * Self-contained IIFE — no globals, no imports.
 */

(function () {
  'use strict';

  // ─── Helpers ────────────────────────────────────────────────────────────────

  /** Format a token pair into a display string, or null when both are absent. */
  function formatTokens(always, invocation) {
    if (always == null && invocation == null) return null;
    if (always != null && invocation != null) return '↻ ' + always + ' / ⊚ ' + invocation;
    if (always != null) return always + ' tok';
    return invocation + ' tok';
  }

  /** Zero-pad a number to two digits. */
  function pad2(n) {
    return String(n).padStart(2, '0');
  }

  // ─── Clock ──────────────────────────────────────────────────────────────────

  function startClock() {
    const el = document.getElementById('clock');
    if (!el) return;

    function tick() {
      const now = new Date();
      el.textContent =
        pad2(now.getHours()) + ':' +
        pad2(now.getMinutes()) + ':' +
        pad2(now.getSeconds());
    }

    tick(); // render immediately so there's no blank flash on first second
    setInterval(tick, 1000);
  }

  // ─── Summary panel count-up animation ──────────────────────────────────────

  /**
   * Animate a single .panel-count element from 0 to `target` over ~700ms.
   * Uses ease-out cubic easing. Renders instantly for prefers-reduced-motion.
   */
  function animatePanelCount(el, target) {
    if (target === 0) {
      el.textContent = '0';
      return;
    }

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) {
      el.textContent = String(target);
      return;
    }

    const DURATION = 700; // ms
    const start = performance.now();

    function step(now) {
      const elapsed = now - start;
      const t = Math.min(elapsed / DURATION, 1);
      // Ease-out cubic: fast start, decelerate at the end
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = String(Math.round(eased * target));

      if (t < 1) {
        requestAnimationFrame(step);
      } else {
        el.textContent = String(target); // guarantee exact final value
      }
    }

    requestAnimationFrame(step);
  }

  function populateSummary(byKind) {
    const panels = document.querySelectorAll('#summary .panel[data-kind]');
    panels.forEach(function (panel) {
      const kind    = panel.dataset.kind;
      const countEl = panel.querySelector('.panel-count');
      if (!countEl) return;
      const value = (byKind && byKind[kind] != null) ? byKind[kind] : 0;
      animatePanelCount(countEl, value);
    });
  }

  // ─── Card rendering ─────────────────────────────────────────────────────────

  /**
   * Build a single .card article element for one data item.
   * ALL text is set via textContent — never innerHTML with raw data.
   */
  function buildCard(item, index) {
    const card = document.createElement('article');
    card.classList.add('card');
    card.dataset.id   = item.id   || '';
    card.dataset.kind = item.kind || '';

    // CSS entrance animation: .enter triggers a keyframe; --i staggers the delay
    card.classList.add('enter');
    card.style.setProperty('--i', String(index));

    const kindEl = document.createElement('div');
    kindEl.classList.add('card-kind');
    kindEl.textContent = (item.kind || '').toUpperCase();

    const nameEl = document.createElement('div');
    nameEl.classList.add('card-name');
    nameEl.textContent = item.name || '';

    const descEl = document.createElement('div');
    descEl.classList.add('card-desc');
    descEl.textContent = item.description || '';

    const tokEl = document.createElement('div');
    tokEl.classList.add('card-tokens');
    const tokStr = formatTokens(item.tokens_always_loaded, item.tokens_invocation);
    if (tokStr !== null) {
      tokEl.textContent = tokStr;
    } else {
      tokEl.hidden = true; // hide the node entirely when no token data
    }

    card.appendChild(kindEl);
    card.appendChild(nameEl);
    card.appendChild(descEl);
    card.appendChild(tokEl);

    return card;
  }

  /**
   * Render all items into #grid via a DocumentFragment (single reflow).
   * Returns the ordered card element array, parallel to the items array.
   */
  function renderCards(items) {
    const grid = document.getElementById('grid');
    if (!grid) return [];

    const fragment = document.createDocumentFragment();
    const cards    = [];

    items.forEach(function (item, index) {
      const card = buildCard(item, index);
      fragment.appendChild(card);
      cards.push(card);
    });

    grid.appendChild(fragment);
    return cards;
  }

  // ─── Shared filter/search logic ─────────────────────────────────────────────

  /** A card passes the kind filter when it matches activeKind, or activeKind is "all". */
  function passesKind(card, activeKind) {
    if (activeKind === 'all' || !activeKind) return true;
    return card.dataset.kind === activeKind;
  }

  /** An item passes the search query when any of its text fields contain the query. */
  function passesSearch(item, query) {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      (item.id          || '').toLowerCase().includes(q) ||
      (item.name        || '').toLowerCase().includes(q) ||
      (item.description || '').toLowerCase().includes(q) ||
      (item.kind        || '').toLowerCase().includes(q)
    );
  }

  /**
   * Apply both the active kind filter and the search query to every card.
   *
   *  - Wrong kind      → display:none, no dimming classes
   *  - Right kind + no query → display restored, no dimming classes
   *  - Right kind + matching query → .is-match, no .is-dimmed
   *  - Right kind + non-matching query → .is-dimmed, no .is-match
   */
  function applyFilters(cards, items, activeKind, searchQuery) {
    cards.forEach(function (card, index) {
      const item     = items[index];
      const kindOk   = passesKind(card, activeKind);
      const searchOk = passesSearch(item, searchQuery);

      if (!kindOk) {
        card.style.display = 'none';
        card.classList.remove('is-match', 'is-dimmed');
        return;
      }

      card.style.display = ''; // restore from kind-hidden state

      if (!searchQuery) {
        card.classList.remove('is-match', 'is-dimmed');
      } else if (searchOk) {
        card.classList.add('is-match');
        card.classList.remove('is-dimmed');
      } else {
        card.classList.add('is-dimmed');
        card.classList.remove('is-match');
      }
    });
  }

  // ─── Filter chips ────────────────────────────────────────────────────────────

  /**
   * Wire up the #filters .chip buttons.
   * Returns a getter () => activeKind for the search handler to read.
   */
  function setupFilters(cards, items, getSearchQuery) {
    const chips = document.querySelectorAll('#filters .chip[data-kind]');
    let activeKind = 'all';

    // Initialise visual state: mark "All" chip active
    chips.forEach(function (chip) {
      const isAll = chip.dataset.kind === 'all';
      chip.classList.toggle('is-active', isAll);
      chip.setAttribute('aria-pressed', isAll ? 'true' : 'false');
    });

    chips.forEach(function (chip) {
      chip.addEventListener('click', function () {
        activeKind = chip.dataset.kind;

        chips.forEach(function (c) {
          const isThis = c === chip;
          c.classList.toggle('is-active', isThis);
          c.setAttribute('aria-pressed', isThis ? 'true' : 'false');
        });

        applyFilters(cards, items, activeKind, getSearchQuery());
      });
    });

    return function getActiveKind() { return activeKind; };
  }

  // ─── Search ──────────────────────────────────────────────────────────────────

  /**
   * Wire up the #search input.
   * Returns a getter () => currentQuery for the filter handler to read.
   */
  function setupSearch(cards, items, getActiveKind) {
    const input = document.getElementById('search');
    if (!input) return function () { return ''; };

    let currentQuery = '';

    input.addEventListener('input', function () {
      currentQuery = input.value.trim();
      applyFilters(cards, items, getActiveKind(), currentQuery);
    });

    return function getQuery() { return currentQuery; };
  }

  // ─── Detail drawer ───────────────────────────────────────────────────────────

  /**
   * Wire up the #detail drawer: card click opens it, close button / Escape shuts it.
   * Returns a control object with .isOpen() and .close() for the keyboard handler.
   */
  function setupDetail(cards, items) {
    const drawer    = document.getElementById('detail');
    const nameEl    = document.getElementById('detail-name');
    const kindEl    = document.getElementById('detail-kind');
    const pathEl    = document.getElementById('detail-path');
    const tokensEl  = document.getElementById('detail-tokens');
    const descEl    = document.getElementById('detail-desc');
    const previewEl = document.getElementById('detail-preview');
    const closeBtn  = document.getElementById('detail-close');

    if (!drawer) {
      // Return a no-op control object so callers don't need to null-check
      return { isOpen: function () { return false; }, close: function () {} };
    }

    let selectedCard = null;

    function openDetail(card, item) {
      // Deselect previously selected card
      if (selectedCard) {
        selectedCard.classList.remove('is-selected');
      }
      selectedCard = card;
      card.classList.add('is-selected');

      // Populate all fields via textContent (safe from injection)
      if (nameEl)    nameEl.textContent    = item.name        || '';
      if (kindEl)    kindEl.textContent    = item.kind        || '';
      if (pathEl)    pathEl.textContent    = item.path        || '';
      if (descEl)    descEl.textContent    = item.description || '';
      if (previewEl) previewEl.textContent = item.preview     || '';

      if (tokensEl) {
        const tokStr = formatTokens(item.tokens_always_loaded, item.tokens_invocation);
        tokensEl.textContent = tokStr !== null ? tokStr : '—'; // em-dash when absent
      }

      // Show drawer: remove BOTH hidden attribute AND .is-hidden class
      drawer.removeAttribute('hidden');
      drawer.classList.remove('is-hidden');
    }

    function closeDetail() {
      // Hide drawer: add BOTH hidden attribute AND .is-hidden class
      drawer.setAttribute('hidden', '');
      drawer.classList.add('is-hidden');

      if (selectedCard) {
        selectedCard.classList.remove('is-selected');
        selectedCard = null;
      }
    }

    // Card click handlers
    cards.forEach(function (card, index) {
      card.addEventListener('click', function () {
        openDetail(card, items[index]);
      });
    });

    // Close button
    if (closeBtn) {
      closeBtn.addEventListener('click', closeDetail);
    }

    return {
      isOpen: function () { return !drawer.hasAttribute('hidden'); },
      close:  closeDetail
    };
  }

  // ─── Keyboard shortcuts ──────────────────────────────────────────────────────

  function setupKeyboard(detail) {
    const searchEl = document.getElementById('search');

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        // Priority 1: close detail drawer if open
        if (detail && detail.isOpen()) {
          detail.close();
        } else if (searchEl && document.activeElement === searchEl) {
          // Priority 2: blur/clear search focus
          searchEl.blur();
        }
        return;
      }

      // '/' focuses the search input, but only when focus is NOT already in a text field
      if (e.key === '/' && searchEl) {
        const activeTag = (document.activeElement || {}).tagName || '';
        if (activeTag !== 'INPUT' && activeTag !== 'TEXTAREA') {
          e.preventDefault(); // prevent the slash character from being typed
          searchEl.focus();
        }
      }
    });
  }

  // ─── Boot overlay ────────────────────────────────────────────────────────────

  /**
   * After ~1.2s, add .done to #boot (triggers CSS fade-out) and then set
   * hidden on it after an additional 600ms for the transition to finish.
   * Guards against hud.js having already dismissed it.
   */
  function dismissBootOverlay() {
    const boot = document.getElementById('boot');
    if (!boot) return;

    // Guard: hud.js may have already handled this
    if (boot.hasAttribute('hidden') || boot.classList.contains('done')) return;

    setTimeout(function () {
      // Re-check inside the timeout in case hud.js acted during the delay
      if (boot.hasAttribute('hidden') || boot.classList.contains('done')) return;

      boot.classList.add('done');

      // After the CSS transition, fully remove from layout/accessibility
      setTimeout(function () {
        boot.setAttribute('hidden', '');
      }, 600);
    }, 1200);
  }

  // ─── No-data fallback ────────────────────────────────────────────────────────

  function renderNoData(message) {
    const grid = document.getElementById('grid');
    if (!grid) return;
    const note = document.createElement('p');
    note.classList.add('no-data');
    note.textContent = message || 'No data available.';
    grid.appendChild(note);
  }

  // ─── Main init ───────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    try {
      // Clock always starts regardless of data state
      startClock();

      // Validate data presence
      const data = window.CCDASH_DATA;
      if (!data || !Array.isArray(data.items) || data.items.length === 0) {
        renderNoData(
          data
            ? 'No config items found.'
            : 'CCDASH_DATA not loaded — run the builder to generate index.html.'
        );
        dismissBootOverlay();
        return;
      }

      const items = data.items;

      // 1. Animate summary panel counts
      populateSummary(data.summary && data.summary.by_kind);

      // 2. Render cards (returns element array parallel to items)
      const cards = renderCards(items);

      // 3. Wire up filters and search with cross-reading closures.
      //    Each setup fn returns a getter; the other setup fn receives it
      //    so both halves of applyFilters always read live state.
      //
      //    Bootstrap order: filters need getSearchQuery, search needs getActiveKind.
      //    Solve with a mutable wrapper so each getter is available before its
      //    producer is fully set up.
      let _getQuery      = function () { return ''; };
      let _getActiveKind = function () { return 'all'; };

      const getSearchQuery = function () { return _getQuery(); };
      const getActiveKind  = function () { return _getActiveKind(); };

      _getActiveKind = setupFilters(cards, items, getSearchQuery);
      _getQuery      = setupSearch(cards, items, getActiveKind);

      // 4. Detail drawer
      const detail = setupDetail(cards, items);

      // 5. Keyboard shortcuts
      setupKeyboard(detail);

      // 6. Dismiss boot overlay after delay
      dismissBootOverlay();

    } catch (err) {
      // Surface any unexpected init error rather than silently failing
      console.error('[ccdash] init error:', err);
      renderNoData('Dashboard failed to initialise. See browser console for details.');
    }
  });

}());

/* ============================================================
   Conversations + tab switching — CCDashboard server mode.
   Self-contained IIFE; reads window.CCDASH_SERVER. No-ops (and disables the
   Conversations tab) in a static snapshot where there is no local server.
   ============================================================ */
(function () {
  'use strict';

  const base = window.CCDASH_SERVER || null;
  const byId = function (id) { return document.getElementById(id); };

  function setupTabs() {
    const tabs = Array.from(document.querySelectorAll('#tabs .tab'));
    const views = { config: byId('view-config'), conversations: byId('view-conversations') };
    if (!tabs.length) return;
    let loaded = false;
    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        if (tab.disabled) return;
        const name = tab.dataset.view;
        tabs.forEach(function (t) {
          const on = t.dataset.view === name;
          t.classList.toggle('is-active', on);
          t.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        Object.keys(views).forEach(function (k) {
          if (views[k]) views[k].hidden = (k !== name);
        });
        if (name === 'conversations' && base && !loaded) {
          loaded = true;
          loadConversations('');
        }
      });
    });
  }

  function fmtDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return isNaN(d.getTime()) ? String(iso).slice(0, 16) : d.toLocaleString();
  }

  function renderResults(results) {
    const wrap = byId('conv-results');
    const count = byId('conv-count');
    if (!wrap) return;
    wrap.textContent = '';
    if (count) count.textContent = results.length + ' conversation' + (results.length === 1 ? '' : 's');
    const frag = document.createDocumentFragment();
    results.forEach(function (r) {
      const row = document.createElement('article');
      row.className = 'conv-row glass';
      row.dataset.session = r.session_id;

      const head = document.createElement('div');
      head.className = 'conv-head';
      const title = document.createElement('span');
      title.className = 'conv-title';
      title.textContent = r.title || '(untitled)';
      const branch = document.createElement('span');
      branch.className = 'conv-branch';
      branch.textContent = r.git_branch || '—';
      head.appendChild(title);
      head.appendChild(branch);

      const meta = document.createElement('div');
      meta.className = 'conv-meta';
      meta.textContent = r.cwd + '   ·   ' + (r.message_count || 0) + ' msgs   ·   ' + fmtDate(r.last_at);

      row.appendChild(head);
      row.appendChild(meta);

      if (r.snippet) {
        const snip = document.createElement('div');
        snip.className = 'conv-snippet';
        snip.textContent = r.snippet;
        row.appendChild(snip);
      }

      const btn = document.createElement('button');
      btn.className = 'conv-resume';
      btn.type = 'button';
      btn.textContent = '▸ Resume (admin)';
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        resume(r.session_id, btn);
      });
      row.appendChild(btn);

      frag.appendChild(row);
    });
    wrap.appendChild(frag);
  }

  function loadConversations(q) {
    if (!base) return;
    fetch(base + '/api/search?q=' + encodeURIComponent(q || ''))
      .then(function (r) { return r.json(); })
      .then(function (d) { renderResults(d.results || []); })
      .catch(function (err) {
        const wrap = byId('conv-results');
        if (wrap) wrap.textContent = 'Search failed: ' + err;
      });
  }

  function resume(sessionId, btn) {
    if (!base) return;
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = '… launching';
    fetch(base + '/api/resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId: sessionId }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) { btn.textContent = d.ok ? '✓ accept the UAC prompt' : ('✕ ' + (d.error || 'failed')); })
      .catch(function (err) { btn.textContent = '✕ ' + err; })
      .finally(function () {
        setTimeout(function () { btn.disabled = false; btn.textContent = original; }, 4500);
      });
  }

  document.addEventListener('DOMContentLoaded', function () {
    setupTabs();
    if (!base) {
      const convTab = document.querySelector('#tabs .tab[data-view="conversations"]');
      if (convTab) {
        convTab.disabled = true;
        convTab.classList.add('is-disabled');
        convTab.title = 'Run the live server (python cc_dashboard.py) to search & resume conversations';
      }
      return;
    }
    const search = byId('conv-search');
    if (search) {
      let timer = null;
      search.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(function () { loadConversations(search.value); }, 180);
      });
    }
  });

}());
