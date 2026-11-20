/* Light novel reader: MangaVibe opens text books (format "epub-text") here instead of its page reader
   (MangaVibe.registerReader, Plugin API 14). MangaVibe gives the whole reader screen (`el`) and `ctl`:
   ctl.page is the section to start at, ctl.save(section, completed) saves the book's progress (a
   section is a page of the book), ctl.leave() goes back, ctl.openBook("next") opens the next book.

   The text comes from this plugin's API already made safe (epub.py), so it's put in as it is.
   Two layouts: scrolling, or pages (CSS columns, each one screen wide: see layoutPages). How far into the
   section the reader is (0 to 1) is saved to the API, so the book opens there again on any device.
   The look (size, font, spacing, colours, width, layout) is per device, in localStorage. */
(() => {
"use strict";
const ID = "light-novel", API = `/api/plugins/${ID}/api`;
const FONTS = {
  serif: ['Serif', 'Charter, "Bitstream Charter", "Iowan Old Style", Georgia, "Noto Serif", "Noto Serif JP", serif'],
  sans: ['Sans', 'system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", "Noto Sans JP", sans-serif'],
};
const THEMES = { dark: "Dark", black: "Black", sepia: "Sepia", light: "Light" };
const WIDTHS = { 32: "Narrow", 40: "Medium", 52: "Wide" };  // the text's width, in em
const LINES = { 1.35: "Tight", 1.6: "Normal", 1.85: "Loose", 2.1: "Looser" };
const LAYOUTS = { scroll: "Scroll", pages: "Pages" };
const SIZES = [14, 15, 16, 17, 18, 19, 20, 22, 24, 26, 28, 32];
const DEFAULTS = { size: 19, line: 1.6, font: "serif", theme: "dark", width: 40, layout: "scroll", justify: false };
const PREFS_KEY = "light-novel:prefs";
const TAP_SIDE = 0.3;  // pages: the left and right parts of the screen that turn the page

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const svg = (d) => `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
  stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const ICONS = {
  back: svg('<path d="M19 12H5M11 6l-6 6 6 6"/>'),
  contents: svg('<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>'),
  settings: svg('<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>'),
  fullscreen: svg('<path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/>'),
  prev: svg('<path d="M15 6l-6 6 6 6"/>'),
  next: svg('<path d="M9 6l6 6-6 6"/>'),
  close: svg('<path d="M6 6l12 12M18 6L6 18"/>'),
};

function loadPrefs() {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") }; } catch { return { ...DEFAULTS }; }
}
function savePrefs() {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(P)); } catch {}
}
let P = loadPrefs();
let S = null;  // the open book (null while none is)

/* ---------------------------------------------------------------- opening and closing */

function open(el, book, ctl) {
  close();
  P = loadPrefs();
  S = { el, book, ctl, n: ctl.page, at: 0, sections: [], cache: new Map(), page: 0, pages: 1,
    panel: null, busy: 0, posTimer: null, posDirty: false, done: book.completed, abort: new AbortController() };
  el.innerHTML = `
    <div class="ln-root" tabindex="-1">
      <header class="ln-bar ln-top">
        <button class="ln-icon" data-do="back" aria-label="Back" title="Back">${ICONS.back}</button>
        <div class="ln-titles"><b>${esc(book.series_title)}</b><span class="ln-chapter"></span></div>
        <button class="ln-icon" data-do="contents" aria-label="Contents" title="Contents">${ICONS.contents}</button>
        <button class="ln-icon" data-do="settings" aria-label="Text and layout" title="Text and layout">${ICONS.settings}</button>
        <button class="ln-icon ln-fs" data-do="fullscreen" aria-label="Fullscreen" title="Fullscreen">${ICONS.fullscreen}</button>
      </header>
      <main class="ln-view"><article class="ln-text"></article></main>
      <footer class="ln-bar ln-bottom">
        <button class="ln-icon" data-do="prev-section" aria-label="Previous chapter" title="Previous chapter">${ICONS.prev}</button>
        <span class="ln-where" aria-live="polite"></span>
        <button class="ln-icon" data-do="next-section" aria-label="Next chapter" title="Next chapter">${ICONS.next}</button>
      </footer>
      <aside class="ln-panel" data-panel="contents" hidden></aside>
      <aside class="ln-panel" data-panel="settings" hidden></aside>
    </div>`;
  S.root = el.querySelector(".ln-root");
  S.view = el.querySelector(".ln-view");
  S.text = el.querySelector(".ln-text");
  if (!document.fullscreenEnabled) el.querySelector(".ln-fs").hidden = true;
  applyPrefs();
  bind();
  start(S);
}

async function start(s) {
  try {
    const info = await MangaVibe.api(`${API}/books/${s.book.id}`);
    if (S !== s) return;
    s.sections = info.sections;
    const pos = info.position;
    s.at = pos && pos.section === s.n ? pos.at : 0;
  } catch (e) {
    if (S === s) showError(e.message);
    return;
  }
  showSection(s.n, s.at, { save: false });
}

function close() {
  if (!S) return;
  flushPosition();
  S.abort.abort();
  clearTimeout(S.posTimer);
  S = null;
}

function showError(message) {
  S.text.innerHTML = `<div class="ln-message"><p>${esc(message)}</p>
    <button class="ln-btn" data-do="retry">Try again</button> <button class="ln-btn" data-do="back">Back</button></div>`;
}

/* ---------------------------------------------------------------- sections */

function titleOf(n) {
  for (let i = n; i >= 0; i--) if (S.sections[i]?.title) return S.sections[i].title;
  return `Section ${n + 1}`;
}

function fetchSection(n) {
  if (!S.cache.has(n)) {
    const p = MangaVibe.api(`${API}/books/${S.book.id}/sections/${n}`);
    p.catch(() => S?.cache.delete(n));
    S.cache.set(n, p);
  }
  return S.cache.get(n);
}

/* show section n at `at` (0: its start, 1: its end), or at the element with id `anchor` */
async function showSection(n, at = 0, { save = true, anchor = "" } = {}) {
  const s = S, count = s.book.page_count;
  n = Math.max(0, Math.min(n, count - 1));
  const ticket = ++s.busy;
  let sec;
  try { sec = await fetchSection(n); } catch (e) {
    if (S === s && ticket === s.busy) showError(e.message);
    return;
  }
  if (S !== s || ticket !== s.busy) return;  // left, or another section asked for meanwhile
  if (n !== s.n) flushPosition();  // the place in the section being left
  s.n = n;
  s.text.innerHTML = sec.html + endOfSection(n);
  layout();
  if (anchor) goToAnchor(anchor); else setAt(at);
  updateWhere();
  if (save) s.ctl.save(n);
  if (n + 1 < count) fetchSection(n + 1);  // ready for when this one ends
  setPanel(null);
}

function endOfSection(n) {
  const last = n === S.book.page_count - 1, next = S.book.next;
  if (!last) {
    return `<nav class="ln-end"><button class="ln-btn primary" data-do="next-section">Next: ${esc(titleOf(n + 1))}</button></nav>`;
  }
  return `<nav class="ln-end ln-finish"><p>The end of ${esc(S.book.label)}.</p>
    ${next ? `<button class="ln-btn primary" data-do="next-book">Next: ${esc(next.label)}</button>` : ""}
    <button class="ln-btn" data-do="back">Back to the series</button></nav>`;
}

/* ---------------------------------------------------------------- where in the section */

function layout() {
  const r = S.root;
  r.classList.toggle("ln-pages", P.layout === "pages");
  r.classList.toggle("ln-scroll", P.layout !== "pages");
  if (P.layout === "pages") layoutPages();
  else S.text.style.cssText = "";
}

/* Pages: the text flows into columns as tall as the screen. Each column is the text's width (W) and
   the gap between two is the rest of the screen (V - W), so one step of V shows exactly the next
   column in the same place: scrollLeft = page * V. */
function layoutPages() {
  const v = S.view, t = S.text;
  const V = v.clientWidth, H = v.clientHeight;
  const W = Math.min(V - 32, P.width * P.size);
  Object.assign(t.style, { width: `${W}px`, height: `${H}px`, columnWidth: `${W}px`, columnGap: `${V - W}px`,
    marginLeft: `${(V - W) / 2}px`, marginRight: "0px" });
  t.style.setProperty("--ln-h", `${H}px`);  // pictures fit in one page (reader.css)
  S.pages = Math.max(1, Math.ceil((v.scrollWidth - 1) / V));
}

function getAt() {
  const v = S.view;
  if (P.layout === "pages") return S.pages > 1 ? S.page / (S.pages - 1) : 1;
  const room = v.scrollHeight - v.clientHeight;
  return room > 0 ? v.scrollTop / room : 1;
}

function setAt(at) {
  const v = S.view;
  if (P.layout === "pages") return setPage(Math.round(at * (S.pages - 1)));
  v.scrollTop = at * (v.scrollHeight - v.clientHeight);
}

function setPage(i) {
  S.page = Math.max(0, Math.min(i, S.pages - 1));
  S.view.scrollLeft = S.page * S.view.clientWidth;
}

function goToAnchor(id) {
  const target = id && S.text.querySelector(`#${CSS.escape(id)}`);
  if (!target) return setAt(0);
  if (P.layout === "pages") {
    const x = target.getBoundingClientRect().left - S.view.getBoundingClientRect().left + S.view.scrollLeft;
    setPage(Math.floor(x / S.view.clientWidth));
  } else target.scrollIntoView({ block: "start" });
}

function updateWhere() {
  const s = S, at = getAt();
  s.root.querySelector(".ln-chapter").textContent = titleOf(s.n);
  const pct = Math.round(at * 100);
  s.root.querySelector(".ln-where").textContent = P.layout === "pages"
    ? `${s.n + 1} / ${s.book.page_count} · page ${s.page + 1} of ${s.pages}`
    : `${s.n + 1} / ${s.book.page_count} · ${pct}%`;
  s.root.querySelector('[data-do="prev-section"]').disabled = s.n === 0;
  s.root.querySelector('[data-do="next-section"]').disabled = s.n >= s.book.page_count - 1;
  // the end of the last section: the book is read
  if (!s.done && s.n === s.book.page_count - 1 && at >= 0.98) {
    s.done = true;
    s.ctl.save(s.n, true).catch(() => { s.done = false; });
  }
}

function positionMoved() {
  if (!S) return;
  updateWhere();
  S.posDirty = true;
  clearTimeout(S.posTimer);
  S.posTimer = setTimeout(flushPosition, 1200);
}

function flushPosition() {
  const s = S;
  if (!s || !s.posDirty || !s.sections.length) return;
  s.posDirty = false;
  clearTimeout(s.posTimer);
  // keepalive: still sent when the page is closed or the reader left
  fetch(`${API}/books/${s.book.id}/position`, { method: "PUT", keepalive: true,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ section: s.n, at: Math.max(0, Math.min(1, getAt())) }) }).catch(() => {});
}

/* ---------------------------------------------------------------- turning */

function forward() {
  const v = S.view;
  if (P.layout === "pages") {
    if (S.page < S.pages - 1) { setPage(S.page + 1); positionMoved(); return; }
  } else if (v.scrollTop + v.clientHeight < v.scrollHeight - 4) {
    v.scrollBy({ top: v.clientHeight * 0.9, behavior: "smooth" });
    return;
  }
  if (S.n < S.book.page_count - 1) showSection(S.n + 1, 0);
}

function backward() {
  const v = S.view;
  if (P.layout === "pages") {
    if (S.page > 0) { setPage(S.page - 1); positionMoved(); return; }
  } else if (v.scrollTop > 4) {
    v.scrollBy({ top: -v.clientHeight * 0.9, behavior: "smooth" });
    return;
  }
  if (S.n > 0) showSection(S.n - 1, 1);  // the previous section's end
}

function toggleBars(show = S.root.classList.contains("ln-bars-hidden")) {
  S.root.classList.toggle("ln-bars-hidden", !show);
}

/* ---------------------------------------------------------------- panels */

/* show a panel ("contents", "settings") or none; a button that opens the shown one closes it (toggle) */
function setPanel(name, toggle = false) {
  if (!S) return;
  S.panel = toggle && S.panel === name ? null : name;
  for (const p of S.root.querySelectorAll(".ln-panel")) p.hidden = p.dataset.panel !== S.panel;
  if (S.panel === "contents") drawContents();
  if (S.panel === "settings") drawSettings();
  if (S.panel) toggleBars(true);
}

function drawContents() {
  const box = S.root.querySelector('[data-panel="contents"]');
  const named = S.sections.map((x, i) => [i, x.title]).filter(([, t]) => t);
  const rows = named.length ? named : S.sections.map((_, i) => [i, `Section ${i + 1}`]);
  // the chapter being read: the last named one at or before this section
  const cur = rows.reduce((c, [i]) => (i <= S.n ? i : c), rows[0]?.[0]);
  box.innerHTML = `<div class="ln-panel-head"><b>Contents</b>
      <button class="ln-icon" data-do="close-panel" aria-label="Close">${ICONS.close}</button></div>
    <ol class="ln-toc">${rows.map(([i, t]) => `<li><button data-section="${i}" class="${i === cur ? "current" : ""}"
      ${i === cur ? 'aria-current="true"' : ""}>${esc(t)}</button></li>`).join("")}</ol>`;
  box.querySelector(".current")?.scrollIntoView({ block: "center" });
}

function chips(key, options, cur) {
  return `<div class="ln-chips" role="group">${Object.entries(options).map(([v, label]) =>
    `<button data-pref="${key}" data-value="${esc(v)}" aria-pressed="${String(v) === String(cur)}">${esc(label)}</button>`).join("")}</div>`;
}

function drawSettings() {
  const box = S.root.querySelector('[data-panel="settings"]');
  box.innerHTML = `<div class="ln-panel-head"><b>Text and layout</b>
      <button class="ln-icon" data-do="close-panel" aria-label="Close">${ICONS.close}</button></div>
    <div class="ln-setting"><span>Size</span><div class="ln-stepper">
      <button data-do="smaller" aria-label="Smaller text">A−</button><output>${P.size}</output>
      <button data-do="bigger" aria-label="Bigger text">A+</button></div></div>
    <div class="ln-setting"><span>Font</span>${chips("font", Object.fromEntries(Object.entries(FONTS).map(([k, [l]]) => [k, l])), P.font)}</div>
    <div class="ln-setting"><span>Spacing</span>${chips("line", LINES, P.line)}</div>
    <div class="ln-setting"><span>Width</span>${chips("width", WIDTHS, P.width)}</div>
    <div class="ln-setting"><span>Colours</span>${chips("theme", THEMES, P.theme)}</div>
    <div class="ln-setting"><span>Layout</span>${chips("layout", LAYOUTS, P.layout)}</div>
    <div class="ln-setting"><span>Justify</span>${chips("justify", { false: "Off", true: "On" }, P.justify)}</div>`;
}

function setPref(key, value) {
  const at = getAt();
  P[key] = ["size", "line", "width"].includes(key) ? +value
    : key === "justify" ? value === true || value === "true" : value;
  savePrefs();
  applyPrefs();
  layout();
  setAt(at);
  updateWhere();
  if (S.panel === "settings") drawSettings();
}

function applyPrefs() {
  const r = S.root;
  r.style.setProperty("--ln-size", `${P.size}px`);
  r.style.setProperty("--ln-line", P.line);
  r.style.setProperty("--ln-width", `${P.width}em`);
  r.style.setProperty("--ln-font", (FONTS[P.font] || FONTS.serif)[1]);
  for (const t of Object.keys(THEMES)) r.classList.toggle(`ln-theme-${t}`, P.theme === t);
  r.classList.toggle("ln-justify", !!P.justify);
}

/* ---------------------------------------------------------------- input */

function bind() {
  const s = S, signal = s.abort.signal;
  s.root.addEventListener("click", (e) => {
    const b = e.target.closest("button, a");
    if (!b || !s.root.contains(b)) return;
    if (b.matches("a[data-section]")) {  // a link inside the book (epub.py)
      e.preventDefault();
      const n = +b.dataset.section;
      if (n === s.n && b.dataset.anchor) { goToAnchor(b.dataset.anchor); positionMoved(); }
      else showSection(n, 0, { anchor: b.dataset.anchor });
      return;
    }
    if (b.dataset.section !== undefined) return showSection(+b.dataset.section, 0);
    if (b.dataset.pref) return setPref(b.dataset.pref, b.dataset.value);
    const act = {
      back: () => s.ctl.leave(), retry: () => start(s), fullscreen: () => s.ctl.fullscreen(),
      contents: () => setPanel("contents", true), settings: () => setPanel("settings", true),
      "close-panel": () => setPanel(null),
      "prev-section": () => showSection(s.n - 1, 0), "next-section": () => showSection(s.n + 1, 0),
      "next-book": () => s.ctl.openBook("next"),
      smaller: () => setPref("size", SIZES[Math.max(0, SIZES.findIndex((x) => x >= P.size) - 1)]),
      bigger: () => setPref("size", SIZES.find((x) => x > P.size) || P.size),
    }[b.dataset.do];
    if (act) act();
  });

  // taps on the text: the middle shows or hides the bars; in pages, the sides turn the page.
  // A swipe turns the page too; a drag that selects text does nothing.
  let down = null;
  s.view.addEventListener("pointerdown", (e) => { down = { x: e.clientX, y: e.clientY, t: performance.now() }; });
  s.view.addEventListener("pointerup", (e) => {
    if (!down || e.target.closest("a, button")) return (down = null);
    const dx = e.clientX - down.x, dy = e.clientY - down.y, quick = performance.now() - down.t < 600;
    down = null;
    if (s.panel) return setPanel(null);
    if (P.layout === "pages" && quick && Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) {
      return dx < 0 ? forward() : backward();
    }
    if (Math.hypot(dx, dy) > 10 || String(getSelection?.() || "")) return;
    const x = (e.clientX - s.view.getBoundingClientRect().left) / s.view.clientWidth;
    if (P.layout === "pages" && x < TAP_SIDE) return backward();
    if (P.layout === "pages" && x > 1 - TAP_SIDE) return forward();
    toggleBars();
  });
  s.view.addEventListener("scroll", () => {
    if (P.layout !== "pages") positionMoved();
  }, { passive: true });

  document.addEventListener("keydown", (e) => {
    if (S !== s || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "Escape") { e.preventDefault(); return s.panel ? setPanel(null) : s.ctl.leave(); }
    if (e.target.closest?.("input, select, textarea")) return;
    const fwd = { ArrowRight: 1, PageDown: 1, " ": e.shiftKey ? -1 : 1, ArrowLeft: -1, PageUp: -1 }[e.key];
    if (fwd) { e.preventDefault(); return fwd > 0 ? forward() : backward(); }
    if (P.layout !== "pages" && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault();
      s.view.scrollBy({ top: (e.key === "ArrowDown" ? 1 : -1) * 60 });
    } else if (e.key === "f" || e.key === "F") s.ctl.fullscreen();
  }, { signal });

  let resizeTimer = null;
  addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (S !== s) return;
      const at = getAt();
      layout();
      setAt(at);
      updateWhere();
    }, 150);
  }, { signal });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden" && S === s) flushPosition();
  }, { signal });
}

/* ---------------------------------------------------------------- MangaVibe's side */

MangaVibe.registerReader(ID, "epub-text", {
  open,
  close,
  step(forwardStep = true) { if (!S) return false; forwardStep ? forward() : backward(); return true; },
  goTo(n) { if (!S) return false; showSection(+n, 0); return true; },
  options(openIt = true) { if (!S) return false; setPanel(openIt ? "settings" : null); return true; },
  back() { if (S?.panel) { setPanel(null); return true; } return false; },
});
})();
