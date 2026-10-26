#!/usr/bin/env python3
"""data/events.json + collector/venues.json から web/index.html を生成する。

生成物は単体 HTML（データを script タグに内包）なので、
そのままブラウザで開いても、GitHub Pages に置いても動く。
表示対象は「本日（JST）以降」の公演のみ、日付昇順。
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
<title>関東ライブまとめ | Live House 公演情報</title>
<style>
  :root { --ink:#23202b; --muted:#6b6577; --line:#e3dff0; --chip:#f1eef9; --accent:#6a3ec9; }
  * { box-sizing: border-box; }
  body { margin:0; font-family:-apple-system,"Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif; color:var(--ink); background:#f8f7fc; }
  header { background:linear-gradient(120deg,#241b4d,#6a3ec9); color:#fff; padding:28px 20px; }
  header h1 { margin:0 0 6px; font-size:22px; }
  header p { margin:0; opacity:.85; font-size:13px; }
  main { max-width:920px; margin:0 auto; padding:16px; }
  .filters { display:flex; flex-wrap:wrap; gap:8px; margin:12px 0 8px; align-items:center; }
  .filters input { flex:1 1 200px; padding:8px 10px; border:1px solid var(--line); border-radius:8px; font-size:14px; background:#fff; }
  .chips { display:flex; flex-wrap:wrap; gap:6px; margin:6px 0; align-items:center; }
  .chips .lbl { font-size:13px; color:var(--muted); }
  .chip { border:1px solid var(--line); background:var(--chip); border-radius:999px; padding:4px 12px; font-size:13px; cursor:pointer; }
  .chip.on { background:var(--accent); color:#fff; border-color:var(--accent); }
  .count { color:var(--muted); font-size:13px; margin:10px 0; }
  .day-head { font-size:15px; margin:22px 0 8px; padding-bottom:4px; border-bottom:2px solid var(--accent); }
  .day-head .wk-sat { color:#2456c8; } .day-head .wk-sun { color:#c82a45; }
  .card { background:#fff; border:1px solid var(--line); border-radius:12px; padding:12px 16px; margin:8px 0; }
  .card h3 { margin:0 0 4px; font-size:15.5px; }
  .card h3 a { color:var(--ink); text-decoration:none; }
  .card h3 a:hover { color:var(--accent); text-decoration:underline; }
  .meta { color:var(--muted); font-size:12.5px; margin-bottom:4px; }
  .artists { font-size:13.5px; line-height:1.6; }
  .price { font-size:13px; color:#7a5200; margin-top:2px; }
  .venue { display:inline-block; font-size:11.5px; padding:2px 8px; border-radius:999px; background:#ece7fb; color:var(--accent); margin-right:6px; }
  .badge { display:inline-block; font-size:11px; font-weight:700; padding:2px 8px; border-radius:4px; margin-right:6px; color:#fff; }
  .b-sold_out { background:#c82a45; } .b-cancelled { background:#44404d; } .b-postponed { background:#d9820a; }
  .gtag { display:inline-block; font-size:11px; padding:2px 8px; border-radius:999px; background:#eef7ee; color:#2e7d32; border:1px solid #cfe6cf; margin-right:4px; }
  .badges { margin:2px 0 5px; }
  .card.is-cancelled { opacity:.6; }
  .actions { margin-top:7px; }
  .ics-btn { border:1px solid var(--line); background:#fff; border-radius:8px; padding:4px 10px; font-size:12.5px; cursor:pointer; color:var(--accent); }
  .ics-btn:hover { background:var(--chip); }
  .hidebad { font-size:13px; color:var(--muted); display:flex; align-items:center; gap:5px; cursor:pointer; }
  .empty { color:var(--muted); text-align:center; padding:40px 0; }
  .venues { margin-top:28px; background:#fff; border:1px solid var(--line); border-radius:12px; padding:16px; font-size:13.5px; }
  .venues h2 { font-size:15px; margin:0 0 8px; }
  .venues li { margin:5px 0; }
  footer { color:var(--muted); font-size:12px; text-align:center; padding:24px 12px 40px; line-height:1.8; }
</style>
</head>
<body>
<header>
  <h1>🎤 関東ライブまとめ</h1>
  <p>関東のライブハウス公演情報を、各会場の公式サイトから毎日自動収集。詳細・チケットは公式ページへ。</p>
</header>
<main>
  <div class="filters">
    <input id="kw" type="search" placeholder="キーワード検索（公演名・出演者・会場）">
  </div>
  <div class="chips" id="periodChips">
    <span class="lbl">期間：</span>
    <button class="chip on" data-period="all">すべて</button>
    <button class="chip" data-period="today">今日</button>
    <button class="chip" data-period="week">今後7日</button>
    <button class="chip" data-period="weekend">週末</button>
  </div>
  <div class="chips" id="prefChips"><span class="lbl">都県：</span></div>
  <div class="chips" id="venueChips"><span class="lbl">会場：</span></div>
  <div class="chips" id="genreChips"><span class="lbl">ジャンル：</span></div>
  <div class="chips">
    <label class="hidebad"><input type="checkbox" id="hideBad"> 完売・中止を隠す</label>
    <button class="chip" id="exportBtn">📅 表示中を .ics で書き出す</button>
  </div>
  <div class="count" id="count"></div>
  <div id="list"></div>
  <section class="venues">
    <h2>対象会場</h2>
    <ul id="venueList"></ul>
  </section>
</main>
<footer>
  <div id="updated"></div>
  <div>公演情報は各会場の公式サイトの発表に基づきます。料金・時間は変更される場合があります。必ず公式詳細ページでご確認ください。</div>
</footer>
<script id="data" type="application/json">__DATA_JSON__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const events = DATA.events, venues = DATA.venues;
const todayStr = DATA.today;
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function addDays(ds, n) { const d = new Date(ds + 'T00:00:00+09:00'); d.setDate(d.getDate() + n); return d.toLocaleDateString('sv-SE', { timeZone: 'Asia/Tokyo' }); }
const weekEnd = addDays(todayStr, 6);
const weekendDates = new Set();
for (let i = 0; i < 7; i++) { const ds = addDays(todayStr, i); const dow = new Date(ds + 'T00:00:00+09:00').getDay(); if (dow === 0 || dow === 6) weekendDates.add(ds); }
let period = 'all', pref = '', venueId = '', kw = '', genre = '', hideBad = false;
let filteredNow = [];
const STATUS_LABEL = { sold_out: 'SOLD OUT', cancelled: '公演中止', postponed: '延期' };
const GENRE_ORDER = ['ロック/バンド', 'アコースティック/弾き語り', 'アイドル', 'ヒップホップ', 'ジャズ', 'クラシック', 'DJ/クラブ', 'トーク/お笑い'];
function mkChips(el, values, cur, fn) {
  el.querySelectorAll('.chip').forEach(c => c.remove());
  const all = document.createElement('button'); all.className = 'chip' + (cur === '' ? ' on' : ''); all.textContent = 'すべて';
  all.onclick = () => fn(''); el.appendChild(all);
  values.forEach(v => { const b = document.createElement('button'); b.className = 'chip' + (cur === v ? ' on' : ''); b.textContent = v; b.onclick = () => fn(v); el.appendChild(b); });
}
const prefChipsEl = document.getElementById('prefChips');
const venueChipsEl = document.getElementById('venueChips');
const genreChipsEl = document.getElementById('genreChips');
function renderChips() {
  mkChips(prefChipsEl, [...new Set(events.map(e => e.pref))].sort(), pref, v => { pref = v; render(); });
  const vs = venues.filter(v => v.status === 'active' && (!pref || v.pref === pref));
  mkChips(venueChipsEl, vs.map(v => v.name), venueId, v => { venueId = v; render(); });
  // 会場チップは名前で絞るため、選択値をそのまま保持する
  venueChipsEl.querySelectorAll('.chip').forEach(c => { if (c.textContent !== 'すべて' && c.textContent === venueId) c.classList.add('on'); });
  const gs = GENRE_ORDER.filter(g => events.some(e => (e.genres || []).includes(g)));
  mkChips(genreChipsEl, gs, genre, v => { genre = v; render(); });
}
function inPeriod(e) {
  if (period === 'today') return e.date === todayStr;
  if (period === 'week') return e.date >= todayStr && e.date <= weekEnd;
  if (period === 'weekend') return weekendDates.has(e.date);
  return true;
}
function render() {
  renderChips();
  const list = events.filter(e => inPeriod(e)
    && (!pref || e.pref === pref)
    && (!venueId || e.venue === venueId)
    && (!genre || (e.genres || []).includes(genre))
    && (!hideBad || (e.status !== 'sold_out' && e.status !== 'cancelled'))
    && (!kw || (e.title + ' ' + e.artists + ' ' + e.venue).includes(kw)));
  filteredNow = list;
  document.getElementById('count').textContent = list.length + ' 件の公演';
  if (!list.length) { document.getElementById('list').innerHTML = '<div class="empty">条件に合う公演がありません。</div>'; return; }
  let out = '', curDate = '';
  list.forEach(e => {
    if (e.date !== curDate) {
      curDate = e.date;
      const wkCls = e.weekday === '土' ? 'wk-sat' : (e.weekday === '日' ? 'wk-sun' : '');
      out += `<div class="day-head">${esc(e.date)} <span class="${wkCls}">(${esc(e.weekday)})</span></div>`;
    }
    const time = (e.open || e.start) ? `OPEN ${esc(e.open || '-')} / START ${esc(e.start || '-')}` : '時間未定（公式ページ参照）';
    const badge = e.status ? `<span class="badge b-${esc(e.status)}">${esc(STATUS_LABEL[e.status] || e.status)}</span>` : '';
    const gtags = (e.genres || []).map(g => `<span class="gtag">${esc(g)}</span>`).join('');
    out += `<div class="card${e.status === 'cancelled' ? ' is-cancelled' : ''}"><div class="meta"><span class="venue">${esc(e.venue)}</span>${esc(e.pref)}・${esc(e.area)} ｜ ${time}</div>`
      + `<h3><a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.title)}</a></h3>`
      + (badge || gtags ? `<div class="badges">${badge}${gtags}</div>` : '')
      + (e.artists && e.artists !== e.title ? `<div class="artists">${esc(e.artists)}</div>` : '')
      + (e.price ? `<div class="price">${esc(e.price)}</div>` : '')
      + `<div class="actions"><button class="ics-btn" data-idx="${events.indexOf(e)}">📅 カレンダーに追加 (.ics)</button></div>`
      + `</div>`;
  });
  document.getElementById('list').innerHTML = out;
  document.querySelectorAll('.ics-btn').forEach(b => b.onclick = () => {
    const e = events[Number(b.dataset.idx)];
    downloadICS([e], 'event-' + e.date + '.ics');
  });
}
// ---- .ics カレンダー書き出し（時刻は JST のローカル時刻として出力） ----
function icsEsc(s) { return String(s == null ? '' : s).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n'); }
function pad2(n) { return String(n).padStart(2, '0'); }
function icsHash(s) { let h = 5381; for (let i = 0; i < s.length; i++) { h = ((h << 5) + h + s.charCodeAt(i)) >>> 0; } return h.toString(36); }
function dtstamp() { const d = new Date(); return d.getUTCFullYear() + pad2(d.getUTCMonth() + 1) + pad2(d.getUTCDate()) + 'T' + pad2(d.getUTCHours()) + pad2(d.getUTCMinutes()) + pad2(d.getUTCSeconds()) + 'Z'; }
function addHoursJST(dateStr, timeStr, hours) {
  let [h, m] = timeStr.split(':').map(Number); h += hours; let ds = dateStr;
  while (h >= 24) { h -= 24; ds = addDays(ds, 1); }
  return [ds, pad2(h) + ':' + pad2(m)];
}
function fmtDT(ds, ts) { const [h, m] = ts.split(':'); return ds.replace(/-/g, '') + 'T' + pad2(Number(h)) + pad2(Number(m)) + '00'; }
function eventICS(e, stamp) {
  const lines = ['BEGIN:VEVENT',
    'UID:' + e.venue_id + '-' + e.date + '-' + icsHash(e.title + '|' + e.url) + '@live-in',
    'DTSTAMP:' + stamp];
  const rawT = e.start || e.open;
  const t = /^\d{1,2}:\d{2}$/.test(rawT || '') ? rawT : '';  // "TBA" 等は終日扱い
  if (t) {
    const [eds, ets] = addHoursJST(e.date, t, 2);
    lines.push('DTSTART:' + fmtDT(e.date, t));
    lines.push('DTEND:' + fmtDT(eds, ets));  // 終了時刻不明のため +2時間
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
  return lines.join('\r\n');
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
document.getElementById('hideBad').addEventListener('change', ev => { hideBad = ev.target.checked; render(); });
document.getElementById('exportBtn').onclick = () => downloadICS(filteredNow, 'live-events.ics');
document.querySelectorAll('#periodChips .chip').forEach(c => c.onclick = () => {
  document.querySelectorAll('#periodChips .chip').forEach(x => x.classList.remove('on'));
  c.classList.add('on'); period = c.dataset.period; render();
});
document.getElementById('kw').addEventListener('input', ev => { kw = ev.target.value.trim(); render(); });
document.getElementById('venueList').innerHTML = venues.map(v =>
  `<li>${v.site_url ? `<a href="${esc(v.site_url)}" target="_blank" rel="noopener">${esc(v.name)}</a>` : esc(v.name)}（${esc(v.pref)}・${esc(v.area)}）${v.status === 'active' ? '' : ' — 取得準備中'}</li>`).join('');
document.getElementById('updated').textContent = '最終更新: ' + DATA.generated_at + ' ｜ 掲載公演数: ' + events.length;
render();
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
        "today": today,
        "events": upcoming,
        "venues": [{k: v.get(k, "") for k in
                    ("id", "name", "pref", "area", "site_url", "status")}
                   for v in venues],
    }
    (ROOT / "web").mkdir(parents=True, exist_ok=True)
    html_out = HTML_TEMPLATE.replace(
        "__DATA_JSON__", json.dumps(payload, ensure_ascii=False))
    (ROOT / "web" / "index.html").write_text(html_out, encoding="utf-8")
    shutil.copyfile(ROOT / "data" / "events.json", ROOT / "web" / "events.json")
    print(f"built web/index.html: {len(upcoming)} upcoming events "
          f"(from {len(data['events'])} collected), today={today}")


if __name__ == "__main__":
    main()
