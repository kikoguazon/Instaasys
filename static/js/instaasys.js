/**
 * INSTAASYS UI Enhancement System  v1.0
 * ─────────────────────────────────────
 * Provides six reusable UI modules exposed on window.InstaUI:
 *   toast       – stacked, auto-dismissing notifications
 *   skeleton    – shimmer placeholder loaders
 *   modal       – focus-trap + scroll-lock modal enhancer
 *   InfiniteScroll – lazy, paginated list loader
 *   DebouncedSearch – request-cancelling async search
 *   DragDrop    – touch-aware, persisting drag-and-drop reorder
 */
(function (global) {
  'use strict';

  // ═══════════════════════════════════════════════════════
  //  1. TOAST NOTIFICATION SYSTEM
  // ═══════════════════════════════════════════════════════

  const TOAST_ICONS = {
    success: 'bi-check-circle-fill',
    error:   'bi-x-circle-fill',
    warning: 'bi-exclamation-triangle-fill',
    info:    'bi-info-circle-fill',
  };
  const TOAST_TITLES = { success: 'Success', error: 'Error', warning: 'Warning', info: 'Info' };
  const MAX_TOASTS = 5;
  const DEFAULT_DURATION = 4500; // ms

  class ToastSystem {
    constructor () {
      this._container = null;
      this._active = [];
    }

    _getContainer () {
      if (!this._container) {
        this._container = document.getElementById('insta-toast-container');
        if (!this._container) {
          this._container = document.createElement('div');
          this._container.id = 'insta-toast-container';
          document.body.appendChild(this._container);
        }
      }
      return this._container;
    }

    /**
     * show(message, type, options)
     * @param {string} message
     * @param {'success'|'error'|'warning'|'info'} type
     * @param {{ title?: string, duration?: number }} opts
     */
    show (message, type = 'info', opts = {}) {
      const container = this._getContainer();

      // Cap active toasts
      while (this._active.length >= MAX_TOASTS) {
        this._dismiss(this._active[0]);
      }

      const duration = opts.duration ?? DEFAULT_DURATION;
      const title    = opts.title ?? TOAST_TITLES[type] ?? 'Notice';
      const icon     = TOAST_ICONS[type] ?? 'bi-bell-fill';

      const el = document.createElement('div');
      el.className = `insta-toast toast-${type}`;
      el.setAttribute('role', 'alert');
      el.innerHTML = `
        <i class="bi ${icon} insta-toast-icon"></i>
        <div class="insta-toast-body">
          <div class="insta-toast-title">${_esc(title)}</div>
          <div class="insta-toast-msg">${_esc(message)}</div>
        </div>
        <button class="insta-toast-close" aria-label="Close">
          <i class="bi bi-x-lg"></i>
        </button>
        <div class="insta-toast-progress"
             style="animation-duration:${duration}ms;"></div>
      `;

      container.appendChild(el);
      this._active.push(el);

      // Animate in (next frame so the initial transform is rendered first)
      requestAnimationFrame(() => {
        requestAnimationFrame(() => el.classList.add('toast-in'));
      });

      // Close button
      el.querySelector('.insta-toast-close').addEventListener('click', () => {
        this._dismiss(el);
      });

      // Auto-dismiss
      const timer = setTimeout(() => this._dismiss(el), duration);
      el._toastTimer = timer;

      return el;
    }

    _dismiss (el) {
      if (!el || el._dismissing) return;
      el._dismissing = true;
      clearTimeout(el._toastTimer);
      el.classList.remove('toast-in');
      el.classList.add('toast-out');
      el.addEventListener('transitionend', () => {
        el.remove();
        const idx = this._active.indexOf(el);
        if (idx !== -1) this._active.splice(idx, 1);
      }, { once: true });
    }

    success (msg, opts) { return this.show(msg, 'success', opts); }
    error   (msg, opts) { return this.show(msg, 'error',   opts); }
    warning (msg, opts) { return this.show(msg, 'warning', opts); }
    info    (msg, opts) { return this.show(msg, 'info',    opts); }
  }


  // ═══════════════════════════════════════════════════════
  //  2. SKELETON LOADERS
  // ═══════════════════════════════════════════════════════

  const Skeleton = {
    /**
     * Insert skeleton placeholder HTML into `container`.
     * @param {Element} container
     * @param {'card'|'table'|'list'} type
     * @param {number} count  number of skeleton items
     */
    show (container, type = 'card', count = 3) {
      const frag = document.createDocumentFragment();
      for (let i = 0; i < count; i++) {
        const node = document.createElement(type === 'table' ? 'tr' : 'div');
        node.className = 'insta-skeleton-item';
        node.innerHTML = _skeletonHTML(type);
        frag.appendChild(node);
      }
      container.appendChild(frag);
    },

    /** Remove all skeleton items from container */
    hide (container) {
      container.querySelectorAll('.insta-skeleton-item').forEach(n => n.remove());
    },
  };

  function _skeletonHTML (type) {
    switch (type) {
      case 'table':
        return `<td><div class="skeleton-line sm" style="width:70%"></div></td>
                <td><div class="skeleton-line sm" style="width:40%"></div></td>
                <td><div class="skeleton-line sm" style="width:55%"></div></td>
                <td><div class="skeleton-line sm" style="width:30%"></div></td>`;
      case 'list':
        return `<div style="display:flex;align-items:center;gap:.75rem;padding:.75rem 1rem;border-bottom:1px solid #e2e8f0;">
                  <div class="skeleton-circle" style="width:36px;height:36px;flex-shrink:0;"></div>
                  <div style="flex:1;display:flex;flex-direction:column;gap:.5rem;">
                    <div class="skeleton-line" style="width:60%"></div>
                    <div class="skeleton-line sm" style="width:40%"></div>
                  </div>
                </div>`;
      default: // card
        return `<div class="skeleton-card-wrap">
                  <div class="skeleton-line sm" style="width:35%"></div>
                  <div class="skeleton-line lg" style="width:75%"></div>
                  <div class="skeleton-line sm" style="width:90%"></div>
                  <div class="skeleton-line sm" style="width:55%"></div>
                </div>`;
    }
  }


  // ═══════════════════════════════════════════════════════
  //  3. MODAL ENHANCER  (focus trap + scroll lock)
  // ═══════════════════════════════════════════════════════

  const ModalEnhancer = {
    _traps: new WeakMap(),

    init () {
      // Patch every Bootstrap modal on the page
      document.querySelectorAll('.modal').forEach(el => ModalEnhancer._enhance(el));

      // Also enhance modals added dynamically
      const observer = new MutationObserver(muts => {
        muts.forEach(m => m.addedNodes.forEach(n => {
          if (n.nodeType !== 1) return;
          if (n.classList && n.classList.contains('modal')) ModalEnhancer._enhance(n);
          n.querySelectorAll && n.querySelectorAll('.modal').forEach(m => ModalEnhancer._enhance(m));
        }));
      });
      observer.observe(document.body, { childList: true, subtree: true });
    },

    _enhance (modalEl) {
      if (this._traps.has(modalEl)) return;
      this._traps.set(modalEl, true);

      modalEl.addEventListener('shown.bs.modal', () => {
        document.body.style.overflow = 'hidden';
        this._trapFocus(modalEl);
      });
      modalEl.addEventListener('hidden.bs.modal', () => {
        document.body.style.overflow = '';
        this._releaseFocus(modalEl);
      });
    },

    _trapFocus (modalEl) {
      const focusable = () => Array.from(
        modalEl.querySelectorAll(
          'a[href],button:not([disabled]),input:not([disabled]),' +
          'select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
        )
      ).filter(el => !el.closest('[aria-hidden="true"]'));

      const handler = (e) => {
        if (e.key !== 'Tab') return;
        const nodes = focusable();
        if (!nodes.length) { e.preventDefault(); return; }
        const first = nodes[0], last = nodes[nodes.length - 1];
        if (e.shiftKey) {
          if (document.activeElement === first) { e.preventDefault(); last.focus(); }
        } else {
          if (document.activeElement === last)  { e.preventDefault(); first.focus(); }
        }
      };
      modalEl._focusTrapHandler = handler;
      modalEl.addEventListener('keydown', handler);

      // Focus first focusable element
      requestAnimationFrame(() => {
        const nodes = focusable();
        if (nodes.length) nodes[0].focus();
      });
    },

    _releaseFocus (modalEl) {
      if (modalEl._focusTrapHandler) {
        modalEl.removeEventListener('keydown', modalEl._focusTrapHandler);
        delete modalEl._focusTrapHandler;
      }
    },
  };


  // ═══════════════════════════════════════════════════════
  //  4. INFINITE SCROLL
  // ═══════════════════════════════════════════════════════

  /**
   * new InfiniteScroll({
   *   container:  Element  — list container to append items into
   *   url:        string   — base URL for JSON pages (?page=N appended)
   *   params:     object   — extra query params forwarded as-is
   *   skeletonType: 'card'|'table'|'list'
   *   skeletonCount: number
   *   onEmpty:    fn()     — called when first load returns 0 items
   * })
   */
  class InfiniteScroll {
    constructor (opts = {}) {
      this.container    = _el(opts.container);
      this.url          = opts.url;
      this.params       = opts.params || {};
      this.skeletonType = opts.skeletonType || 'card';
      this.skeletonCount = opts.skeletonCount || 3;
      this.uniqueAttr    = opts.uniqueAttr || 'data-lesson-id';
      this._onEmpty     = opts.onEmpty || null;
      this._page        = 1;
      this._loading     = false;
      this._done        = false;

      this._buildChrome();
      this._observe();
      this._loadPage(); // initial load
    }

    _buildChrome () {
      // Loading spinner row
      this._loader = document.createElement('div');
      this._loader.className = 'insta-load-more';
      this._loader.innerHTML = `
        <div class="spinner-border text-primary" role="status"></div>
        <span>Loading more…</span>`;
      this.container.after(this._loader);

      // End-of-list message
      this._endMsg = document.createElement('div');
      this._endMsg.className = 'insta-end-msg';
      this._endMsg.innerHTML = `<i class="bi bi-check2-all"></i> All items loaded`;
      this._loader.after(this._endMsg);

      // Sentinel (invisible trigger element)
      this._sentinel = document.createElement('div');
      this._sentinel.className = 'insta-sentinel';
      this._endMsg.after(this._sentinel);
    }

    _observe () {
      this._io = new IntersectionObserver(entries => {
        if (entries[0].isIntersecting) this._loadPage();
      }, { rootMargin: '200px' });
      this._io.observe(this._sentinel);
    }

    _buildURL () {
      const u = new URL(this.url, location.origin);
      u.searchParams.set('page', this._page);
      u.searchParams.set('format', 'json');
      Object.entries(this.params).forEach(([k, v]) => {
        if (v !== null && v !== undefined && v !== '') u.searchParams.set(k, v);
      });
      return u.toString();
    }

    async _loadPage () {
      if (this._loading || this._done) return;
      this._loading = true;

      // Show skeletons on first page
      if (this._page === 1) {
        Skeleton.show(this.container, this.skeletonType, this.skeletonCount);
      }
      this._loader.classList.add('visible');

      try {
        const resp = await fetch(this._buildURL(), {
          headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        Skeleton.hide(this.container);
        this._loader.classList.remove('visible');

        if (data.html) {
          const tmp = document.createElement('template');
          tmp.innerHTML = data.html;
          const fragment = tmp.content;

          // Prevent duplication by checking uniqueAttr
          if (this.uniqueAttr) {
            const incoming = Array.from(fragment.children);
            incoming.forEach(el => {
              const id = el.getAttribute(this.uniqueAttr);
              if (id && this.container.querySelector(`[${this.uniqueAttr}="${id}"]`)) {
                el.remove(); // Already exists in DOM
              }
            });
          }
          
          this.container.appendChild(fragment);
        }

        if (this._page === 1 && !data.html?.trim()) {
          // first page, empty
          if (this._onEmpty) this._onEmpty();
        }

        if (data.has_next) {
          this._page++;
        } else {
          this._done = true;
          this._io.disconnect();
          if (this.container.children.length > 0) {
            this._endMsg.classList.add('visible');
          }
        }
      } catch (err) {
        Skeleton.hide(this.container);
        this._loader.classList.remove('visible');
        console.error('[InfiniteScroll]', err);
        InstaUI.toast.error('Failed to load more items. Please refresh.');
        this._io.disconnect();
      } finally {
        this._loading = false;
      }
    }

    /** Reload from page 1 (useful after search/filter change) */
    reset (newParams = {}) {
      Object.assign(this.params, newParams);
      this._page   = 1;
      this._done   = false;
      this.container.innerHTML = '';
      this._endMsg.classList.remove('visible');
      this._io.observe(this._sentinel);
      this._loadPage();
    }
  }


  // ═══════════════════════════════════════════════════════
  //  5. DEBOUNCED SEARCH
  // ═══════════════════════════════════════════════════════

  /**
   * new DebouncedSearch({
   *   input:       Element|string  — the <input> element
   *   url:         string          — endpoint URL
   *   container:   Element|string  — element where results are rendered
   *   countEl:     Element|string  — optional element showing "N results"
   *   delay:       number          — debounce ms (default 400)
   *   minChars:    number          — min input length to search (default 0)
   *   highlight:   bool            — highlight matched text (default true)
   *   skeletonType: 'card'|'table'|'list'
   *   onResults:   fn(data)        — custom handler instead of innerHTML
   *   noResultsEl: Element|string  — shown when results are empty
   * })
   */
  class DebouncedSearch {
    constructor (opts = {}) {
      this._input     = _el(opts.input);
      this._url       = opts.url;
      this._container = _el(opts.container);
      this._countEl   = opts.countEl ? _el(opts.countEl) : null;
      this._delay     = opts.delay ?? 400;
      this._minChars  = opts.minChars ?? 0;
      this._highlight = opts.highlight !== false;
      this._skType    = opts.skeletonType || 'list';
      this._onResults = opts.onResults || null;
      this._noResultsEl = opts.noResultsEl ? _el(opts.noResultsEl) : null;
      this._timer     = null;
      this._ctrl      = null;   // AbortController

      // Wrap input in .search-wrap if not already
      if (!this._input.parentElement.classList.contains('search-wrap')) {
        const wrap = document.createElement('div');
        wrap.className = 'search-wrap';
        this._input.replaceWith(wrap);
        wrap.appendChild(this._input);
        const spinner = document.createElement('div');
        spinner.className = 'search-spinner';
        wrap.appendChild(spinner);
        this._wrap = wrap;
      } else {
        this._wrap = this._input.parentElement;
      }

      this._input.addEventListener('input', () => this._schedule());
    }

    _schedule () {
      clearTimeout(this._timer);
      const q = this._input.value;
      if (q.length < this._minChars && q.length !== 0) return;
      this._timer = setTimeout(() => this._execute(q), this._delay);
    }

    async _execute (q) {
      // Cancel previous in-flight request
      if (this._ctrl) this._ctrl.abort();
      this._ctrl = new AbortController();

      this._wrap.classList.add('searching');

      const u = new URL(this._url, location.origin);
      u.searchParams.set('q', q);
      u.searchParams.set('format', 'json');

      try {
        const resp = await fetch(u.toString(), {
          signal: this._ctrl.signal,
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        this._wrap.classList.remove('searching');

        if (this._onResults) {
          this._onResults(data, q);
        } else {
          this._container.innerHTML = data.html || '';
          if (this._highlight && q) _highlightText(this._container, q);
        }

        if (this._countEl && data.total !== undefined) {
          this._countEl.textContent = data.total;
        }

        const empty = !data.html?.trim() || data.total === 0;
        if (this._noResultsEl) {
          this._noResultsEl.classList.toggle('visible', empty);
        }

      } catch (err) {
        if (err.name === 'AbortError') return;
        this._wrap.classList.remove('searching');
        console.error('[DebouncedSearch]', err);
      }
    }

    /** Force a search with the current input value */
    trigger () {
      this._execute(this._input.value);
    }
  }

  function _highlightText (container, q) {
    if (!q) return;
    const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(`(${escaped})`, 'gi');
    _walkText(container, node => {
      if (!re.test(node.nodeValue)) return;
      const span = document.createElement('span');
      span.innerHTML = node.nodeValue.replace(re, '<mark class="search-highlight">$1</mark>');
      node.parentNode.replaceChild(span, node);
    });
  }

  function _walkText (el, fn) {
    const iter = document.createNodeIterator(el, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let n;
    while ((n = iter.nextNode())) nodes.push(n);
    nodes.forEach(fn);
  }


  // ═══════════════════════════════════════════════════════
  //  6. DRAG & DROP REORDERING
  // ═══════════════════════════════════════════════════════

  /**
   * new DragDrop({
   *   container:     Element|string  — the UL/TBODY/DIV containing items
   *   itemSelector:  string          — CSS selector for draggable items (e.g. 'tr', '.card')
   *   handleSelector:string          — CSS selector for drag handle inside item
   *   onReorder:     fn(newOrder)    — called with array of item keys after drop
   *   keyAttr:       string          — data attribute for item key (default 'data-index')
   *   saveUrl:       string          — optional POST URL to persist order
   *   saveCsrf:      string          — CSRF token for POST
   *   savePayloadKey:string          — key name in JSON body (default 'order')
   * })
   */
  class DragDrop {
    constructor (opts = {}) {
      this.container   = _el(opts.container);
      this.itemSel     = opts.itemSelector  || '[data-drag-item]';
      this.handleSel   = opts.handleSelector || '.drag-handle';
      this.onReorder   = opts.onReorder     || null;
      this.keyAttr     = opts.keyAttr       || 'data-index';
      this.saveUrl     = opts.saveUrl       || null;
      this.saveCsrf    = opts.saveCsrf      || _getCsrf();
      this.saveKey     = opts.savePayloadKey|| 'order';

      this._dragEl     = null;
      this._ghostEl    = null;
      this._touchY     = 0;

      this._init();
    }

    _init () {
      this.container.addEventListener('dragstart',  e => this._onDragStart(e));
      this.container.addEventListener('dragend',    e => this._onDragEnd(e));
      this.container.addEventListener('dragover',   e => this._onDragOver(e));
      this.container.addEventListener('dragleave',  e => this._onDragLeave(e));
      this.container.addEventListener('drop',       e => this._onDrop(e));

      // Touch support
      this.container.addEventListener('touchstart', e => this._onTouchStart(e), { passive: false });
      this.container.addEventListener('touchmove',  e => this._onTouchMove(e),  { passive: false });
      this.container.addEventListener('touchend',   e => this._onTouchEnd(e));

      this._applyHandles();

      // Re-apply when container children change
      new MutationObserver(() => this._applyHandles()).observe(
        this.container, { childList: true }
      );
    }

    _applyHandles () {
      this.container.querySelectorAll(this.itemSel).forEach(item => {
        if (item._dndInit) return;
        item._dndInit = true;
        item.classList.add('drag-item');
        // Make only the handle draggable, not the whole item
        const handle = item.querySelector(this.handleSel);
        if (handle) {
          handle.addEventListener('mousedown', () => { item.draggable = true; });
          handle.addEventListener('mouseup',   () => { item.draggable = false; });
          item.draggable = false;
        } else {
          item.draggable = true;
        }
      });
    }

    _onDragStart (e) {
      const item = e.target.closest(this.itemSel);
      if (!item) return;
      this._dragEl = item;
      item.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', '');
    }

    _onDragEnd (e) {
      if (this._dragEl) {
        this._dragEl.classList.remove('dragging');
        this._dragEl.draggable = false;
        this._dragEl = null;
      }
      this.container.querySelectorAll('.drag-over-top, .drag-over-bottom')
          .forEach(el => el.classList.remove('drag-over-top', 'drag-over-bottom'));
    }

    _onDragOver (e) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      const target = e.target.closest(this.itemSel);
      if (!target || target === this._dragEl) return;

      this.container.querySelectorAll('.drag-over-top, .drag-over-bottom')
          .forEach(el => el.classList.remove('drag-over-top', 'drag-over-bottom'));

      const rect = target.getBoundingClientRect();
      const half = rect.top + rect.height / 2;
      target.classList.add(e.clientY < half ? 'drag-over-top' : 'drag-over-bottom');
    }

    _onDragLeave (e) {
      const target = e.target.closest(this.itemSel);
      if (target) target.classList.remove('drag-over-top', 'drag-over-bottom');
    }

    _onDrop (e) {
      e.preventDefault();
      const target = e.target.closest(this.itemSel);
      if (!target || !this._dragEl || target === this._dragEl) return;

      const before = target.classList.contains('drag-over-top');
      target.classList.remove('drag-over-top', 'drag-over-bottom');

      if (before) {
        this.container.insertBefore(this._dragEl, target);
      } else {
        this.container.insertBefore(this._dragEl, target.nextSibling);
      }

      this._finalize();
    }

    _finalize () {
      const items = Array.from(this.container.querySelectorAll(this.itemSel));
      const newOrder = items.map(el => el.getAttribute(this.keyAttr));

      if (this.onReorder) this.onReorder(newOrder);
      if (this.saveUrl)   this._persist(newOrder);
    }

    async _persist (order) {
      try {
        const resp = await fetch(this.saveUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken':  this.saveCsrf,
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: JSON.stringify({ [this.saveKey]: order }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        InstaUI.toast.success('Order saved.', { duration: 2000 });
      } catch (err) {
        console.error('[DragDrop persist]', err);
        InstaUI.toast.error('Failed to save order.');
      }
    }

    // ── Touch support ─────────────────────────────────────────────
    _onTouchStart (e) {
      const handle = e.target.closest(this.handleSel);
      if (!handle) return;
      const item = handle.closest(this.itemSel);
      if (!item) return;

      e.preventDefault();
      this._dragEl  = item;
      this._touchY  = e.touches[0].clientY;
      item.classList.add('dragging');
    }

    _onTouchMove (e) {
      if (!this._dragEl) return;
      e.preventDefault();
      const touch   = e.touches[0];
      const elBelow = document.elementFromPoint(touch.clientX, touch.clientY);
      const target  = elBelow && elBelow.closest(this.itemSel);

      this.container.querySelectorAll('.drag-over-top, .drag-over-bottom')
          .forEach(el => el.classList.remove('drag-over-top', 'drag-over-bottom'));

      if (target && target !== this._dragEl) {
        const rect  = target.getBoundingClientRect();
        const half  = rect.top + rect.height / 2;
        target.classList.add(touch.clientY < half ? 'drag-over-top' : 'drag-over-bottom');
      }
    }

    _onTouchEnd (e) {
      if (!this._dragEl) return;
      const touch   = e.changedTouches[0];
      const elBelow = document.elementFromPoint(touch.clientX, touch.clientY);
      const target  = elBelow && elBelow.closest(this.itemSel);

      if (target && target !== this._dragEl) {
        const before = target.classList.contains('drag-over-top');
        target.classList.remove('drag-over-top', 'drag-over-bottom');
        if (before) {
          this.container.insertBefore(this._dragEl, target);
        } else {
          this.container.insertBefore(this._dragEl, target.nextSibling);
        }
        this._finalize();
      }

      this._dragEl.classList.remove('dragging');
      this._dragEl = null;
      this.container.querySelectorAll('.drag-over-top, .drag-over-bottom')
          .forEach(el => el.classList.remove('drag-over-top', 'drag-over-bottom'));
    }
  }


  // ═══════════════════════════════════════════════════════
  //  UTILITIES
  // ═══════════════════════════════════════════════════════

  function _el (ref) {
    if (!ref) return null;
    return typeof ref === 'string' ? document.querySelector(ref) : ref;
  }

  function _esc (str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _getCsrf () {
    const el = document.querySelector('[name=csrfmiddlewaretoken]');
    return el ? el.value : '';
  }


  // ═══════════════════════════════════════════════════════
  //  GLOBAL EXPOSURE
  // ═══════════════════════════════════════════════════════

  const toast = new ToastSystem();

  global.InstaUI = {
    toast,
    skeleton:      Skeleton,
    modal:         ModalEnhancer,
    InfiniteScroll,
    DebouncedSearch,
    DragDrop,
  };

  // Auto-init modal enhancer on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => ModalEnhancer.init());
  } else {
    ModalEnhancer.init();
  }

  // Bridge: convert Django flash message alerts to toasts on DOMContentLoaded
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-django-message]').forEach(el => {
      const type = el.dataset.djangoMessageType || 'info';
      const msg  = el.dataset.djangoMessage;
      const map  = { success: 'success', error: 'error', danger: 'error', warning: 'warning', info: 'info', debug: 'info' };
      toast.show(msg, map[type] || 'info');
      el.remove();
    });
  });

})(window);
