/* ============================================================
   WE 壁纸播放器 — 前端逻辑
   ============================================================ */
'use strict';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const ic = (name) => `<svg class="ic"><use href="#i-${name}"></use></svg>`;

const el = {
  subtitle: $('#subtitle'),
  search: $('#search'),
  clearSearch: $('#clearSearch'),
  btnRandom: $('#btnRandom'),
  btnPlayAll: $('#btnPlayAll'),
  btnRescan: $('#btnRescan'),
  btnHelp: $('#btnHelp'),
  btnResetFilter: $('#btnResetFilter'),
  fFolder: $('#fFolder'),
  folderHint: $('#folderHint'),
  btnGroup: $('#btnGroup'),
  fType: $('#fType'),
  fSource: $('#fSource'),
  fState: $('#fState'),
  fTags: $('#fTags'),
  count: $('#count'),
  sort: $('#sort'),
  density: $('#density'),
  segThumb: $('#density .seg-thumb'),
  toolbar: $('.toolbar'),
  content: $('.content'),
  grid: $('#grid'),
  empty: $('#empty'),
  emptyHint: $('#emptyHint'),

  player: $('#player'),
  stage: $('#stage'),
  stageTop: $('#stageTop'),
  video: $('#video'),
  fallbackPreview: $('#fallbackPreview'),
  stageMessage: $('#stageMessage'),
  btnBack: $('#btnBack'),
  playerTitle: $('#playerTitle'),
  playerSub: $('#playerSub'),
  btnFav: $('#btnFav'),
  btnExternal: $('#btnExternal'),
  btnReveal: $('#btnReveal'),
  btnPip: $('#btnPip'),
  btnFullscreen: $('#btnFullscreen'),
  bigPrev: $('#bigPrev'),
  bigPlay: $('#bigPlay'),
  bigNext: $('#bigNext'),
  flash: $('#flash'),
  timeCur: $('#timeCur'),
  timeDur: $('#timeDur'),
  bar: $('#bar'),
  barBuffer: $('#barBuffer'),
  barPlayed: $('#barPlayed'),
  btnPrev: $('#btnPrev'),
  btnPlay: $('#btnPlay'),
  btnNext: $('#btnNext'),
  btnMute: $('#btnMute'),
  volume: $('#volume'),
  speed: $('#speed'),
  btnLoop: $('#btnLoop'),
  btnShuffle: $('#btnShuffle'),
  btnAutonext: $('#btnAutonext'),
  btnPlaylist: $('#btnPlaylist'),
  effectStatus: $('#effectStatus'),
  effectStatusText: $('#effectStatusText'),
  btnEffectRaise: $('#btnEffectRaise'),
  btnEffectClose: $('#btnEffectClose'),
  plCountBadge: $('#plCountBadge'),
  playlist: $('#playlist'),
  plList: $('#plList'),
  plCount: $('#plCount'),

  ctxMenu: $('#ctxMenu'),
  modal: $('#modal'),
  modalTitle: $('#modalTitle'),
  modalBody: $('#modalBody'),
  modalClose: $('#modalClose'),
  toast: $('#toast'),
};

const app = {
  items: [],
  filtered: [],
  stats: {},
  dataMode: new URLSearchParams(location.search).get('data') || '',
  devMode: false,
  state: { favorites: {}, positions: {}, watched: {}, settings: {} },
  palette: 'valley',
  filters: { q: '', types: new Set(), sources: new Set(), tags: new Set(), folders: new Set(), onlyFav: false, onlyUnwatched: false, onlyWatched: false },
  sort: 'subscribed',
  density: 'm',
  groupByFolder: false,
  index: -1,
  shuffle: false,
  loop: false,
  autonext: true,
  idleTimer: null,
  saveTimer: null,
  pendingPatch: { favorites: {}, positions: {}, watched: {}, settings: {} },
};

/* ---------------------------------------------------------- 工具 */
function fmtTime(sec) {
  if (!isFinite(sec) || sec < 0) return '00:00';
  sec = Math.floor(sec);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const p = (n) => String(n).padStart(2, '0');
  return h > 0 ? `${h}:${p(m)}:${p(s)}` : `${p(m)}:${p(s)}`;
}

function toast(msg, ms = 1900) {
  el.toast.textContent = msg;
  el.toast.classList.remove('hidden');
  requestAnimationFrame(() => el.toast.classList.add('show'));
  clearTimeout(toast._t);
  toast._t = setTimeout(() => {
    el.toast.classList.remove('show');
    setTimeout(() => el.toast.classList.add('hidden'), 220);
  }, ms);
}

function flash(text, ms = 700) {
  el.flash.textContent = text;
  el.flash.classList.add('show');
  clearTimeout(flash._t);
  flash._t = setTimeout(() => el.flash.classList.remove('show'), ms);
}

function escapeHtml(str) {
  return String(str == null ? '' : str).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/* 计数一律走本地化格式：1284 → 1,284（否则四位以上读起来费劲） */
const numFmt = (() => {
  try { return new Intl.NumberFormat('zh-CN'); } catch (e) { return { format: (n) => String(n) }; }
})();
function fmtNum(n) {
  const v = Number(n);
  return Number.isFinite(v) ? numFmt.format(v) : String(n);
}

async function api(path, body) {
  const opts = body === undefined
    ? { method: 'GET' }
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const resp = await fetch(path, opts);
  if (!resp.ok) throw new Error(`${path} -> ${resp.status}`);
  return resp.json();
}

/* ---------------------------------------------------------- 开发用数据开关
   只在服务端 --dev 时出现：Demo data / Worst case / Empty / One / Many。
   选择写回 URL，刷新后保持。普通运行（不带 --dev）永远看不到它。 */
const DEV_STATES = [
  ['', 'Demo data'],
  ['worst', 'Worst case'],
  ['empty', 'Empty'],
  ['one', 'One'],
  ['many', '1,284 rows'],
];

/* ---------------------------------------------------------- 配色
   终末地官方两套配色：谷地黄（默认，ECP 用的那套）与武陵青。 */
const PALETTES = ['valley', 'wuling'];

function setPalette(name, persist) {
  const p = PALETTES.includes(name) ? name : 'valley';
  app.palette = p;
  document.documentElement.dataset.palette = p;
  $$('.palette-swatch').forEach((b) => b.classList.toggle('active', b.dataset.palette === p));
  if (persist) patch('settings', 'palette', p);
}

function renderDevToggle() {
  let bar = document.getElementById('devToggle');
  if (!app.devMode) { if (bar) bar.remove(); return; }
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'devToggle';
    bar.innerHTML = DEV_STATES
      .map(([v, label]) => `<button data-mode="${v}">${label}</button>`).join('');
    bar.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      const url = new URL(location.href);
      if (btn.dataset.mode) url.searchParams.set('data', btn.dataset.mode);
      else url.searchParams.delete('data');
      location.href = url.toString();
    });
    document.body.appendChild(bar);
  }
  bar.querySelectorAll('button').forEach((b) => {
    b.classList.toggle('active', (b.dataset.mode || '') === app.dataMode);
  });
}

/* 仅开发用：?ui=help|info|menu|playlist 直接进入某个瞬时状态（截图/回归用） */
function applyDevUI() {
  const ui = app.devMode ? new URLSearchParams(location.search).get('ui') : null;
  if (!ui) return;
  if (ui === 'help') toggleHelp(false);
  else if (ui === 'info') toggleHelp(true);
  else if (ui === 'menu' && app.filtered.length) {
    const card = el.grid.querySelector('.card');
    const box = card ? card.getBoundingClientRect() : { left: 300, top: 200 };
    showContextMenu(box.left + 120, box.top + 96, app.filtered[0]);
  } else if (ui === 'playlist') {
    el.player.classList.add('playlist-open');
    el.btnPlaylist.classList.add('active');
  }
}

/* ---------------------------------------------------------- 状态持久化 */
function patch(section, key, value) {
  app.state[section][key] = value;
  app.pendingPatch[section][key] = value;
  clearTimeout(app.saveTimer);
  app.saveTimer = setTimeout(flushPatch, 700);
}

function flushPatch() {
  const payload = {};
  let empty = true;
  for (const section of Object.keys(app.pendingPatch)) {
    const obj = app.pendingPatch[section];
    if (Object.keys(obj).length) { payload[section] = obj; empty = false; }
  }
  app.pendingPatch = { favorites: {}, positions: {}, watched: {}, settings: {} };
  if (empty) return;
  fetch('/api/state', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => { });
}

window.addEventListener('pagehide', () => {
  flushPatch();
  try { navigator.sendBeacon('/api/bye', new Blob(['{}'], { type: 'application/json' })); } catch (e) { }
});

/* 心跳：窗口还开着就保持服务运行 */
setInterval(() => { fetch('/api/ping', { method: 'POST' }).catch(() => { }); }, 15000);

/* ---------------------------------------------------------- 载入数据 */
async function loadLibrary(rescan) {
  el.subtitle.textContent = rescan ? '正在重新扫描壁纸目录…' : '正在扫描壁纸…';
  try {
    if (rescan) await api('/api/rescan', { force: false });
    const data = await api('/api/library' + (app.dataMode ? '?data=' + encodeURIComponent(app.dataMode) : ''));
    app.items = data.items || [];
    app.state = Object.assign({ favorites: {}, positions: {}, watched: {}, settings: {} }, data.state || {});
    app.stats = data.stats || {};
    app.devMode = !!(data.dev || (data.stats && data.stats.dev));
    renderDevToggle();
    const s = app.state.settings || {};
    if (s.sort) app.sort = s.sort;
    if (s.density) app.density = s.density;
    setPalette(s.palette || 'valley');
    // 仅开发用：?density=s|m|l 便于在固定宽度下压测卡片
    const devDensity = app.devMode ? new URLSearchParams(location.search).get('density') : null;
    if (devDensity && 'sml'.includes(devDensity)) app.density = devDensity;
    if (typeof s.groupByFolder === 'boolean') app.groupByFolder = s.groupByFolder;
    if (typeof s.autonext === 'boolean') app.autonext = s.autonext;
    if (typeof s.volume === 'number') { el.volume.value = s.volume; el.video.volume = s.volume; }
    el.sort.value = app.sort;
    setDensity(app.density, false);
    el.btnGroup.classList.toggle('active', app.groupByFolder);
    syncToggles();
    buildFilters();
    applyFilters();
    openFromHash();
    applyDevUI();
    const videoCount = app.items.filter((i) => i.hasVideo).length;
    const folderCount = (app.stats.weFolders || []).length;
    el.subtitle.textContent = `已收录 ${fmtNum(app.items.length)} 个壁纸 · 视频 ${fmtNum(videoCount)} 个`
      + (folderCount ? ` · WE 文件夹 ${fmtNum(folderCount)} 个` : '')
      + ` · 扫描耗时 ${app.stats.seconds || 0}s`;
  } catch (err) {
    el.subtitle.textContent = '加载失败：' + err.message;
    toast('加载壁纸列表失败：' + err.message, 4000);
  }
}

/* ---------------------------------------------------------- 筛选器 */
function buildFilters() {
  const typeCount = {}, sourceCount = {}, tagCount = {}, folderCount = {};
  let favCount = 0, unwatched = 0, watched = 0, unclassified = 0;
  for (const it of app.items) {
    typeCount[it.type] = (typeCount[it.type] || 0) + 1;
    sourceCount[it.sourceLabel] = (sourceCount[it.sourceLabel] || 0) + 1;
    for (const t of it.tags) tagCount[t] = (tagCount[t] || 0) + 1;
    if (it.weFolder) folderCount[it.weFolder] = (folderCount[it.weFolder] || 0) + 1;
    else unclassified++;
    if (app.state.favorites[it.key]) favCount++;
    if (app.state.watched[it.key]) watched++; else unwatched++;
  }

  const chip = (label, count, active, dataset) => {
    const attrs = Object.entries(dataset).map(([k, v]) => `data-${k}="${escapeHtml(v)}"`).join(' ');
    return `<button class="chip${active ? ' active' : ''}" ${attrs} title="${escapeHtml(label)}">`
      + `<span class="chip-name">${escapeHtml(label)}</span><span class="n">${fmtNum(count)}</span></button>`;
  };

  /* ---- Wallpaper Engine 文件夹（保持层级与顺序） ---- */
  const nodes = app.stats.weFolders || [];
  if (nodes.length) {
    el.folderHint.textContent = `${fmtNum(nodes.length)} 个`;
    el.fFolder.innerHTML = nodes.map((f) => {
      const active = app.filters.folders.has(f.path);
      return `<button class="chip folder${active ? ' active' : ''}" data-folder="${escapeHtml(f.path)}"
        style="margin-left:${f.depth * 12}px" title="${escapeHtml(f.path)}"
        ><span class="chip-name">${f.depth ? '└ ' : ''}${escapeHtml(f.title)}</span><span class="n">${fmtNum(folderCount[f.path] || 0)}</span></button>`;
    }).join('') + (unclassified ? chip('未分类', unclassified, app.filters.folders.has(''), { folder: '' }) : '');
  } else {
    el.folderHint.textContent = '';
    el.fFolder.innerHTML = `<div class="hint">没有检测到 Wallpaper Engine 文件夹。<br>
      在 WE 的「已安装」里建好文件夹并移动壁纸后，关闭一次 WE（让配置写入磁盘），再点「重新扫描」。</div>`;
  }

  el.fType.innerHTML = ['video', 'scene', 'web', 'application']
    .filter((t) => typeCount[t])
    .map((t) => chip(typeLabel(t), typeCount[t], app.filters.types.has(t), { type: t })).join('');

  el.fSource.innerHTML = Object.keys(sourceCount).map((s) => chip(s, sourceCount[s], app.filters.sources.has(s), { source: s })).join('');

  el.fState.innerHTML =
    chip('❤ 收藏', favCount, app.filters.onlyFav, { statefilter: 'fav' }) +
    chip('未看', unwatched, app.filters.onlyUnwatched, { statefilter: 'unwatched' }) +
    chip('已看', watched, app.filters.onlyWatched, { statefilter: 'watched' });

  const tags = Object.entries(tagCount).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  el.fTags.innerHTML = tags.map(([t, n]) => chip(t, n, app.filters.tags.has(t), { tag: t })).join('');

  // 空的筛选组不要留一个孤零零的标题
  const groupOf = (el2) => el2.closest('.filter-group');
  [[el.fFolder, nodes.length ? 1 : 0], [el.fType, el.fType.children.length],
   [el.fSource, el.fSource.children.length], [el.fState, 3],
   [el.fTags, el.fTags.children.length]].forEach(([node, n]) => {
    const g = groupOf(node);
    if (g) g.classList.toggle('hidden', !n);
  });
}

function typeLabel(type) {
  return { video: '视频', scene: '场景', web: '网页', application: '应用', text: '文字', preset: '预设' }[type] || type;
}

function toggleSet(set, value) {
  if (set.has(value)) set.delete(value); else set.add(value);
}

el.fType.addEventListener('click', (e) => { const b = e.target.closest('[data-type]'); if (!b) return; toggleSet(app.filters.types, b.dataset.type); buildFilters(); applyFilters(); });
el.fSource.addEventListener('click', (e) => { const b = e.target.closest('[data-source]'); if (!b) return; toggleSet(app.filters.sources, b.dataset.source); buildFilters(); applyFilters(); });
el.fTags.addEventListener('click', (e) => { const b = e.target.closest('[data-tag]'); if (!b) return; toggleSet(app.filters.tags, b.dataset.tag); buildFilters(); applyFilters(); });
el.fFolder.addEventListener('click', (e) => {
  const b = e.target.closest('[data-folder]');
  if (!b) return;
  toggleSet(app.filters.folders, b.dataset.folder);
  buildFilters(); applyFilters();
});
el.fState.addEventListener('click', (e) => {
  const b = e.target.closest('[data-statefilter]'); if (!b) return;
  const kind = b.dataset.statefilter;
  if (kind === 'fav') app.filters.onlyFav = !app.filters.onlyFav;
  if (kind === 'unwatched') app.filters.onlyUnwatched = !app.filters.onlyUnwatched;
  if (kind === 'watched') app.filters.onlyWatched = !app.filters.onlyWatched;
  buildFilters(); applyFilters();
});

el.btnResetFilter.addEventListener('click', () => {
  app.filters = { q: '', types: new Set(), sources: new Set(), tags: new Set(), folders: new Set(), onlyFav: false, onlyUnwatched: false, onlyWatched: false };
  el.search.value = '';
  el.clearSearch.classList.add('hidden');
  buildFilters(); applyFilters();
});

el.search.addEventListener('input', () => {
  app.filters.q = el.search.value.trim().toLowerCase();
  el.clearSearch.classList.toggle('hidden', !el.search.value);
  applyFilters();
});
el.clearSearch.addEventListener('click', () => {
  el.search.value = ''; app.filters.q = '';
  el.clearSearch.classList.add('hidden');
  applyFilters(); el.search.focus();
});

el.sort.addEventListener('change', () => { app.sort = el.sort.value; patch('settings', 'sort', app.sort); applyFilters(); });

/* iOS 分段控件：滑块滑到当前项，而不是各自变色 */
function positionSegThumb() {
  if (!el.density || !el.segThumb) return;
  const active = el.density.querySelector('button.active');
  if (!active) { el.segThumb.style.opacity = '0'; return; }
  const segRect = el.density.getBoundingClientRect();
  const btnRect = active.getBoundingClientRect();
  el.segThumb.style.opacity = '1';
  el.density.style.setProperty('--seg-x', (btnRect.left - segRect.left) + 'px');
  el.density.style.setProperty('--seg-w', btnRect.width + 'px');
}

function setDensity(size, persist = true) {
  app.density = size;
  el.grid.className = 'grid size-' + size;
  $$('#density button').forEach((b) => {
    const on = b.dataset.size === size;
    b.classList.toggle('active', on);
    b.setAttribute('aria-checked', on ? 'true' : 'false');
  });
  positionSegThumb();
  if (persist) patch('settings', 'density', size);
}
el.density.addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) setDensity(b.dataset.size); });

/* 工具条是浮动层：把它的高度告诉网格（避免盖住第一行），并在滚动后显示边缘渐隐 */
function measureChrome() {
  if (el.toolbar) document.documentElement.style.setProperty('--toolbar-h', el.toolbar.offsetHeight + 'px');
  // 工具条一换行，分段控件的位置就变了，滑块必须重新对齐
  positionSegThumb();
}
if (window.ResizeObserver && el.toolbar) new ResizeObserver(measureChrome).observe(el.toolbar);
window.addEventListener('resize', measureChrome);
if (document.fonts && document.fonts.ready) {
  // 字体加载完宽度会变，滑块要再量一次
  document.fonts.ready.then(() => measureChrome()).catch(() => { });
}
if (el.grid && el.content) {
  el.grid.addEventListener('scroll', () => {
    el.content.dataset.scrolled = el.grid.scrollTop > 4 ? 'true' : 'false';
  }, { passive: true });
}

el.btnGroup.addEventListener('click', () => {
  app.groupByFolder = !app.groupByFolder;
  el.btnGroup.classList.toggle('active', app.groupByFolder);
  patch('settings', 'groupByFolder', app.groupByFolder);
  renderGrid();
  toast(app.groupByFolder ? '已按 Wallpaper Engine 文件夹分组' : '已切换为平铺显示', 1300);
});

/* ---------------------------------------------------------- 过滤 + 渲染 */
function applyFilters() {
  const f = app.filters;
  let list = app.items.filter((it) => {
    if (f.types.size && !f.types.has(it.type)) return false;
    if (f.sources.size && !f.sources.has(it.sourceLabel)) return false;
    if (f.tags.size && !it.tags.some((t) => f.tags.has(t))) return false;
    if (f.folders.size) {
      // 选中父文件夹时连同子文件夹一起显示（分级过滤）
      const hit = [...f.folders].some((sel) => (sel === ''
        ? !it.weFolder
        : (it.weFolder === sel || it.weFolder.startsWith(sel + ' / '))));
      if (!hit) return false;
    }
    if (f.onlyFav && !app.state.favorites[it.key]) return false;
    if (f.onlyUnwatched && app.state.watched[it.key]) return false;
    if (f.onlyWatched && !app.state.watched[it.key]) return false;
    if (f.q) {
      const hay = (it.title + ' ' + it.tags.join(' ') + ' ' + it.id + ' ' + it.typeLabel + ' ' + it.sourceLabel + ' ' + (it.weFolder || '')).toLowerCase();
      if (!hay.includes(f.q)) return false;
    }
    return true;
  });

  const by = {
    subscribed: (a, b) => (b.subscribedAt || 0) - (a.subscribedAt || 0),
    added: (a, b) => b.mtime - a.mtime,
    title: (a, b) => a.title.localeCompare(b.title, 'zh-Hans-CN'),
    duration: (a, b) => (b.duration || 0) - (a.duration || 0),
    size: (a, b) => b.size - a.size,
    weorder: (a, b) => (a.weFolderOrder - b.weFolderOrder) || (a.weOrder - b.weOrder),
    random: () => Math.random() - 0.5,
  }[app.sort] || ((a, b) => (b.subscribedAt || 0) - (a.subscribedAt || 0));
  list.sort(by);

  app.filtered = list;
  renderGrid();
  renderPlaylist();
  updateCount();
}

function updateCount() {
  const videos = app.filtered.filter((i) => i.hasVideo).length;
  const folders = new Set(app.filtered.map((i) => i.weFolder).filter(Boolean)).size;
  el.count.innerHTML = `共 <b>${fmtNum(app.filtered.length)}</b> 个壁纸 · 可播放视频 <b>${fmtNum(videos)}</b> 个`
    + (folders ? ` · 涉及 <b>${fmtNum(folders)}</b> 个 WE 文件夹` : '');
}

/* 缩略图按需加载：进入视口才真正加载 GIF；滚出视口就卸载，
   避免几十个 GIF 同时解码把 CPU 吃满。 */
const thumbObserver = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    const img = entry.target;
    if (entry.isIntersecting) {
      if (!img.getAttribute('src') && img.dataset.src) img.src = img.dataset.src;
    } else if (img.getAttribute('src')) {
      img.removeAttribute('src');
    }
  }
}, { root: el.grid, rootMargin: '300px 0px' });

function renderGrid() {
  if (!app.filtered.length) {
    el.grid.innerHTML = '';
    el.grid.classList.add('hidden');
    el.empty.classList.remove('hidden');
    el.emptyHint.textContent = app.items.length
      ? '试试放宽筛选条件，或点左侧「重置」。'
      : '没有扫描到壁纸。请确认 Wallpaper Engine 已下载壁纸，或在 data/config.json 的 extra_libraries 里手工填写 Steam 库路径。';
    return;
  }
  el.grid.classList.remove('hidden');
  el.empty.classList.add('hidden');

  const posOf = new Map(app.filtered.map((it, i) => [it.key, i]));
  const frag = document.createDocumentFragment();

  if (app.groupByFolder) {
    /* ---- 按 Wallpaper Engine 的文件夹分组（保持层级与顺序） ---- */
    const groups = new Map();
    for (const it of app.filtered) {
      const k = it.weFolder || '';
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(it);
    }
    const meta = new Map((app.stats.weFolders || []).map((f) => [f.path, f]));
    const keys = [...groups.keys()].sort((a, b) => {
      if (!a) return 1;                          // 未分类排最后
      if (!b) return -1;
      const ma = meta.get(a), mb = meta.get(b);
      const oa = ma ? ma.order : 1e6, ob = mb ? mb.order : 1e6;
      return (oa - ob) || a.localeCompare(b, 'zh-Hans-CN');
    });
    for (const k of keys) {
      const list = groups.get(k);
      const depth = k ? ((meta.get(k) || {}).depth || 0) : 0;
      const videos = list.filter((i) => i.hasVideo).length;
      const head = document.createElement('div');
      head.className = 'group-head' + (k ? '' : ' plain');
      head.innerHTML = `
        <span class="gh-name" style="padding-left:${depth * 18}px">
          ${k ? ic('folder') : ''}${escapeHtml(k || '未分类（不属于任何 WE 文件夹）')}
        </span>
        <span class="gh-count">${fmtNum(list.length)} 个 · 视频 ${fmtNum(videos)} 个</span>`;
      frag.appendChild(head);
      for (const it of list) frag.appendChild(renderCard(it, posOf.get(it.key)));
    }
  } else {
    app.filtered.forEach((it, idx) => frag.appendChild(renderCard(it, idx)));
  }

  el.grid.innerHTML = '';
  el.grid.appendChild(frag);
}

function renderCard(it, idx) {
  const card = document.createElement('div');
  card.className = 'card';
  card.dataset.key = it.key;
  card.dataset.index = idx;

  const fav = !!app.state.favorites[it.key];
  const pos = app.state.positions[it.key] || 0;
  const dur = it.duration || 0;
  const pct = dur > 0 && pos > 0 ? Math.min(100, (pos / dur) * 100) : 0;
  const watched = !!app.state.watched[it.key];

  const badges = [];
  badges.push(`<span class="badge ${it.type}">${escapeHtml(typeLabel(it.type))}</span>`);
  if (!it.browserPlayable && it.hasVideo) badges.push(`<span class="badge">${escapeHtml(it.videoExt.replace('.', '').toUpperCase())}</span>`);

  const cornerBadge = it.durationText
    ? `<span class="badge badge-corner">${it.durationText}</span>`
    : (it.resolutionText ? `<span class="badge badge-corner">${it.resolutionText}</span>` : '');

  // 视频壁纸给播放圆钮；场景/网页壁纸只展示官方预览动画，不给播放图标
  const hoverLayer = it.hasVideo
    ? `<div class="play-overlay"><div class="circle">${ic('play')}</div></div>`
    : `<div class="preview-overlay"><span>${ic('film')}预览</span></div>`;

  card.innerHTML = `
    <div class="thumb">
      <div class="placeholder">${ic('film')}</div>
      <img data-src="${it.previewUrl || ''}" alt="">
      <div class="badge-row">${badges.join('')}</div>
      ${cornerBadge}
      <button class="card-fav ${fav ? 'on' : ''}" title="收藏">${ic(fav ? 'heart-fill' : 'heart')}</button>
      ${hoverLayer}
    </div>
    <div class="card-body">
      <div class="card-title" title="${escapeHtml(it.title)}">${escapeHtml(it.title)}</div>
      <div class="card-meta">
        ${it.resolutionText ? `<span>${it.resolutionText}</span>` : ''}
        <span>${escapeHtml(it.sizeText)}</span>
        ${it.weFolder ? `<span class="folder-tag" title="WE 文件夹：${escapeHtml(it.weFolder)}">${ic('folder')}<span class="ft-name">${escapeHtml(it.weFolderName)}</span></span>` : ''}
        ${watched ? '<span class="watched-tag">已看</span>' : ''}
      </div>
      ${pct > 0 ? `<div class="progress-line"><i style="width:${pct.toFixed(1)}%"></i></div>` : ''}
    </div>`;

  const img = card.querySelector('img');
  if (img.dataset.src) {
    // 图片就绪后移除占位图标，避免它压在预览图上面
    img.addEventListener('load', () => {
      const ph = card.querySelector('.placeholder');
      if (ph) ph.remove();
    }, { once: true });
    // 预览缺失/损坏时也要有明确回退：直接摘掉 img，让占位图接管
    img.addEventListener('error', () => {
      img.removeAttribute('src');
      img.classList.add('broken');
    }, { once: true });
    thumbObserver.observe(img);
  } else {
    img.remove();
  }

  card.querySelector('.card-fav').addEventListener('click', (e) => { e.stopPropagation(); toggleFav(it.key, true); });

  card.addEventListener('click', () => openPlayer(idx));
  card.addEventListener('contextmenu', (e) => { e.preventDefault(); showContextMenu(e.clientX, e.clientY, it); });
  return card;
}

function refreshCardFlags(key) {
  const card = el.grid.querySelector(`.card[data-key="${key}"]`);
  if (!card) return;
  const fav = !!app.state.favorites[key];
  const btn = card.querySelector('.card-fav');
  btn.classList.toggle('on', fav);
  btn.innerHTML = ic(fav ? 'heart-fill' : 'heart');
}

function toggleFav(key, rebuild) {
  const next = !app.state.favorites[key];
  if (next) patch('favorites', key, 1); else patch('favorites', key, null);
  if (!next) delete app.state.favorites[key];
  refreshCardFlags(key);
  if (app.index >= 0 && app.filtered[app.index] && app.filtered[app.index].key === key) updateFavButton();
  if (rebuild && (app.filters.onlyFav)) { buildFilters(); applyFilters(); }
  else { buildFilters(); updateCount(); }
  toast(next ? '已加入收藏' : '已取消收藏', 1200);
}

/* ---------------------------------------------------------- 右键菜单 */
function showContextMenu(x, y, it) {
  const fav = !!app.state.favorites[it.key];
  const menu = el.ctxMenu;
  menu.innerHTML = `
    <button data-act="play">${ic('play')} 播放</button>
    ${it.hasVideo ? `<button data-act="external">${ic('external')} 用系统默认播放器打开</button>` : ''}
    <button data-act="fav">${ic(fav ? 'heart-fill' : 'heart')} ${fav ? '取消收藏' : '加入收藏'}</button>
    <button data-act="watched">${ic('stop')} ${app.state.watched[it.key] ? '标记为未看' : '标记为已看'}</button>
    <div class="sep"></div>
    <button data-act="reveal">${ic('folder')} 在资源管理器中显示</button>
    <button data-act="copypath">${ic('list')} 复制文件路径</button>
    <button data-act="copytitle">${ic('list')} 复制标题</button>
    ${it.workshopUrl ? `<button data-act="workshop">${ic('external')} 打开创意工坊页面</button>` : ''}
    <div class="sep"></div>
    <button data-act="copyinfo">${ic('film')} 复制壁纸信息</button>`;

  menu.classList.remove('hidden');
  // 每次显示都重放「从触发点长出来」的动画
  menu.style.animation = 'none';
  void menu.offsetWidth;
  menu.style.animation = '';
  const rect = menu.getBoundingClientRect();
  const left = Math.min(x, window.innerWidth - rect.width - 8);
  const top = Math.min(y, window.innerHeight - rect.height - 8);
  menu.style.left = left + 'px';
  menu.style.top = top + 'px';
  // 空间一致性：菜单从鼠标按下的那一点展开，而不是从自己中心
  menu.style.setProperty('--menu-ox', Math.round(x - left) + 'px');
  menu.style.setProperty('--menu-oy', Math.round(y - top) + 'px');

  menu.onclick = async (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;
    const act = btn.dataset.act;
    hideContextMenu();
    if (act === 'play') { const idx = app.filtered.findIndex((i) => i.key === it.key); openPlayer(idx >= 0 ? idx : 0); }
    if (act === 'external') await openExternal(it.key);
    if (act === 'fav') toggleFav(it.key, true);
    if (act === 'watched') { toggleWatched(it.key); applyFilters(); }
    if (act === 'reveal') await revealInExplorer(it.key);
    if (act === 'workshop') window.open(it.workshopUrl, '_blank');
    if (act === 'copypath') { const p = await filePath(it.key); copyText(p || it.folder, '文件路径已复制'); }
    if (act === 'copytitle') copyText(it.title, '标题已复制');
    if (act === 'copyinfo') copyText(wallpaperInfoText(it), '壁纸信息已复制');
  };
}

function hideContextMenu() { el.ctxMenu.classList.add('hidden'); }
document.addEventListener('click', (e) => { if (!el.ctxMenu.contains(e.target)) hideContextMenu(); });
document.addEventListener('contextmenu', (e) => { if (!e.target.closest('.card')) hideContextMenu(); });
window.addEventListener('blur', hideContextMenu);

function wallpaperInfoText(it) {
  return [
    `标题：${it.title}`,
    `类型：${it.typeLabel}`,
    `来源：${it.sourceLabel}`,
    it.weFolder ? `WE 文件夹：${it.weFolder}` : 'WE 文件夹：（未分类）',
    it.id ? `ID：${it.id}` : '',
    it.resolutionText ? `分辨率：${it.resolutionText}` : '',
    it.durationText ? `时长：${it.durationText}` : '',
    `体积：${it.sizeText}`,
    it.subscribedAt ? `订阅时间：${new Date(it.subscribedAt * 1000).toLocaleString()}` : '',
    it.tags.length ? `标签：${it.tags.join('、')}` : '',
    `目录：${it.folder}`,
  ].filter(Boolean).join('\n');
}

async function copyText(text, msg) {
  try {
    await navigator.clipboard.writeText(text);
    toast(msg || '已复制');
  } catch (err) {
    toast('复制失败：' + err.message);
  }
}

async function filePath(key) {
  try { const r = await api('/file/' + encodeURIComponent(key)); return r.path; } catch (e) { return null; }
}
async function revealInExplorer(key) {
  const r = await api('/api/reveal', { key });
  toast(r.ok ? '已在资源管理器中打开' : '打开失败');
}
async function openExternal(key) {
  const r = await api('/api/open_external', { key });
  if (!r.ok) toast('调用系统播放器失败');
}

function toggleWatched(key) {
  if (app.state.watched[key]) { patch('watched', key, null); delete app.state.watched[key]; toast('已标记为未看', 1100); }
  else { patch('watched', key, 1); app.state.watched[key] = 1; toast('已标记为已看', 1100); }
}

/* ---------------------------------------------------------- 效果窗口
   场景 / 网页壁纸由 Wallpaper Engine 渲染到一个独立窗口，我们把它贴在
   舞台区域上（后端 SetWindowPos），播放器失焦时自动隐藏。 */
const effect = { open: false, key: null, poll: null, sync: null };

function stageRect() {
  const s = el.stage.getBoundingClientRect();
  const topBar = el.stageTop ? el.stageTop.getBoundingClientRect() : null;
  const row = document.querySelector('#controls .buttons-row');
  const bottomEdge = row ? row.getBoundingClientRect().top : s.bottom;
  const insetTop = topBar ? Math.max(0, topBar.bottom - s.top + 8) : 0;
  const height = Math.max(140, bottomEdge - s.top - insetTop - 8);
  return {
    left: s.left, top: s.top + insetTop, width: s.width, height,
    screenX: window.screenX || 0, screenY: window.screenY || 0,
    dpr: window.devicePixelRatio || 1,
  };
}

function setEffectUI(on, note) {
  effect.open = !!on;
  el.player.classList.toggle('effect-mode', !!on);
  el.effectStatus.classList.toggle('hidden', !on);
  el.btnEffectRaise.classList.toggle('hidden', !on);
  el.btnEffectClose.classList.toggle('hidden', !on);
  if (note) el.effectStatusText.textContent = note;
}

async function openEffectWindow(it) {
  if (app.state.settings && app.state.settings.useEffectWindow === false) return { ok: false, error: '已设置为只用预览图' };
  try {
    const res = await api('/api/effect/open', { key: it.key, rect: stageRect(), dpr: window.devicePixelRatio || 1 });
    setEffectUI(!!res.ok);
    if (res.ok) {
      clearInterval(effect.poll);
      effect.lastSig = null;
      effect.poll = setInterval(() => syncEffect(true), 1500);   // 窗口被拖动/缩放时也能跟上
      effect.key = it.key;
    }
    return res;
  } catch (err) {
    setEffectUI(false);
    return { ok: false, error: err.message };
  }
}

function syncEffect(force) {
  if (!effect.open && !effect.key) return;
  const rect = stageRect();
  const sig = JSON.stringify(rect);
  if (!force && sig === effect.lastSig) return;      // 没变化就不折腾窗口
  effect.lastSig = sig;
  // 显不显示由后端按「真实前台窗口」判断：点画面不会让它消失，切到别的程序会自动收起
  api('/api/effect/update', {
    rect, dpr: window.devicePixelRatio || 1,
    focused: document.hasFocus(),
  }).catch(() => { });
}

async function closeEffectWindow() {
  clearInterval(effect.poll);
  effect.poll = null;
  const had = effect.open || effect.key;
  setEffectUI(false);
  effect.key = null;
  if (!had) return;
  try { await api('/api/effect/close', {}); } catch (e) { }
}

window.addEventListener('resize', () => {
  clearTimeout(effect.sync);
  effect.sync = setTimeout(() => syncEffect(false), 180);
});
document.addEventListener('fullscreenchange', () => setTimeout(() => syncEffect(true), 350));
window.addEventListener('focus', () => { effect.lastSig = null; syncEffect(true); });
window.addEventListener('blur', () => { effect.lastSig = null; setTimeout(() => syncEffect(true), 260); });

/* ---------------------------------------------------------- 播放器 */
function openPlayer(index) {
  if (index < 0 || index >= app.filtered.length) return;
  app.index = index;
  const it = app.filtered[index];
  el.player.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
  loadMedia(it);
  renderPlaylist();
  showControls();
  try { history.replaceState(null, '', '#play=' + encodeURIComponent(it.key)); } catch (e) { }
}

/* 支持直接打开某个壁纸：index.html#play=<key> */
function openFromHash() {
  const m = /^#play=(.+)$/.exec(location.hash || '');
  if (!m) return false;
  const key = decodeURIComponent(m[1]);
  const idx = app.filtered.findIndex((i) => i.key === key);
  if (idx < 0) return false;
  openPlayer(idx);
  return true;
}

function loadMedia(it) {
  const video = el.video;
  const key = it.key;
  const playable = !!(it.hasVideo && it.browserPlayable);

  // 非视频壁纸 = 预览模式：隐藏播放/进度/音量等无意义的控件
  el.player.classList.toggle('preview-mode', !playable);

  el.playerTitle.textContent = it.title;
  const subParts = [it.typeLabel, it.resolutionText, it.durationText, it.sizeText, it.sourceLabel]
    .filter(Boolean).map(escapeHtml);
  el.playerSub.innerHTML = subParts.join(' · ')
    + (it.weFolder ? ` · <span class="sub-folder">${ic('folder')}${escapeHtml(it.weFolder)}</span>` : '');
  updateFavButton();

  el.fallbackPreview.classList.add('hidden');
  el.stageMessage.classList.add('hidden');
  video.classList.remove('hidden');

  if (it.hasVideo && it.browserPlayable) {
    closeEffectWindow();
    video.src = it.mediaUrl;
    video.load();
    const saved = app.state.positions[key] || 0;
    if (saved > 5) {
      video.addEventListener('loadedmetadata', function once() {
        video.removeEventListener('loadedmetadata', once);
        if (isFinite(video.duration) && saved < video.duration - 8) {
          video.currentTime = saved;
          toast('已从上次位置继续：' + fmtTime(saved), 2000);
        }
      });
    }
    video.play().catch(() => { });
    el.btnExternal.classList.remove('hidden');
  } else {
    video.pause();
    video.removeAttribute('src');
    video.load();
    if (it.previewUrl) {
      el.fallbackPreview.src = it.previewUrl;
      el.fallbackPreview.classList.remove('hidden');
      video.classList.add('hidden');
    }
    el.stageMessage.classList.remove('hidden');
    el.stageMessage.textContent = it.hasVideo
      ? `该壁纸使用 ${it.videoExt.replace('.', '').toUpperCase()} 格式，浏览器无法直接播放，可用「外部播放」打开`
      : `正在让 Wallpaper Engine 渲染${it.typeLabel}的真实效果…`;

    // 交给 Wallpaper Engine 渲染真实效果（窗口会被贴到画面区域上）
    openEffectWindow(it).then((res) => {
      if (currentItem() !== it) return;
      if (!res.ok) {
        el.stageMessage.textContent = it.hasVideo
          ? `该壁纸使用 ${it.videoExt.replace('.', '').toUpperCase()} 格式，可用「外部播放」打开`
          : `这是${it.typeLabel}，未能调用 Wallpaper Engine（${res.error || '未知原因'}），这里显示官方预览动画`;
        return;
      }
      el.stageMessage.classList.add('hidden');
    });
    el.btnExternal.classList.toggle('hidden', !it.hasVideo);
  }
  document.title = it.title + ' — WE 壁纸播放器';
}

function closePlayer() {
  const it = currentItem();
  savePosition(true);
  closeEffectWindow();
  el.video.pause();
  el.video.removeAttribute('src');
  el.video.load();
  el.player.classList.add('hidden');
  el.player.classList.remove('idle');
  el.player.classList.remove('preview-mode');
  document.body.style.overflow = '';
  document.title = 'WE 壁纸播放器';
  app.index = -1;
  try { history.replaceState(null, '', location.pathname); } catch (e) { }
  if (it) refreshCardProgress(it.key);   // 只更新这一张卡，保留滚动位置
  else applyFilters();
}

/* 播放结束后只刷新单张卡片（进度条 / 已看标记），避免整表重绘导致滚动位置丢失 */
function refreshCardProgress(key) {
  const it = app.items.find((i) => i.key === key);
  const card = el.grid.querySelector(`.card[data-key="${key}"]`);
  if (!it || !card) return;
  const pos = app.state.positions[key] || 0;
  const dur = it.duration || 0;
  const pct = dur > 0 && pos > 0 ? Math.min(100, (pos / dur) * 100) : 0;
  const body = card.querySelector('.card-body');
  let line = card.querySelector('.progress-line');
  if (pct > 1) {
    if (!line) {
      line = document.createElement('div');
      line.className = 'progress-line';
      line.innerHTML = '<i></i>';
      body.appendChild(line);
    }
    line.querySelector('i').style.width = pct.toFixed(1) + '%';
  } else if (line) {
    line.remove();
  }
  const meta = card.querySelector('.card-meta');
  if (meta && app.state.watched[key] && !meta.querySelector('.watched-tag')) {
    meta.insertAdjacentHTML('beforeend', '<span class="dot"></span><span class="watched-tag">已看</span>');
  }
}

function updateFavButton() {
  const it = app.filtered[app.index];
  if (!it) return;
  const fav = !!app.state.favorites[it.key];
  el.btnFav.innerHTML = ic(fav ? 'heart-fill' : 'heart');
  el.btnFav.style.color = fav ? 'var(--danger)' : '';
}

function currentItem() { return app.filtered[app.index] || null; }

function savePosition(force) {
  const it = currentItem();
  if (!it || !it.hasVideo) return;
  const v = el.video;
  if (!isFinite(v.currentTime) || v.currentTime < 3) return;
  const key = it.key;
  const prev = app.state.positions[key] || 0;
  if (!force && Math.abs(v.currentTime - prev) < 3) return;
  patch('positions', key, Math.round(v.currentTime));
  if (isFinite(v.duration) && v.duration > 0 && v.currentTime / v.duration > 0.92 && !app.state.watched[key]) {
    app.state.watched[key] = 1;
    patch('watched', key, 1);
  }
}

el.video.addEventListener('timeupdate', () => {
  const v = el.video;
  if (isFinite(v.duration) && v.duration > 0) {
    el.barPlayed.style.width = ((v.currentTime / v.duration) * 100).toFixed(3) + '%';
    el.timeCur.textContent = fmtTime(v.currentTime);
    el.timeDur.textContent = fmtTime(v.duration);
  }
  savePosition(false);
});
el.video.addEventListener('progress', () => {
  const v = el.video;
  if (v.buffered.length && isFinite(v.duration) && v.duration > 0) {
    el.barBuffer.style.width = ((v.buffered.end(v.buffered.length - 1) / v.duration) * 100).toFixed(2) + '%';
  }
});
el.video.addEventListener('loadedmetadata', () => {
  const it = currentItem();
  el.timeDur.textContent = fmtTime(el.video.duration);
  if (it && isFinite(el.video.duration) && el.video.duration > 0) {
    if (!it.duration) {
      it.duration = el.video.duration;
      it.durationText = fmtTime(el.video.duration);
      api('/api/duration', { key: it.key, seconds: el.video.duration }).catch(() => { });
    }
    if (isFinite(el.video.videoWidth) && !it.resolutionText && el.video.videoWidth) {
      it.resolutionText = `${el.video.videoWidth} × ${el.video.videoHeight}`;
    }
  }
});
el.video.addEventListener('play', () => { syncPlayIcons(true); markPlayingCard(); scheduleIdle(); });
el.video.addEventListener('playing', () => { syncPlayIcons(true); });
el.video.addEventListener('pause', () => { syncPlayIcons(false); showControls(); });
el.video.addEventListener('waiting', () => { el.btnPlay.innerHTML = '⋯'; });
el.video.addEventListener('ended', () => {
  savePosition(true);
  const it = currentItem();
  if (it) { patch('watched', it.key, 1); app.state.watched[it.key] = 1; }
  if (app.loop) { el.video.currentTime = 0; el.video.play().catch(() => { }); return; }
  if (app.autonext) next(); else syncPlayIcons(false);
});

function syncPlayIcons(playing) {
  const markup = ic(playing ? 'pause' : 'play');
  el.btnPlay.innerHTML = markup;
  el.bigPlay.innerHTML = markup;
  el.btnPlay.classList.toggle('primary', !playing);
}

function markPlayingCard() {
  const it = currentItem();
  $$('.card.playing').forEach((c) => c.classList.remove('playing'));
  if (!it) return;
  const card = el.grid.querySelector(`.card[data-key="${it.key}"]`);
  if (card) card.classList.add('playing');
}

/* -------- 播放控制 -------- */
function togglePlay() {
  if (el.video.classList.contains('hidden')) return;
  if (el.video.paused) el.video.play().catch(() => { }); else el.video.pause();
}

function next() {
  if (!app.filtered.length) return;
  let idx;
  if (app.shuffle) idx = Math.floor(Math.random() * app.filtered.length);
  else idx = (app.index + 1) % app.filtered.length;
  openPlayer(idx);
  flash('下一个');
}

function prev() {
  if (!app.filtered.length) return;
  if (el.video.currentTime > 5 && !el.video.classList.contains('hidden')) { el.video.currentTime = 0; return; }
  const idx = app.shuffle ? Math.floor(Math.random() * app.filtered.length) : (app.index - 1 + app.filtered.length) % app.filtered.length;
  openPlayer(idx);
  flash('上一个');
}

function seekBy(delta) {
  if (!isFinite(el.video.duration)) return;
  // 不弹「+5s」这类浮层：进度条和时间本身已经在反馈，浮层只会挡住画面
  el.video.currentTime = Math.max(0, Math.min(el.video.duration, el.video.currentTime + delta));
}

function setVolume(v) {
  el.video.volume = Math.max(0, Math.min(1, v));
  el.volume.value = el.video.volume;
  el.btnMute.innerHTML = ic((el.video.volume === 0 || el.video.muted) ? 'mute' : 'volume');
  patch('settings', 'volume', el.video.volume);
}

el.btnPlay.addEventListener('click', togglePlay);
el.bigPlay.addEventListener('click', togglePlay);
el.btnNext.addEventListener('click', next);
el.bigNext.addEventListener('click', next);
el.btnPrev.addEventListener('click', prev);
el.bigPrev.addEventListener('click', prev);
el.btnBack.addEventListener('click', closePlayer);

el.video.addEventListener('click', (e) => {
  if (e.detail > 1) return;
  togglePlay();
});
el.video.addEventListener('dblclick', toggleFullscreen);
el.fallbackPreview.addEventListener('click', toggleFullscreen);

el.volume.addEventListener('input', () => setVolume(parseFloat(el.volume.value)));
el.btnMute.addEventListener('click', () => { el.video.muted = !el.video.muted; setVolume(el.video.volume); });
el.speed.addEventListener('change', () => { el.video.playbackRate = parseFloat(el.speed.value); flash(el.speed.value + '×'); });

el.btnLoop.addEventListener('click', () => { app.loop = !app.loop; el.btnLoop.classList.toggle('active', app.loop); flash(app.loop ? '单个循环开' : '单个循环关'); });
el.btnShuffle.addEventListener('click', () => { app.shuffle = !app.shuffle; el.btnShuffle.classList.toggle('active', app.shuffle); flash(app.shuffle ? '随机播放开' : '随机播放关'); });
el.btnAutonext.addEventListener('click', () => {
  app.autonext = !app.autonext;
  el.btnAutonext.classList.toggle('active', app.autonext);
  patch('settings', 'autonext', app.autonext);
  flash(app.autonext ? '自动连播开' : '自动连播关');
});
el.btnPlaylist.addEventListener('click', () => {
  const open = !el.player.classList.contains('playlist-open');
  el.player.classList.toggle('playlist-open', open);
  el.btnPlaylist.classList.toggle('active', open);
});
el.btnEffectRaise.addEventListener('click', () => { syncEffect(true); toast('已把效果窗口贴回画面', 1300); });
el.btnEffectClose.addEventListener('click', async () => {
  await closeEffectWindow();
  const it = currentItem();
  if (it) {
    if (it.previewUrl) { el.fallbackPreview.src = it.previewUrl; el.fallbackPreview.classList.remove('hidden'); el.video.classList.add('hidden'); }
    el.stageMessage.classList.remove('hidden');
    el.stageMessage.textContent = `这是${it.typeLabel}，已关闭效果窗口，这里显示官方预览动画`;
  }
  toast('已关闭效果窗口', 1400);
});
el.btnFav.addEventListener('click', () => { const it = currentItem(); if (it) toggleFav(it.key, false); });
el.btnReveal.addEventListener('click', () => { const it = currentItem(); if (it) revealInExplorer(it.key); });
el.btnExternal.addEventListener('click', () => { const it = currentItem(); if (it) openExternal(it.key); });
el.btnPip.addEventListener('click', async () => {
  try {
    if (document.pictureInPictureElement) await document.exitPictureInPicture();
    else await el.video.requestPictureInPicture();
  } catch (e) { toast('当前环境不支持画中画'); }
});

async function toggleFullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    // 对整个播放器请求全屏：这样播放列表面板也进全屏（只全屏 stage 会把它挡在外面）
    else await el.player.requestFullscreen();
  } catch (e) { toast('无法进入全屏：' + e.message); }
}
el.btnFullscreen.addEventListener('click', toggleFullscreen);

function syncToggles() {
  el.btnAutonext.classList.toggle('active', app.autonext);
  el.btnLoop.classList.toggle('active', app.loop);
  el.btnShuffle.classList.toggle('active', app.shuffle);
  const speed = (app.state.settings || {}).speed;
  if (speed) { el.speed.value = String(speed); el.video.playbackRate = parseFloat(speed); }
}

/* -------- 进度条：按下即反馈，拖拽 1:1 跟手（pointer capture），松手才落盘 -------- */
function seekToClientX(clientX) {
  const rect = el.bar.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
  if (isFinite(el.video.duration)) {
    el.video.currentTime = ratio * el.video.duration;
    el.barPlayed.style.width = (ratio * 100).toFixed(2) + '%';
    el.timeCur.textContent = fmtTime(el.video.currentTime);
    el.bar.setAttribute('aria-valuenow', Math.round(ratio * 100));
  }
}
let dragging = false;
el.bar.addEventListener('pointerdown', (e) => {
  if (el.video.classList.contains('hidden') || !isFinite(el.video.duration)) return;
  dragging = true;
  el.bar.classList.add('dragging');
  try { el.bar.setPointerCapture(e.pointerId); } catch (err) { }
  seekToClientX(e.clientX);
  e.preventDefault();
});
el.bar.addEventListener('pointermove', (e) => { if (dragging) seekToClientX(e.clientX); });
function endDrag(e) {
  if (!dragging) return;
  dragging = false;
  el.bar.classList.remove('dragging');
  try { el.bar.releasePointerCapture(e.pointerId); } catch (err) { }
  savePosition(true);
}
el.bar.addEventListener('pointerup', endDrag);
el.bar.addEventListener('pointercancel', endDrag);

/* -------- 播放列表 -------- */
function renderPlaylist() {
  const list = app.filtered;
  el.plCount.textContent = `${fmtNum(list.length)} 个`;
  el.plCountBadge.textContent = fmtNum(list.length);
  const frag = document.createDocumentFragment();
  list.forEach((it, idx) => {
    const row = document.createElement('div');
    row.className = 'pl-item' + (idx === app.index ? ' active' : '');
    row.innerHTML = `
      <img src="${it.previewUrl || ''}" alt="" loading="lazy">
      <div class="info">
        <div class="t">${escapeHtml(it.title)}</div>
        <div class="m">${[it.durationText, it.resolutionText, it.typeLabel].filter(Boolean).join(' · ')}</div>
      </div>`;
    row.addEventListener('click', () => openPlayer(idx));
    frag.appendChild(row);
  });
  el.plList.innerHTML = '';
  el.plList.appendChild(frag);
}

/* -------- 鼠标空闲隐藏控制层 -------- */
function showControls() {
  el.player.classList.remove('idle');
  scheduleIdle();
}
function scheduleIdle() {
  clearTimeout(app.idleTimer);
  if (el.video.paused || el.player.classList.contains('hidden')) return;
  app.idleTimer = setTimeout(() => el.player.classList.add('idle'), 3200);
}
el.stage.addEventListener('mousemove', showControls);
el.stage.addEventListener('mouseleave', () => { clearTimeout(app.idleTimer); });

/* ---------------------------------------------------------- 快捷键 */
document.addEventListener('keydown', (e) => {
  const tag = (e.target.tagName || '').toLowerCase();
  const typing = tag === 'input' || tag === 'select' || tag === 'textarea';

  if (e.key === 'Escape') {
    if (!el.modal.classList.contains('hidden')) { el.modal.classList.add('hidden'); return; }
    if (!el.ctxMenu.classList.contains('hidden')) { hideContextMenu(); return; }
    if (document.fullscreenElement) return;   // 交给浏览器退出全屏
    if (!el.player.classList.contains('hidden')) closePlayer();
    return;
  }
  if (typing) return;
  if (!el.modal.classList.contains('hidden')) return;

  const inPlayer = !el.player.classList.contains('hidden');
  const isPreview = el.player.classList.contains('preview-mode');
  const k = e.key.toLowerCase();

  if (inPlayer) showControls();

  if (k === '/' ) { e.preventDefault(); el.search.focus(); el.search.select(); return; }
  if (k === '?' || (e.shiftKey && k === '/')) { toggleHelp(); return; }

  if (!inPlayer) {
    if (k === 'enter' && app.filtered.length) openPlayer(0);
    return;
  }

  switch (k) {
    case ' ': case 'k': e.preventDefault(); if (!isPreview) togglePlay(); break;
    case 'arrowright': e.preventDefault(); if (!isPreview) seekBy(e.shiftKey ? 60 : 5); break;
    case 'arrowleft': e.preventDefault(); if (!isPreview) seekBy(e.shiftKey ? -60 : -5); break;
    case 'l': e.preventDefault(); if (!isPreview) seekBy(10); break;
    case 'j': e.preventDefault(); if (!isPreview) seekBy(-10); break;
    case 'arrowup': e.preventDefault(); if (!isPreview) { setVolume(el.video.volume + 0.05); flash('音量 ' + Math.round(el.video.volume * 100) + '%'); } break;
    case 'arrowdown': e.preventDefault(); if (!isPreview) { setVolume(el.video.volume - 0.05); flash('音量 ' + Math.round(el.video.volume * 100) + '%'); } break;
    case 'n': next(); break;
    case 'b': prev(); break;
    case 'm': if (!isPreview) { el.btnMute.click(); flash(el.video.muted ? '静音' : '取消静音'); } break;
    case 'f': toggleFullscreen(); break;
    case 'p': if (!isPreview) el.btnPip.click(); break;
    case 's': el.btnShuffle.click(); break;
    case 'r': if (!isPreview) el.btnLoop.click(); break;
    case 'c': { const it = currentItem(); if (it) toggleFav(it.key, false); break; }
    case 'o': { const it = currentItem(); if (it) revealInExplorer(it.key); break; }
    case 'e': { const it = currentItem(); if (it) openExternal(it.key); break; }
    case 't': el.btnPlaylist.click(); break;
    case '0': if (!isPreview) el.video.currentTime = 0; break;
    case '1': case '2': case '3': case '4': case '5': case '6': case '7': case '8': case '9': {
      if (!isPreview && isFinite(el.video.duration)) {
        el.video.currentTime = el.video.duration * (parseInt(k, 10) / 10);
      }
      break;
    }
    default: break;
  }
});

/* ---------------------------------------------------------- 帮助 / 信息 */
function toggleHelp(showInfo) {
  if (!el.modal.classList.contains('hidden') && !showInfo) { el.modal.classList.add('hidden'); return; }
  el.modalTitle.textContent = showInfo ? '扫描信息' : '快捷键';
  el.modalBody.innerHTML = showInfo ? infoHtml() : helpHtml();
  el.modal.classList.remove('hidden');
}

function helpHtml() {
  const keys = [
    ['空格 / K', '播放 / 暂停'], ['← →', '快退 / 快进 5 秒'], ['Shift + ← →', '快退 / 快进 60 秒'],
    ['J / L', '快退 / 快进 10 秒'], ['↑ ↓', '音量'], ['M', '静音'],
    ['N / B', '下一个 / 上一个'], ['F', '全屏'], ['P', '画中画'],
    ['S', '随机播放'], ['R', '单个循环'], ['C', '收藏当前'],
    ['O', '在资源管理器中显示'], ['E', '用系统播放器打开'], ['T', '播放列表'],
    ['0 - 9', '跳到 0% ~ 90%'], ['/ ', '搜索'], ['Esc', '退出播放器 / 关闭弹窗'],
  ];
  return `<h3>播放器</h3><div class="keys">${keys.map(([k, v]) => `<div><span>${v}</span><b>${escapeHtml(k)}</b></div>`).join('')}</div>
  <h3>配色</h3>
  <div>终末地官方两套配色：谷地黄是 ECP 用的那套，武陵青是站点设置里的第二套。</div>
  <div class="palette-row">
    <button class="palette-swatch${app.palette === 'valley' ? ' active' : ''}" data-palette="valley"><i style="background:#c6ca4c"></i>谷地黄</button>
    <button class="palette-swatch${app.palette === 'wuling' ? ' active' : ''}" data-palette="wuling"><i style="background:#14d0d0"></i>武陵青</button>
  </div>
  <h3>非视频壁纸怎么显示</h3>
  <div>场景 / 网页壁纸是 Wallpaper Engine 自己的格式，这里调用 WE 的命令行把壁纸渲染到一个
  无边框窗口，再精确贴到播放器的画面区域上，看起来就像内嵌播放；播放器失焦时窗口会自动隐藏。</div>
  <div style="margin-top:8px">
    <button class="pill" id="btnPrefEffect">${
      (app.state.settings && app.state.settings.useEffectWindow === false)
        ? '当前：显示官方预览动画 → 点此改回真实效果' : '当前：Wallpaper Engine 真实效果 → 点此改成只用预览动画'
    }</button>
  </div>
  <h3>文件夹与排序</h3>
  <div>· 左侧「文件夹」直接读 Wallpaper Engine 的文件夹结构，点父文件夹会连同子文件夹一起筛选。</div>
  <div>· 工具条的「分组」按钮 = 按 WE 文件夹分段平铺显示；关掉就是普通网格。</div>
  <div>· 排序默认「订阅时间」，即壁纸下载到本机的时间，和 WE 的「订阅日期」一致。</div>
  <h3>小技巧</h3>
  <div>· 双击画面即可全屏；单击画面暂停/继续。鼠标不动 3 秒会自动隐藏控制栏。</div>
  <div>· 每部壁纸的播放进度会自动记住，下次点开接着看。</div>
  <div>· 在卡片上点右键，可以「用系统播放器打开」「在资源管理器中显示」「复制路径」。</div>
  <div>· 左侧可以按类型 / 来源 / 收藏 / 已看 过滤，顶部搜索支持标题、标签和创意工坊 ID。</div>`;
}

function infoHtml() {
  const s = app.stats || {};
  const libs = (s.libraries || []).map((p) => `<div class="mono">${escapeHtml(p)}</div>`).join('') || '<div class="mono">（未发现）</div>';
  const ws = (s.workshopDirs || []).map((p) => `<div class="mono">${escapeHtml(p)}</div>`).join('') || '<div class="mono">（未发现）</div>';
  const my = (s.myProjectDirs || []).map((p) => `<div class="mono">${escapeHtml(p)}</div>`).join('') || '<div class="mono">（未发现）</div>';
  const errs = (s.errors || []).length ? `<h3>扫描告警</h3><div>${(s.errors || []).map(escapeHtml).join('<br>')}</div>` : '';
  const folders = (s.weFolders || []).map((f) => {
    const title = f.path.split(' / ').pop();
    return `<div class="mono" style="padding-left:${f.depth * 14}px">${f.depth ? '└ ' : ''}${escapeHtml(title)} · ${f.count} 个</div>`;
  }).join('') || '<div class="mono">（没有检测到 WE 文件夹）</div>';
  return `<h3>统计</h3>
  <div class="kv">
    <div class="k">壁纸总数</div><div>${app.items.length}</div>
    <div class="k">可播放视频</div><div>${app.items.filter((i) => i.hasVideo).length}</div>
    <div class="k">浏览器可播</div><div>${app.items.filter((i) => i.browserPlayable).length}</div>
    <div class="k">未分类</div><div>${s.unclassified || 0}</div>
    <div class="k">扫描耗时</div><div>${s.seconds || 0} 秒</div>
  </div>
  <h3>Wallpaper Engine 文件夹</h3>${folders}
  <div class="mono" style="margin-top:6px">来源配置：${escapeHtml(s.weConfig || '未找到 config.json')}</div>
  <h3>Steam 库</h3>${libs}
  <h3>创意工坊目录（AppID 431960）</h3>${ws}
  <h3>Wallpaper Engine「我的壁纸」</h3>${my}
  ${errs}
  <h3>收录更多目录</h3>
  <div>如果壁纸在其它位置，把它们写进 <span class="mono">data\\config.json</span>，例如：</div>
  <div class="mono" style="margin-top:8px">{ "extra_libraries": ["E:\\\\SteamLibrary"], "extra_project_dirs": ["E:\\\\WE\\\\projects"], "we_config": "E:\\\\WE\\\\config.json" }</div>
  <h3>文件夹没有同步？</h3>
  <div>Wallpaper Engine 只在自己保存配置时才把文件夹写进 <span class="mono">config.json</span>。
  刚在 WE 里新建/移动过文件夹的话，<b>先从托盘完全退出一次 WE</b>，再回来点「重新扫描」。</div>`;
}

el.btnHelp.addEventListener('click', () => toggleHelp(false));
el.modalClose.addEventListener('click', () => el.modal.classList.add('hidden'));
el.modal.addEventListener('click', (e) => {
  if (e.target === el.modal) { el.modal.classList.add('hidden'); return; }
  const swatch = e.target.closest('.palette-swatch');
  if (swatch) {
    const name = swatch.dataset.palette;
    setPalette(name, true);
    toast(name === 'wuling' ? '配色：武陵青' : '配色：谷地黄', 1300);
    return;
  }
  const btn = e.target.closest('#btnPrefEffect');
  if (!btn) return;
  const next = !(app.state.settings && app.state.settings.useEffectWindow === false);
  patch('settings', 'useEffectWindow', next);
  app.state.settings = app.state.settings || {};
  app.state.settings.useEffectWindow = next;
  el.modalBody.innerHTML = helpHtml();
  toast(next ? '非视频壁纸：使用 WE 真实效果' : '非视频壁纸：只用预览动画', 1600);
  if (!next) closeEffectWindow();
});

/* ---------------------------------------------------------- 全局按钮 */
el.btnRandom.addEventListener('click', () => {
  if (!app.filtered.length) return;
  openPlayer(Math.floor(Math.random() * app.filtered.length));
});
el.btnPlayAll.addEventListener('click', () => { if (app.filtered.length) openPlayer(0); });
el.btnRescan.addEventListener('click', async () => {
  el.btnRescan.disabled = true;
  await loadLibrary(true);
  el.btnRescan.disabled = false;
  toast('扫描完成，共 ' + app.items.length + ' 个壁纸');
});

/* ---------------------------------------------------------- 启动 */
loadLibrary(false);
measureChrome();
positionSegThumb();
// 字体/布局稳定后再量一次（首帧时工具栏高度可能还没定）
requestAnimationFrame(() => { measureChrome(); positionSegThumb(); });
/* 每 30 秒保存一次进度，防止异常退出丢失 */
setInterval(() => { if (app.index >= 0) savePosition(false); flushPatch(); }, 30000);
window.addEventListener('beforeunload', () => { savePosition(true); flushPatch(); });
