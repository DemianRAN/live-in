#!/usr/bin/env python3
"""data/events.json + collector/venues.json から web/index.html を生成する。

生成物は単体 HTML（データを script タグに内包）なので、
そのままブラウザで開いても、GitHub Pages に置いても動く。
生成時点で「本日（JST）以降」の公演に絞り、閲覧時にもブラウザ側で
閲覧日（JST）以降に絞り直す（生成から日付が変わっても過去公演を出さない）。
日付昇順。
使い方: python3 collector/build.py
"""

import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>関東ライブまとめ | ライブハウス公演スケジュール</title>
<meta name="description" content="__DESC__">
<meta property="og:type" content="website">
<meta property="og:title" content="関東ライブまとめ">
<meta property="og:description" content="__DESC__">
<meta property="og:url" content="https://demianran.github.io/live-in/">
<meta name="twitter:card" content="summary">
<meta name="theme-color" content="#241b4d">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🎤</text></svg>">
<style>
  :root {
    color-scheme: light dark;
    --bg:#f8f7fc; --surface:#fff; --ink:#23202b; --muted:#6b6577; --line:#e3dff0; --chip:#f1eef9;
    --accent:#6a3ec9; --accent-ink:#fff; --venue-bg:#ece7fb; --price:#7a5200; --sat:#2456c8; --sun:#c82a45;
    --gtag-bg:#eef7ee; --gtag-ink:#2e7d32; --gtag-line:#cfe6cf; --warn-bg:#fff4e0; --warn-ink:#7a4b00;
    --shadow:0 8px 24px rgba(36,27,77,.18);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg:#16141c; --surface:#211e2a; --ink:#ece9f3; --muted:#a49eb2; --line:#363145; --chip:#2a2636;
      --accent:#a98bf0; --accent-ink:#16141c; --venue-bg:#2f2846; --price:#e5b665; --sat:#7ea6ff; --sun:#ff7f93;
      --gtag-bg:#1d2b1e; --gtag-ink:#8fd194; --gtag-line:#2f4a31; --warn-bg:#3a2c12; --warn-ink:#f3c97a;
      --shadow:0 8px 24px rgba(0,0,0,.5);
    }
  }
  * { box-sizing: border-box; }
  body { margin:0; font-family:-apple-system,"Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif; color:var(--ink); background:var(--bg); -webkit-text-size-adjust:100%; }
  a { color:inherit; }
  :focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
  header.site { background:linear-gradient(120deg,#241b4d,#6a3ec9); color:#fff; padding:22px 16px 18px; }
  header.site .inner { max-width:920px; margin:0 auto; }
  header.site h1 { margin:0 0 4px; font-size:21px; }
  header.site p { margin:0; opacity:.88; font-size:13px; line-height:1.6; }
  header.site .fresh { margin-top:6px; font-size:12px; opacity:.8; }
  main { max-width:920px; margin:0 auto; padding:0 16px 16px; }

  /* 検索バー（常に上部に固定） */
  .toolbar { position:sticky; top:0; z-index:20; background:var(--bg); padding:10px 0 8px; display:flex; gap:8px; align-items:center; }
  .toolbar input { flex:1; min-width:0; padding:9px 12px; border:1px solid var(--line); border-radius:10px; font-size:16px; background:var(--surface); color:var(--ink); }
  .btn { border:1px solid var(--line); background:var(--surface); color:var(--ink); border-radius:10px; padding:8px 12px; font-size:13.5px; cursor:pointer; white-space:nowrap; }
  .btn.primary { background:var(--accent); color:var(--accent-ink); border-color:var(--accent); }
  .btn.link { border:0; background:none; color:var(--accent); padding:4px 2px; text-decoration:underline; }
  #filterToggle, #panelDone { display:none; }

  /* 絞り込みパネル */
  .panel { padding:2px 0 6px; border-bottom:1px solid var(--line); }
  .row { display:flex; flex-wrap:wrap; gap:6px; margin:6px 0; align-items:center; }
  .row .lbl { font-size:12.5px; color:var(--muted); min-width:3.6em; }
  .chip { border:1px solid var(--line); background:var(--chip); color:var(--ink); border-radius:999px; padding:5px 12px; font-size:13px; cursor:pointer; }
  .chip .c { color:var(--muted); font-size:11.5px; margin-left:3px; }
  .chip[aria-pressed="true"] { background:var(--accent); color:var(--accent-ink); border-color:var(--accent); }
  .chip[aria-pressed="true"] .c { color:inherit; opacity:.8; }
  select { padding:7px 10px; border:1px solid var(--line); border-radius:10px; background:var(--surface); color:var(--ink); font-size:14px; max-width:100%; }
  .check { font-size:13px; color:var(--muted); display:flex; align-items:center; gap:5px; cursor:pointer; }

  .statusline { display:flex; flex-wrap:wrap; gap:6px 12px; align-items:center; color:var(--muted); font-size:13px; margin:10px 0 0; }
  .statusline strong { color:var(--ink); font-size:14px; }
  .statusline .spacer { flex:1; }
  .notice { background:var(--warn-bg); color:var(--warn-ink); border-radius:10px; padding:8px 12px; font-size:13px; margin:10px 0 0; line-height:1.6; }

  /* 日付見出し（検索バーの下に固定） */
  .day-head { position:sticky; top:var(--tb-h,58px); z-index:5; background:var(--bg); font-size:15px; font-weight:700; margin:16px 0 6px; padding:6px 0 4px; border-bottom:2px solid var(--accent); }
  .day-head .rel { display:inline-block; font-size:11.5px; background:var(--accent); color:var(--accent-ink); border-radius:4px; padding:1px 6px; margin-left:6px; vertical-align:2px; }
  .day-head .n { font-weight:400; color:var(--muted); font-size:12.5px; margin-left:6px; }
  .wk-sat { color:var(--sat); } .wk-sun { color:var(--sun); }

  .card { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:12px 14px; margin:8px 0; }
  .card h3 { margin:6px 0 4px; font-size:15.5px; line-height:1.45; overflow-wrap:anywhere; }
  .card h3 a { text-decoration:none; }
  .card h3 a:hover { color:var(--accent); text-decoration:underline; }
  .meta { color:var(--muted); font-size:12.5px; display:flex; flex-wrap:wrap; gap:4px 8px; align-items:center; }
  .venue { font:inherit; font-size:12px; font-weight:600; padding:2px 9px; border-radius:999px; background:var(--venue-bg); color:var(--accent); border:0; cursor:pointer; }
  .artists { font-size:13.5px; line-height:1.6; overflow-wrap:anywhere; }
  .price { font-size:13px; color:var(--price); margin-top:2px; overflow-wrap:anywhere; }
  .badges { margin:2px 0 4px; }
  .badge { display:inline-block; font-size:11px; font-weight:700; padding:2px 8px; border-radius:4px; margin-right:6px; color:#fff; }
  .b-sold_out { background:#c82a45; } .b-cancelled { background:#44404d; } .b-postponed { background:#d9820a; }
  .b-stale { background:#8a8496; font-weight:400; }
  .gtag { display:inline-block; font-size:11px; padding:2px 8px; border-radius:999px; background:var(--gtag-bg); color:var(--gtag-ink); border:1px solid var(--gtag-line); margin-right:4px; }
  .card.is-cancelled { opacity:.6; }
  .actions { margin-top:8px; display:flex; gap:8px; flex-wrap:wrap; }
  .actions a, .actions button { font:inherit; font-size:12.5px; padding:5px 10px; border-radius:8px; border:1px solid var(--line); background:var(--surface); color:var(--accent); cursor:pointer; text-decoration:none; }
  .actions a:hover, .actions button:hover { background:var(--chip); }

  .empty { color:var(--muted); text-align:center; padding:40px 0; line-height:2; }
  #more { display:none; margin:16px auto; }
  #toTop { position:fixed; right:16px; bottom:16px; z-index:30; width:44px; height:44px; border-radius:50%; border:1px solid var(--line); background:var(--surface); color:var(--accent); font-size:18px; box-shadow:var(--shadow); cursor:pointer; display:none; }
  #toTop.show { display:block; }

  details.venues { margin-top:28px; background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:12px 16px; font-size:13.5px; }
  details.venues summary { cursor:pointer; font-weight:700; font-size:14.5px; }
  details.venues ul { margin:8px 0 0; padding-left:20px; }
  details.venues li { margin:5px 0; }
  details.venues .c { color:var(--muted); font-size:12px; }
  footer { color:var(--muted); font-size:12px; text-align:center; padding:24px 16px 72px; line-height:1.8; }

  /* スマホ: 絞り込みはボタンで開くドロップダウンにする */
  @media (max-width: 719px) {
    #filterToggle { display:inline-block; }
    .panel { display:none; }
    .panel.open { display:block; position:fixed; z-index:25; left:0; right:0; top:var(--panel-top,58px); max-height:calc(100vh - var(--panel-top,58px)); overflow:auto; background:var(--bg); padding:4px 16px 14px; box-shadow:var(--shadow); }
    #panelDone { display:block; width:100%; margin-top:10px; }
    .row .lbl { min-width:100%; }
  }
</style>
</head>
<body>
<header class="site">
  <div class="inner">
    <h1>🎤 関東ライブまとめ</h1>
    <p>関東のライブハウス・小ホールの公演情報を、各会場の公式サイトから毎日自動収集。詳細・チケットは公式ページへ。</p>
    <div class="fresh" id="fresh"></div>
  </div>
</header>
<main>
  <div class="toolbar" id="toolbar">
    <input id="kw" type="search" placeholder="出演者・公演名・会場" aria-label="キーワード検索（スペース区切りで AND 検索）" autocomplete="off">
    <button class="btn" id="filterToggle" type="button" aria-expanded="false" aria-controls="panel">絞り込み</button>
  </div>
  <div class="panel" id="panel">
    <div class="row" id="periodRow" role="group" aria-label="期間">
      <span class="lbl">期間</span>
      <button type="button" class="chip" data-v="all">すべて</button>
      <button type="button" class="chip" data-v="today">今日</button>
      <button type="button" class="chip" data-v="tomorrow">明日</button>
      <button type="button" class="chip" data-v="week">今後7日</button>
      <button type="button" class="chip" data-v="weekend">今週末</button>
    </div>
    <div class="row" id="prefRow" role="group" aria-label="都県"><span class="lbl">都県</span></div>
    <div class="row">
      <label class="lbl" for="venueSel">会場</label>
      <select id="venueSel"></select>
    </div>
    <div class="row" id="genreRow" role="group" aria-label="ジャンル"><span class="lbl">ジャンル</span></div>
    <div class="row">
      <span class="lbl">表示</span>
      <label class="check"><input type="checkbox" id="hideBad"> 完売・中止を隠す</label>
    </div>
    <button class="btn primary" id="panelDone" type="button">結果を見る</button>
  </div>
  <div class="statusline">
    <span id="count"></span>
    <button class="btn link" id="resetBtn" type="button" hidden>条件をリセット</button>
    <span class="spacer"></span>
    <button class="btn" id="exportBtn" type="button">📅 表示中を .ics で書き出す</button>
  </div>
  <div id="notice"></div>
  <div id="list" aria-live="polite"></div>
  <button class="btn" id="more" type="button">さらに表示</button>
  <details class="venues">
    <summary id="venueSummary">対象会場</summary>
    <ul id="venueList"></ul>
  </details>
</main>
<footer>
  <div id="updated"></div>
  <div>公演情報は各会場の公式サイトの発表に基づきます。料金・時間は変更される場合があります。必ず公式詳細ページでご確認ください。</div>
</footer>
<button id="toTop" type="button" aria-label="ページの先頭へ">↑</button>
<script id="data" type="application/json">__DATA_JSON__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
// 「今日」は生成時ではなく閲覧時の JST で決める（生成から日付が変わっても正しく絞る）
const todayStr = new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Tokyo' });
const events = DATA.events.filter(e => e.date >= todayStr), venues = DATA.venues;
const venueById = Object.fromEntries(venues.map(v => [v.id, v]));
// 検索は全角/半角・大文字/小文字を区別しない
function norm(s) { return String(s == null ? '' : s).normalize('NFKC').toLowerCase(); }
events.forEach((e, i) => { e._i = i; e._hay = norm([e.title, e.artists, e.venue, e.area, e.pref].join(' ')); });
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
// 収集データ由来の URL は http(s) のみリンクにする
function safeUrl(u) { return /^https?:\/\//i.test(u || '') ? u : ''; }
// 日付演算は UTC で行う（閲覧端末のタイムゾーンや夏時間の影響を受けない）
function ymd(ds) { return ds.split('-').map(Number); }
function addDays(ds, n) { const [y, m, d] = ymd(ds); return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10); }
function dowOf(ds) { const [y, m, d] = ymd(ds); return new Date(Date.UTC(y, m - 1, d)).getUTCDay(); }
const tomorrowStr = addDays(todayStr, 1);
const weekEnd = addDays(todayStr, 6);
const weekendDates = new Set();
for (let i = 0; i < 7; i++) { const ds = addDays(todayStr, i); const dow = dowOf(ds); if (dow === 0 || dow === 6) weekendDates.add(ds); }

const STATUS_LABEL = { sold_out: 'SOLD OUT', cancelled: '公演中止', postponed: '延期' };
const GENRE_ORDER = ['ロック/バンド', 'アコースティック/弾き語り', 'アイドル', 'ヒップホップ', 'ジャズ', 'クラシック', 'DJ/クラブ', 'トーク/お笑い'];
const PREF_ORDER = ['東京都', '神奈川県', '埼玉県', '千葉県', '茨城県', '栃木県', '群馬県'];
const PERIODS = ['all', 'today', 'tomorrow', 'week', 'weekend'];
const PAGE = 120;  // 一度に描画する件数（残りはスクロールで追加）
const prefRank = p => { const i = PREF_ORDER.indexOf(p); return i < 0 ? 99 : i; };
const countBy = key => events.reduce((m, e) => { m[e[key]] = (m[e[key]] || 0) + 1; return m; }, {});
const prefCount = countBy('pref'), venueCount = countBy('venue_id');

const state = { q: '', period: 'all', pref: '', venue: '', genre: '', hide: false };
let filteredNow = [], shown = 0, lastDate = '', dateCount = {};
const $ = id => document.getElementById(id);

// ---- URL と状態の同期（絞り込み条件をそのまま共有・ブックマークできる） ----
function readURL() {
  const p = new URLSearchParams(location.search);
  state.q = p.get('q') || '';
  state.period = PERIODS.includes(p.get('period')) ? p.get('period') : 'all';
  state.pref = prefCount[p.get('pref')] ? p.get('pref') : '';
  state.venue = venueById[p.get('venue')] ? p.get('venue') : '';
  state.genre = GENRE_ORDER.includes(p.get('genre')) ? p.get('genre') : '';
  state.hide = p.get('hide') === '1';
}
function writeURL() {
  const p = new URLSearchParams();
  if (state.q) p.set('q', state.q);
  if (state.period !== 'all') p.set('period', state.period);
  if (state.pref) p.set('pref', state.pref);
  if (state.venue) p.set('venue', state.venue);
  if (state.genre) p.set('genre', state.genre);
  if (state.hide) p.set('hide', '1');
  const qs = p.toString();
  try { history.replaceState(null, '', qs ? '?' + qs : location.pathname); } catch (_) { /* file:// 等 */ }
}

// ---- 絞り込み UI ----
function addChips(row, items) {
  items.forEach(([v, label, n]) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'chip'; b.dataset.v = v;
    b.innerHTML = esc(label) + (n != null ? `<span class="c">${n}</span>` : '');
    row.appendChild(b);
  });
}
function bindChips(row, key) {
  row.addEventListener('click', ev => {
    const b = ev.target.closest('.chip'); if (!b) return;
    const v = b.dataset.v;
    state[key] = (key !== 'period' && state[key] === v) ? '' : v;  // 選択中をもう一度押すと解除
    if (key === 'pref' && state.venue && state.pref && venueById[state.venue].pref !== state.pref) state.venue = '';
    if (key === 'pref') buildVenueSelect();
    update();
  });
}
addChips($('prefRow'), [['', 'すべて']].concat(Object.keys(prefCount).sort((a, b) => prefRank(a) - prefRank(b)).map(p => [p, p, prefCount[p]])));
addChips($('genreRow'), [['', 'すべて']].concat(GENRE_ORDER.filter(g => events.some(e => (e.genres || []).includes(g))).map(g => [g, g])));
bindChips($('periodRow'), 'period'); bindChips($('prefRow'), 'pref'); bindChips($('genreRow'), 'genre');

function buildVenueSelect() {
  const sel = $('venueSel');
  const vs = venues.filter(v => v.status === 'active' && (!state.pref || v.pref === state.pref))
    .sort((a, b) => prefRank(a.pref) - prefRank(b.pref) || a.area.localeCompare(b.area, 'ja') || a.name.localeCompare(b.name, 'ja'));
  const groups = new Map();
  vs.forEach(v => { const g = (state.pref ? '' : v.pref + ' ') + v.area; if (!groups.has(g)) groups.set(g, []); groups.get(g).push(v); });
  let html = '<option value="">すべての会場</option>';
  groups.forEach((list, g) => {
    html += `<optgroup label="${esc(g)}">` + list.map(v => `<option value="${esc(v.id)}">${esc(v.name)}（${venueCount[v.id] || 0}）</option>`).join('') + '</optgroup>';
  });
  sel.innerHTML = html;
  sel.value = state.venue;
}
$('venueSel').addEventListener('change', ev => { state.venue = ev.target.value; update(); });
$('hideBad').addEventListener('change', ev => { state.hide = ev.target.checked; update(); });
let kwTimer = 0;
$('kw').addEventListener('input', ev => { clearTimeout(kwTimer); kwTimer = setTimeout(() => { state.q = ev.target.value.trim(); update(); }, 150); });
$('resetBtn').onclick = () => {
  Object.assign(state, { q: '', period: 'all', pref: '', venue: '', genre: '', hide: false });
  $('kw').value = ''; buildVenueSelect(); update();
};

function activeFilterCount() {
  return (state.period !== 'all') + !!state.pref + !!state.venue + !!state.genre + state.hide;
}
function syncControls() {
  [['periodRow', 'period'], ['prefRow', 'pref'], ['genreRow', 'genre']].forEach(([id, key]) =>
    $(id).querySelectorAll('.chip').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === state[key]))));
  $('venueSel').value = state.venue;
  $('hideBad').checked = state.hide;
  if ($('kw').value.trim() !== state.q) $('kw').value = state.q;
  const n = activeFilterCount();
  $('filterToggle').textContent = '絞り込み' + (n ? `（${n}）` : '');
  $('resetBtn').hidden = !(n || state.q);
}

const tb = $('toolbar');
// スマホの絞り込みパネル開閉
// パネルは検索バーの直下に重ねて出す（ページ先頭ではバーがヘッダーの下にあるため、位置は実測する）
function placePanel() { document.documentElement.style.setProperty('--panel-top', Math.max(0, tb.getBoundingClientRect().bottom) + 'px'); }
function setPanel(open) {
  if (open) placePanel();
  $('panel').classList.toggle('open', open);
  $('filterToggle').setAttribute('aria-expanded', String(open));
}
window.addEventListener('scroll', () => { if ($('panel').classList.contains('open')) placePanel(); }, { passive: true });
$('filterToggle').onclick = () => setPanel(!$('panel').classList.contains('open'));
$('panelDone').onclick = () => { setPanel(false); scrollToList(); };
document.addEventListener('keydown', ev => {
  if (ev.key === 'Escape') setPanel(false);
  if (ev.key === '/' && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) { ev.preventDefault(); $('kw').focus(); }
});

// 固定ヘッダーの高さを日付見出しの固定位置に反映する
function syncToolbarHeight() { document.documentElement.style.setProperty('--tb-h', tb.offsetHeight + 'px'); }
if (window.ResizeObserver) new ResizeObserver(syncToolbarHeight).observe(tb);
syncToolbarHeight();

// ---- 一覧 ----
function inPeriod(e) {
  if (state.period === 'today') return e.date === todayStr;
  if (state.period === 'tomorrow') return e.date === tomorrowStr;
  if (state.period === 'week') return e.date <= weekEnd;
  if (state.period === 'weekend') return weekendDates.has(e.date);
  return true;
}
function applyFilters() {
  const tokens = norm(state.q).split(/\s+/).filter(Boolean);
  return events.filter(e => inPeriod(e)
    && (!state.pref || e.pref === state.pref)
    && (!state.venue || e.venue_id === state.venue)
    && (!state.genre || (e.genres || []).includes(state.genre))
    && (!state.hide || (e.status !== 'sold_out' && e.status !== 'cancelled'))
    && tokens.every(t => e._hay.includes(t)));
}
function dayHead(e) {
  const [y, m, d] = ymd(e.date);
  const wkCls = e.weekday === '土' ? 'wk-sat' : (e.weekday === '日' ? 'wk-sun' : '');
  const rel = e.date === todayStr ? '今日' : (e.date === tomorrowStr ? '明日' : '');
  const yr = String(y) !== todayStr.slice(0, 4) ? `${y}年` : '';
  return `<div class="day-head">${yr}${m}月${d}日 <span class="${wkCls}">(${esc(e.weekday)})</span>`
    + (rel ? `<span class="rel">${rel}</span>` : '') + `<span class="n">${dateCount[e.date]}件</span></div>`;
}
function cardHTML(e) {
  const note = e.time_note ? esc(e.time_note) : '';
  const time = (e.open || e.start)
    ? `OPEN ${esc(e.open || '-')} / START ${esc(e.start || '-')}` + (note ? `（${note}）` : '')
    : (note || '時間未定（公式ページ参照）');
  const url = safeUrl(e.url);
  const badge = (e.status ? `<span class="badge b-${esc(e.status)}">${esc(STATUS_LABEL[e.status] || e.status)}</span>` : '')
    + (e.stale ? `<span class="badge b-stale" title="今回の収集で会場サイトから取得できなかったため、前回取得した情報を表示しています">前回取得分・未更新</span>` : '');
  const gtags = (e.genres || []).map(g => `<span class="gtag">${esc(g)}</span>`).join('');
  return `<article class="card${e.status === 'cancelled' ? ' is-cancelled' : ''}">`
    + `<div class="meta"><button type="button" class="venue" data-venue="${esc(e.venue_id)}" title="この会場で絞り込む">${esc(e.venue)}</button><span>${esc(e.area)}</span><span>${time}</span></div>`
    + `<h3>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(e.title)}</a>` : esc(e.title)}</h3>`
    + (badge || gtags ? `<div class="badges">${badge}${gtags}</div>` : '')
    + (e.artists && e.artists !== e.title ? `<div class="artists">${esc(e.artists)}</div>` : '')
    + (e.price ? `<div class="price">${esc(e.price)}</div>` : '')
    + `<div class="actions">${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">公式ページ ↗</a>` : ''}`
    + `<button type="button" class="ics-btn" data-i="${e._i}">📅 カレンダーに追加</button></div>`
    + `</article>`;
}
function renderMore() {
  const next = filteredNow.slice(shown, shown + PAGE);
  let out = '';
  next.forEach(e => {
    if (e.date !== lastDate) { lastDate = e.date; out += dayHead(e); }
    out += cardHTML(e);
  });
  $('list').insertAdjacentHTML('beforeend', out);
  shown += next.length;
  $('more').style.display = shown < filteredNow.length ? 'block' : 'none';
}
function update() {
  syncControls();
  writeURL();
  filteredNow = applyFilters();
  dateCount = {};
  filteredNow.forEach(e => { dateCount[e.date] = (dateCount[e.date] || 0) + 1; });
  shown = 0; lastDate = '';
  const filtered = activeFilterCount() || state.q;
  $('count').innerHTML = `<strong>${filteredNow.length}</strong> 件の公演` + (filtered ? `（全 ${events.length} 件中）` : '');
  $('exportBtn').disabled = !filteredNow.length;
  if (!filteredNow.length) {
    $('list').innerHTML = '<div class="empty">条件に合う公演がありません。<br><button type="button" class="btn" id="emptyReset">条件をリセット</button></div>';
    $('emptyReset').onclick = () => $('resetBtn').onclick();
    $('more').style.display = 'none';
    return;
  }
  $('list').innerHTML = '';
  renderMore();
}
function scrollToList() {
  const y = $('list').getBoundingClientRect().top + window.scrollY - tb.offsetHeight - 8;
  if (window.scrollY > y) window.scrollTo({ top: y });
}
$('more').onclick = renderMore;
if (window.IntersectionObserver) {
  new IntersectionObserver(es => { if (es[0].isIntersecting && shown < filteredNow.length) renderMore(); },
    { rootMargin: '800px 0px' }).observe($('more'));
}
$('list').addEventListener('click', ev => {
  const v = ev.target.closest('.venue');
  if (v) {
    state.venue = v.dataset.venue;
    if (state.pref && venueById[state.venue].pref !== state.pref) state.pref = '';
    buildVenueSelect(); update(); scrollToList();
    return;
  }
  const b = ev.target.closest('.ics-btn');
  if (b) { const e = events[Number(b.dataset.i)]; downloadICS([e], 'event-' + e.date + '.ics'); }
});
const toTop = $('toTop');
window.addEventListener('scroll', () => toTop.classList.toggle('show', window.scrollY > 900), { passive: true });
toTop.onclick = () => window.scrollTo({ top: 0, behavior: 'smooth' });

// ---- .ics カレンダー書き出し（JST の公演時刻を UTC に換算して出力） ----
function icsEsc(s) { return String(s == null ? '' : s).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n'); }
function pad2(n) { return String(n).padStart(2, '0'); }
function icsHash(s) { let h = 5381; for (let i = 0; i < s.length; i++) { h = ((h << 5) + h + s.charCodeAt(i)) >>> 0; } return h.toString(36); }
function dtstamp() { const d = new Date(); return d.getUTCFullYear() + pad2(d.getUTCMonth() + 1) + pad2(d.getUTCDate()) + 'T' + pad2(d.getUTCHours()) + pad2(d.getUTCMinutes()) + pad2(d.getUTCSeconds()) + 'Z'; }
// JST の日付＋時刻（+addHours 時間）を UTC の iCalendar 形式 YYYYMMDDTHHMMSSZ にする。
// フローティング時刻だと閲覧端末のタイムゾーンで解釈されてずれるため。
// "25:00" のような深夜表記も Date.UTC の繰り上がりで翌日になる。
function utcDT(ds, ts, addHours) {
  const [y, mo, d] = ymd(ds); const [h, mi] = ts.split(':').map(Number);
  const t = new Date(Date.UTC(y, mo - 1, d, h - 9 + (addHours || 0), mi));
  return t.toISOString().replace(/[-:]/g, '').slice(0, 15) + 'Z';
}
// RFC 5545: 1行 75 オクテットを超える場合は CRLF + 空白で折り返す（UTF-8 のバイト数で数える）
const utf8 = new TextEncoder();
function foldLine(line) {
  let out = '', bytes = 0;
  for (const ch of line) {
    const n = utf8.encode(ch).length;
    if (bytes + n > 75) { out += '\r\n '; bytes = 1; }
    out += ch; bytes += n;
  }
  return out;
}
function eventICS(e, stamp) {
  const lines = ['BEGIN:VEVENT',
    'UID:' + e.venue_id + '-' + e.date + '-' + icsHash(e.title + '|' + e.url) + '@live-in',
    'DTSTAMP:' + stamp];
  const rawT = e.start || e.open;
  const t = /^\d{1,2}:\d{2}$/.test(rawT || '') ? rawT : '';  // "TBA" 等は終日扱い
  if (t) {
    lines.push('DTSTART:' + utcDT(e.date, t));
    lines.push('DTEND:' + utcDT(e.date, t, 2));  // 終了時刻不明のため +2時間
  } else {
    lines.push('DTSTART;VALUE=DATE:' + e.date.replace(/-/g, ''));
    lines.push('DTEND;VALUE=DATE:' + addDays(e.date, 1).replace(/-/g, ''));
  }
  lines.push('SUMMARY:' + icsEsc(e.title));
  lines.push('LOCATION:' + icsEsc(e.venue + '（' + e.pref + '・' + e.area + '）'));
  const desc = [e.artists ? '出演: ' + e.artists : '', e.price ? '料金: ' + e.price : '', '公式: ' + e.url].filter(Boolean).join('\n');
  lines.push('DESCRIPTION:' + icsEsc(desc));
  if (e.status === 'cancelled') lines.push('STATUS:CANCELLED');
  lines.push('END:VEVENT');
  return lines.map(foldLine).join('\r\n');
}
function downloadICS(list, filename) {
  if (!list.length) return;
  const stamp = dtstamp();
  const body = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//live-in//Kanto Live Events//JA', 'CALSCALE:GREGORIAN']
    .concat(list.map(e => eventICS(e, stamp)), ['END:VCALENDAR']).join('\r\n') + '\r\n';
  const blob = new Blob([body], { type: 'text/calendar;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 3000);
}
$('exportBtn').onclick = () => downloadICS(filteredNow, 'live-events.ics');

// ---- 更新時刻と鮮度 ----
function parseGenerated(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/.exec(s || '');
  return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4] - 9, +m[5])) : null;
}
function ago(d) {
  const min = Math.max(1, Math.round((Date.now() - d) / 60000));
  if (min < 60) return `${min}分前`;
  const h = Math.round(min / 60);
  return h < 48 ? `${h}時間前` : `${Math.round(h / 24)}日前`;
}
const gen = parseGenerated(DATA.generated_at);
$('fresh').textContent = '最終更新: ' + DATA.generated_at + (gen ? `（${ago(gen)}）` : '');
$('updated').textContent = '最終更新: ' + DATA.generated_at + ' ｜ 掲載公演数: ' + events.length;
// 1日2回更新のため、26時間以上更新が無ければ注意を出す
if (gen && Date.now() - gen > 26 * 3600 * 1000) {
  $('notice').innerHTML = `<div class="notice">⚠️ 公演データの更新が${ago(gen)}から止まっています。最新の情報は各会場の公式サイトでご確認ください。</div>`;
}

$('venueSummary').textContent = `対象会場（${venues.filter(v => v.status === 'active').length}会場）`;
$('venueList').innerHTML = venues.slice().sort((a, b) => prefRank(a.pref) - prefRank(b.pref)).map(v => {
  const site = safeUrl(v.site_url);
  const name = site ? `<a href="${esc(site)}" target="_blank" rel="noopener">${esc(v.name)}</a>` : esc(v.name);
  const tail = v.status === 'active' ? ` <span class="c">今後 ${venueCount[v.id] || 0} 件</span>` : ' — 取得準備中';
  return `<li>${name}（${esc(v.pref)}・${esc(v.area)}）${tail}</li>`;
}).join('');

readURL();
buildVenueSelect();
update();
</script>
</body>
</html>
"""


def main():
    today = datetime.now(JST).strftime("%Y-%m-%d")
    data = json.loads((ROOT / "data" / "events.json").read_text(encoding="utf-8"))
    venues = json.loads(
        (ROOT / "collector" / "venues.json").read_text(encoding="utf-8"))["venues"]
    upcoming = [e for e in data["events"] if e["date"] >= today]
    payload = {
        "generated_at": data.get("generated_at", ""),
        "events": upcoming,
        "venues": [{k: v.get(k, "") for k in
                    ("id", "name", "pref", "area", "site_url", "status")}
                   for v in venues],
    }
    (ROOT / "web").mkdir(parents=True, exist_ok=True)
    n_active = sum(1 for v in venues if v.get("status") == "active")
    desc = (f"関東のライブハウス・小ホール{n_active}会場の公演スケジュールを、"
            "各会場の公式サイトから毎日自動収集。日付・会場・ジャンルで絞り込み、"
            "カレンダーに追加できます。")
    # データは </script> を含み得るため "</" をエスケープして埋め込む
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html_out = (HTML_TEMPLATE.replace("__DESC__", desc)
                .replace("__DATA_JSON__", data_json))
    (ROOT / "web" / "index.html").write_text(html_out, encoding="utf-8")
    shutil.copyfile(ROOT / "data" / "events.json", ROOT / "web" / "events.json")
    print(f"built web/index.html: {len(upcoming)} upcoming events "
          f"(from {len(data['events'])} collected), today={today}")


if __name__ == "__main__":
    main()
