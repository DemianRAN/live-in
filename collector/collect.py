#!/usr/bin/env python3
"""関東のライブハウス公演情報を各会場の公式サイトから収集し、
data/events.json に正規化して保存する。

使い方:
    python3 collector/collect.py [--venues collector/venues.json]
                                 [--out data/events.json]
                                 [--state data/state.json]

設計方針:
  - 標準ライブラリのみ。pip install 不要（GitHub Actions でもそのまま動く）。
  - ソースは venues.json で宣言する。1会場の失敗が他に波及しない
    （失敗は state.json とログに記録し、処理は続行する）。
  - 収集するのは公演の事実情報（日付・時刻・タイトル・出演・料金）と
    公式詳細ページへのリンクまで。紹介文・画像などは転載しない。
  - チケットプラットフォーム（e+/ぴあ/ローチケ等）は収集対象にしない。
  - 日付は各サイトの月別ページの文脈（URL の YYYYMM 等）から確定する。
    年跨ぎは「対象月 < 現在月 なら翌年」ではなく、月別 URL を
    現在月・翌月で生成するため自然に正しい年になる。

対応アダプタ:
  - www_shibuya: 渋谷 WWW / WWW X（月別 YYYYMM.php、placeLabel で振り分け）
  - quattro:     渋谷 CLUB QUATTRO（?ym=YYYYMM、data-event-date に日付）
  - liquidroom:  恵比寿 LIQUIDROOM（/schedule/YYYY/MM、詳細URL末尾に日付）
  - parkdiner:   つくば PARKDINER（WPイベントアーカイブ、当月分のみ）
  - loft_project: LOFT PROJECT 系（2026-10-26 時点で 403 のため未実装・保留）
"""

import argparse
import html as html_mod
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/130.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
}
WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]  # Mon..Sun

ROOT = Path(__file__).resolve().parent.parent


def now_jst() -> datetime:
    return datetime.now(JST)


def clean(text: str) -> str:
    """タグを除去し、空白を正規化したプレーンテキストにする。"""
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", " / ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip(" /").strip()


def make_event(venue, date_str, title, artists="", open_t="", start_t="",
               price="", url="", source=""):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
    return {
        "venue_id": venue["id"],
        "venue": venue["name"],
        "pref": venue.get("pref", ""),
        "area": venue.get("area", ""),
        "date": date_str,
        "weekday": WEEKDAYS_JA[d.weekday()],
        "open": open_t or "",
        "start": start_t or "",
        "title": title or "",
        "artists": artists or "",
        "price": price or "",
        "url": url or venue.get("site_url", ""),
        "source": source or venue.get("schedule_url", ""),
    }


def split_segments(text, marker_pat):
    """marker_pat のマッチ位置で text を分割し、(マッチ, 区間) のリストを返す。"""
    matches = list(re.finditer(marker_pat, text))
    out = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((m, text[m.start():end]))
    return out


def two_months(base: datetime):
    """現在月と翌月の (year, month) を返す。"""
    y, m = base.year, base.month
    nxt = (y + 1, 1) if m == 12 else (y, m + 1)
    return [(y, m), nxt]


# ---------------------------------------------------------------- fetch

class Fetcher:
    def __init__(self):
        self.cache = {}

    def fetch(self, url, timeout=25):
        """成功時 (True, text)、失敗時 (False, reason)。同一URLはキャッシュ。"""
        if url in self.cache:
            return self.cache[url]
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "") or ""
            declared = None
            m_ct = re.search(r"charset=([A-Za-z0-9_\-]+)", ctype, flags=re.I)
            if m_ct:
                declared = m_ct.group(1)
            else:
                m_meta = re.search(rb"charset=([A-Za-z0-9_\-]+)", raw[:4096],
                                   flags=re.I)
                if m_meta:
                    declared = m_meta.group(1).decode("ascii", errors="ignore")
            order = ([declared] if declared else []) + ["utf-8", "euc-jp",
                                                        "shift_jis"]
            text = None
            for enc in order:
                try:
                    text = raw.decode(enc)
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            if text is None:
                text = raw.decode(declared or "utf-8", errors="replace")
            result = (True, text)
        except Exception as e:  # noqa: BLE001 - 失敗は記録して続行する
            result = (False, f"{type(e).__name__}: {e}")
        self.cache[url] = result
        return result


# ---------------------------------------------------------------- adapters

def adapter_www_shibuya(venue, fetcher):
    """渋谷 WWW / WWW X。月別ページ schedule/YYYYMM.php。

    <article class="column ..."> ごとに1公演。日は <p class="day">、
    会場は placeLabel（"WWW" / "WWW X"）で判定する
    （data-place は複合値があるため使わない）。
    年月はページ URL の YYYYMM が正。
    """
    events, errors = [], []
    base = venue["schedule_url"].rstrip("/") + "/"
    want = venue.get("place_label", venue["name"])
    for (y, m) in two_months(now_jst()):
        url = f"{base}{y}{m:02d}.php"
        ok, res = fetcher.fetch(url)
        if not ok:
            errors.append(f"{url}: {res}")
            continue
        for _match, seg in split_segments(res, r"<article\b"):
            lab = re.search(r'placeLabel">.*?<span>(.*?)</span>', seg, re.S)
            if not lab or clean(lab.group(1)) != want:
                continue
            day = re.search(r'<p class="day">(\d{1,2})</p>', seg)
            artist = re.search(r'<h3 class="title"><span>(.*?)</span></h3>',
                               seg, re.S)
            exp = re.search(r'<p class="exp"><span>(.*?)</span></p>', seg, re.S)
            times = re.search(r'<p class="openstart">(.*?)</p>', seg, re.S)
            link = re.search(r'href="([^"]+)" class="pageLink"', seg)
            if not day or not artist:
                continue
            open_t = start_t = ""
            if times:
                tm = re.search(r"(\d{1,2}:\d{2})\s*/\s*(\d{1,2}:\d{2})",
                               clean(times.group(1)))
                if tm:
                    open_t, start_t = tm.group(1), tm.group(2)
            artist_txt = clean(artist.group(1))
            exp_txt = clean(exp.group(1)) if exp else ""
            ev = make_event(
                venue, f"{y}-{m:02d}-{int(day.group(1)):02d}",
                title=exp_txt or artist_txt, artists=artist_txt,
                open_t=open_t, start_t=start_t,
                url=link.group(1) if link else "", source=url)
            if ev:
                events.append(ev)
    return events, errors


def adapter_quattro(venue, fetcher):
    """渋谷 CLUB QUATTRO。?ym=YYYYMM の月別ページ。

    <li data-event-date="YYYY-MM-DD"> ごとに1公演で日付は明示。
    detail-list の dt/dd から 開場/開演 と 料金 を取る。
    """
    events, errors = [], []
    base = venue["schedule_url"]
    for (y, m) in two_months(now_jst()):
        url = f"{base}?ym={y}{m:02d}"
        ok, res = fetcher.fetch(url)
        if not ok:
            errors.append(f"{url}: {res}")
            continue
        for match, seg in split_segments(res, r'data-event-date="(\d{4}-\d{2}-\d{2})"'):
            date_str = match.group(1)
            artist = re.search(r'<p class="txt-01">(.*?)</p>', seg, re.S)
            title = re.search(r'<p class="txt-02">(.*?)</p>', seg, re.S)
            link = re.search(r'href="(/[^"]*/schedule/detail/\?cd=\d+)"', seg)
            open_t = start_t = price = ""
            for dt, dd in re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>",
                                     seg, re.S):
                dt_t, dd_t = clean(dt), clean(dd)
                if dt_t == "開場/開演":
                    tm = re.search(r"(\d{1,2}:\d{2})\s*/\s*(\d{1,2}:\d{2})",
                                   dd_t)
                    if tm:
                        open_t, start_t = tm.group(1), tm.group(2)
                elif dt_t == "料金":
                    price = dd_t
            artist_txt = clean(artist.group(1)) if artist else ""
            title_txt = clean(title.group(1)) if title else ""
            ev = make_event(
                venue, date_str, title=title_txt or artist_txt,
                artists=artist_txt, open_t=open_t, start_t=start_t,
                price=price,
                url=urllib.parse.urljoin(base, link.group(1)) if link else "",
                source=url)
            if ev:
                events.append(ev)
    return events, errors


def adapter_liquidroom(venue, fetcher):
    """恵比寿 LIQUIDROOM。/schedule/YYYY/MM の月別ページ。

    <article> ごとに1公演。詳細URL末尾の _YYYYMMDD が日付で明示。
    dl の OPEN / START / ADV（/ DOOR）を取る。
    """
    events, errors = [], []
    base = venue["schedule_url"].rstrip("/")
    for (y, m) in two_months(now_jst()):
        url = f"{base}/{y}/{m:02d}"
        ok, res = fetcher.fetch(url)
        if not ok:
            errors.append(f"{url}: {res}")
            continue
        for _match, seg in split_segments(res, r"<article\b"):
            link = re.search(r'<a class="s_link" href="([^"]+)"', seg)
            if not link:
                continue
            dm = re.search(r"_(\d{4})(\d{2})(\d{2})$",
                           urllib.parse.unquote(link.group(1)))
            if not dm:
                continue
            date_str = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"
            artist = re.search(r"<h2>(.*?)</h2>", seg, re.S)
            subtitle = re.search(r'<p class="subtitle">(.*?)</p>', seg, re.S)
            open_t = start_t = ""
            prices = []
            for dt, dd in re.findall(
                    r'<dt class="f1M">(.*?)</dt>\s*<dd>(.*?)</dd>', seg, re.S):
                dt_t, dd_t = clean(dt), clean(dd)
                if dt_t == "OPEN":
                    open_t = dd_t
                elif dt_t == "START":
                    start_t = dd_t
                elif dt_t in ("ADV", "DOOR") and dd_t:
                    prices.append(dd_t)
            artist_txt = clean(artist.group(1)) if artist else ""
            sub_txt = clean(subtitle.group(1)) if subtitle else ""
            ev = make_event(
                venue, date_str, title=sub_txt or artist_txt,
                artists=artist_txt, open_t=open_t, start_t=start_t,
                price=" / ".join(prices), url=link.group(1), source=url)
            if ev:
                events.append(ev)
    return events, errors


def adapter_parkdiner(venue, fetcher):
    """つくば PARKDINER。WP のイベントアーカイブ（当月分のみ表示）。

    月はページ見出しの month_label、年は各公演の year スパンが正。
    excerpt 内の "open/start HH:MM/HH:MM" と "adv/door ..." を抽出する
    （excerpt はサイト側で省略され、料金が途中で切れる場合がある）。
    """
    events, errors = [], []
    url = venue["schedule_url"]
    ok, res = fetcher.fetch(url)
    if not ok:
        return [], [f"{url}: {res}"]
    head = re.search(r'month_label">(\d{1,2})</span>', res)
    if not head:
        return [], [f"{url}: month_label not found"]
    month = int(head.group(1))
    for _match, seg in split_segments(res, r"<article\b"):
        if 'class="item' not in seg[:120]:
            continue
        day = re.search(r'<span class="date">(\d{1,2})</span>', seg)
        year = re.search(r'<span class="year">(\d{4})</span>', seg)
        title = re.search(r'<h3 class="title">(.*?)</h3>', seg, re.S)
        excerpt = re.search(r'<p class="excerpt">(.*?)</p>', seg, re.S)
        link = re.search(r'<a class="link event_button" href="([^"]+)"', seg)
        if not link:  # main_link 側にも詳細URLがある
            link = re.search(r'<a class="main_link[^"]*" href="([^"]+)"', seg)
        if not day or not year or not title:
            continue
        open_t = start_t = price = ""
        if excerpt:
            ex = clean(excerpt.group(1))
            tm = re.search(r"open/start\s*(\d{1,2}:\d{2})\s*/\s*(\d{1,2}:\d{2})",
                           ex, re.I)
            if tm:
                open_t, start_t = tm.group(1), tm.group(2)
            pm = re.search(r"adv/door\s*(.+)$", ex, re.I)
            if pm:
                price = pm.group(1).strip()
        ev = make_event(
            venue, f"{year.group(1)}-{month:02d}-{int(day.group(1)):02d}",
            title=clean(title.group(1)), open_t=open_t, start_t=start_t,
            price=price, url=link.group(1) if link else "", source=url)
        if ev:
            events.append(ev)
    return events, errors


ADAPTERS = {
    "www_shibuya": adapter_www_shibuya,
    "quattro": adapter_quattro,
    "liquidroom": adapter_liquidroom,
    "parkdiner": adapter_parkdiner,
    # "loft_project": 未実装（403 のため保留。venues.json の note 参照）
}


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--venues", default=str(ROOT / "collector" / "venues.json"))
    ap.add_argument("--out", default=str(ROOT / "data" / "events.json"))
    ap.add_argument("--state", default=str(ROOT / "data" / "state.json"))
    args = ap.parse_args()

    venues = json.loads(Path(args.venues).read_text(encoding="utf-8"))["venues"]
    fetcher = Fetcher()
    all_events, seen = [], set()
    state = {"updated_at": now_jst().strftime("%Y-%m-%d %H:%M JST"),
             "venues": {}}
    for venue in venues:
        vid = venue["id"]
        if venue.get("status") != "active":
            state["venues"][vid] = {"status": "pending", "count": 0,
                                    "error": venue.get("note", "")}
            print(f"[pending] {venue['name']}: {venue.get('note', '')[:60]}")
            continue
        fn = ADAPTERS.get(venue.get("adapter", ""))
        if fn is None:
            state["venues"][vid] = {"status": "fail", "count": 0,
                                    "error": f"unknown adapter: {venue.get('adapter')}"}
            print(f"[fail] {venue['name']}: unknown adapter")
            continue
        try:
            events, errors = fn(venue, fetcher)
        except Exception as e:  # noqa: BLE001 - 1会場の例外で全体を止めない
            events, errors = [], [f"{type(e).__name__}: {e}"]
        kept = 0
        for ev in events:
            key = (ev["venue_id"], ev["date"], ev["title"], ev["url"])
            if key in seen:
                continue
            seen.add(key)
            all_events.append(ev)
            kept += 1
        if errors and kept == 0:
            state["venues"][vid] = {"status": "fail", "count": 0,
                                    "error": "; ".join(errors)}
            print(f"[fail] {venue['name']}: {'; '.join(errors)[:160]}")
        else:
            state["venues"][vid] = {
                "status": "ok", "count": kept,
                "error": "; ".join(errors) if errors else ""}
            print(f"[ok] {venue['name']}: {kept} events"
                  + (f" (warnings: {'; '.join(errors)[:120]})" if errors else ""))

    all_events.sort(key=lambda e: (e["date"], e["start"] or "99:99",
                                   e["venue"], e["title"]))
    state["total_events"] = len(all_events)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps({"generated_at": state["updated_at"],
                    "events": all_events}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    Path(args.state).write_text(
        json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"total: {len(all_events)} events -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
