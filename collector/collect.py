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
  - heavensrock: HEAVEN'S ROCK 各店（/schedule/YYYYMM、詳細URL末尾に日付）
  - baysis:      横浜 BAYSIS（yokohamabaysis.com/schedule.php?mt=YYYY.MM）
  - palooza:     柏 PALOOZA（pc/Schedule/YYYYMM.html、アコーディオン形式）
  - mito_lighthouse: 水戸 LIGHT HOUSE（sche{YY}{月}.html の月別ページ）
  - chiba_look:  千葉 LOOK（schedule/index.html、当月分のみ・表形式）
  - loft_project: LOFT PROJECT 系（全パス 403 メンテナンス表示のため未実装・保留）
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

    @staticmethod
    def _decode(raw, ctype):
        """Content-Type / meta の charset を優先してデコードする。"""
        declared = None
        m_ct = re.search(r"charset=([A-Za-z0-9_\-]+)", ctype or "", flags=re.I)
        if m_ct:
            declared = m_ct.group(1)
        else:
            m_meta = re.search(rb"charset=([A-Za-z0-9_\-]+)", raw[:4096],
                               flags=re.I)
            if m_meta:
                declared = m_meta.group(1).decode("ascii", errors="ignore")
        order = ([declared] if declared else []) + ["utf-8", "euc-jp",
                                                    "shift_jis"]
        for enc in order:
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode(declared or "utf-8", errors="replace")

    def fetch(self, url, timeout=25, accept_404=False):
        """成功時 (True, text)、失敗時 (False, reason)。同一URLはキャッシュ。

        accept_404=True のときは 404 でも本文を返す（HEAVEN'S ROCK の月別
        ページが、正しい内容を 404 ステータスで返すため。採用可否は
        アダプタ側で本文の月見出しを検証して判断する）。
        """
        if url in self.cache:
            return self.cache[url]
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            try:
                resp_ctx = urllib.request.urlopen(req, timeout=timeout)
            except urllib.error.HTTPError as e:
                if not (accept_404 and e.code == 404):
                    raise
                raw = e.read()
                result = (True, self._decode(raw, ""))
                self.cache[url] = result
                return result
            with resp_ctx as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "") or ""
            result = (True, self._decode(raw, ctype))
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


def adapter_heavensrock(venue, fetcher):
    """HEAVEN'S ROCK 各店。/<slug>/schedule/YYYYMM の月別ページ。

    <a class="schedule-item" href=".../schedule/YYYY-MM-DD/"> ごとに1公演で
    詳細URL末尾の日付が明示。OPEN/START は日付ブロック内の text-sm、
    タイトルは text-bold、出演は schedule-list-date-act から取る。
    （一部公演は同日2件目が -2 サフィックスのURLになる）
    """
    events, errors = [], []
    base = venue["schedule_url"].rstrip("/") + "/"
    pat = (r'<a href="(https://www\.heavensrock\.com/[a-z0-9]+/schedule/'
           r'(\d{4}-\d{2}-\d{2})(?:-\d+)?/)" class="schedule-item')
    for (y, m) in two_months(now_jst()):
        url = f"{base}{y}{m:02d}"
        # 月別ページは正しい内容を 404 で返すため accept_404 で取得し、
        # 月見出し (text-lg=月 / text-lead=年) が要求月と一致するか検証する
        ok, res = fetcher.fetch(url, accept_404=True)
        if not ok:
            errors.append(f"{url}: {res}")
            continue
        heads = re.findall(
            r'<span class="text-lg font-en-02">(\d+)</span>.*?'
            r'<span class="text-lead">(\d{4})</span>', res, re.S)
        if not heads or (int(heads[0][0]), int(heads[0][1])) != (m, y):
            errors.append(f"{url}: month header mismatch {heads[:1]}")
            continue
        for match, seg in split_segments(res, pat):
            detail_url, date_str = match.group(1), match.group(2)
            title = re.search(
                r'<div class="text-bold text-sm">(.*?)</div>', seg, re.S)
            act = re.search(
                r'schedule-list-date-act">(.*?)</div>', seg, re.S)
            time_blk = re.search(
                r'schedule-list-date">.*?<div class="text-sm">(.*?)</div>',
                seg, re.S)
            open_t = start_t = ""
            if time_blk:
                tt = clean(time_blk.group(1))
                om = re.search(r"OPEN\s*(?:（1部）|\(1部\))?\s*(\d{1,2}:\d{2})",
                               tt)
                sm = re.search(r"START\s*(?:（1部）|\(1部\))?\s*(\d{1,2}:\d{2})",
                               tt)
                if om:
                    open_t = om.group(1)
                if sm:
                    start_t = sm.group(1)
            ev = make_event(
                venue, date_str,
                title=clean(title.group(1)) if title else "",
                artists=clean(act.group(1)) if act else "",
                open_t=open_t, start_t=start_t,
                url=detail_url, source=url)
            if ev and ev["title"]:
                events.append(ev)
    return events, errors


def adapter_baysis(venue, fetcher):
    """横浜 BAYSIS。公式は yokohamabaysis.com（baysis.jp はパーキング表示）。

    schedule.php?mt=YYYY.MM の月別ページ。<div class="sbox"> ごとに1公演。
    日は .day の "D(曜)"、タイトルは h4 の a name（アンカーID）、
    出演は .guest、開場/開演と前売/当日は .open の冒頭から取る。
    """
    events, errors = [], []
    base = venue["schedule_url"]
    for (y, m) in two_months(now_jst()):
        url = f"{base}?mt={y}.{m:02d}"
        ok, res = fetcher.fetch(url)
        if not ok:
            errors.append(f"{url}: {res}")
            continue
        for _match, seg in split_segments(res, r'<div class="sbox\b'):
            day = re.search(r'<div class="day">(?:<span[^>]*>)?(\d{1,2})\(',
                            seg)
            head = re.search(r'<h4><a name="(\d+)">(.*?)</a></h4>', seg, re.S)
            if not day or not head:
                continue
            guest = re.search(r'<div class="guest">(.*?)</div>', seg, re.S)
            open_blk = re.search(r'<div class="open">(.*?)</div>', seg, re.S)
            open_t = start_t = price = ""
            if open_blk:
                ot = clean(open_blk.group(1))
                om = re.search(r"開場\s*(\d{1,2}:\d{2})", ot)
                sm = re.search(r"開演\s*(\d{1,2}:\d{2})", ot)
                if om:
                    open_t = om.group(1)
                if sm:
                    start_t = sm.group(1)
                prices = []
                am = re.search(r"前売\s*[￥¥]([\d,]+)", ot)
                dm = re.search(r"当日\s*[￥¥]([\d,]+)", ot)
                if am:
                    prices.append(f"前売 ￥{am.group(1)}")
                if dm:
                    prices.append(f"当日 ￥{dm.group(1)}")
                price = " / ".join(prices)
            ev = make_event(
                venue, f"{y}-{m:02d}-{int(day.group(1)):02d}",
                title=clean(head.group(2)),
                artists=clean(guest.group(1)) if guest else "",
                open_t=open_t, start_t=start_t, price=price,
                url=f"{base}?mt={y}.{m:02d}#{head.group(1)}", source=url)
            if ev and ev["title"]:
                events.append(ev)
    return events, errors


def adapter_palooza(venue, fetcher):
    """柏 PALOOZA。pc/Schedule/YYYYMM.html（http のみ応答）。

    jQuery アコーディオン: <h3> に "YYYY.M.D (曜) 見出し"、続く <div> に
    公演日/タイトル/出演者/開場・開演/チケット値段 のラベル形式
    （一部は タイトル：/出演：/時間：/料金： の自由形式）。
    ラベル値が取れる場合はそちらを優先し、見出しをフォールバックにする。
    """
    events, errors = [], []
    base = venue["schedule_url"].rstrip("/") + "/"
    labels = ["公演日", "タイトル", "出演者", "出演", "開場 / 開演", "開場",
              "時間", "チケット値段", "チケット詳細", "チケット予約",
              "料金", "入場順", "お問い合わせ"]

    def label_value(text, names):
        for name in names:
            mm = re.search(re.escape(name) + r"\s*[:：]?\s*", text)
            if not mm:
                continue
            rest = text[mm.end():]
            cut = len(rest)
            for other in labels:
                if other in names:
                    continue
                j = rest.find(other)
                if 0 <= j < cut:
                    cut = j
            val = rest[:cut].strip(" :：/")
            if val:
                return val
        return ""

    for (y, m) in two_months(now_jst()):
        url = f"{base}{y}{m:02d}.html"
        ok, res = fetcher.fetch(url)
        if not ok:
            errors.append(f"{url}: {res}")
            continue
        for _match, seg in split_segments(res, r"<h3>"):
            dm = re.search(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", seg[:200])
            if not dm:
                continue
            head_end = seg.find("</h3>")
            head_txt = clean(seg[:head_end]) if head_end >= 0 else ""
            head_txt = re.sub(
                r"^\d{4}\.\d{1,2}\.\d{1,2}\s*[\(（][^\)）]*[\)）]\s*", "",
                head_txt)
            detail = clean(seg[head_end + 5:]) if head_end >= 0 else clean(seg)
            title = label_value(detail, ["タイトル"]) or head_txt
            artists = label_value(detail, ["出演者", "出演"])
            om = re.search(r"開場\s*[:：]?\s*(\d{1,2}:\d{2})", detail)
            sm = re.search(r"開演\s*[:：]?\s*(\d{1,2}:\d{2})", detail)
            open_t = om.group(1) if om else ""
            start_t = sm.group(1) if sm else ""
            if not open_t:
                tm = re.search(r"(\d{1,2}:\d{2})\s*/\s*(\d{1,2}:\d{2})",
                               detail)
                if tm:
                    open_t, start_t = tm.group(1), tm.group(2)
            price = label_value(detail, ["チケット値段", "料金"])
            if price and ("¥" in price or "￥" in price):
                # "〜THANK YOU! SOLD OUT!!!〜 / 前売り…¥X" のように
                # 料金以外の注記が先行する場合は、¥ を含む部分から採る
                parts = [p.strip() for p in price.split("/")]
                priced = [p for p in parts if "¥" in p or "￥" in p]
                if priced and priced != parts:
                    price = " / ".join(priced)
            if not open_t:
                # 自由形式（例: ※16時30分開場 / 17:00-20:00本番）の救済
                km = re.search(r"(\d{1,2})時(\d{2})分開場", detail)
                if km:
                    open_t = f"{int(km.group(1))}:{km.group(2)}"
                hm = re.search(r"(\d{1,2}):(\d{2})\s*[-–]\s*\d{1,2}:\d{2}",
                               detail)
                if hm and not start_t:
                    start_t = f"{int(hm.group(1))}:{hm.group(2)}"
            if len(price) > 90:
                price = price[:90].rstrip() + "…"
            ev = make_event(
                venue,
                f"{int(dm.group(1))}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}",
                title=title, artists=artists, open_t=open_t,
                start_t=start_t, price=price, url=url, source=url)
            if ev and ev["title"]:
                events.append(ev)
    return events, errors


# mito LIGHT HOUSE の月別ファイル名の月コード（年により表記ゆれあり）
_MITO_MONTH_CODES = {
    1: ["jan"], 2: ["feb", "jfeb"], 3: ["mar"], 4: ["apr"], 5: ["may"],
    6: ["june", "jun"], 7: ["july"], 8: ["aug"], 9: ["sep"], 10: ["oct"],
    11: ["nor", "nov"], 12: ["dec"],
}


def adapter_mito_lighthouse(venue, fetcher):
    """水戸 LIGHT HOUSE。sche{YY}{月コード}.html の月別ページ（Shift_JIS）。

    本文テキストは "YYYY/MM/DD/曜" で公演が区切られ、
    『タイトル』・出演（・区切り）・OPEN/START・前売￥ が続く形式。
    月コードは年により異なる（例: 11月=nor）ため候補を順に試し、
    ページ内に当該年月の日付が含まれるものを採用する。
    """
    events, errors = [], []
    origin = venue["site_url"].rstrip("/")
    for (y, m) in two_months(now_jst()):
        text = None
        used_url = ""
        for code in _MITO_MONTH_CODES[m]:
            url = f"{origin}/sche{y % 100:02d}{code}.html"
            ok, res = fetcher.fetch(url)
            if ok and f"{y}/{m:02d}/" in clean(res):
                text, used_url = clean(res), url
                break
        if text is None:
            errors.append(f"sche{y % 100:02d}({m}月): monthly page not found")
            continue
        parts = re.split(
            r"(\d{4})/(\d{2})/(\d{2})/(?:MON|TUE|WED|THU|FRI|SAT|SUN)", text)
        # parts: [前文, y, m, d, 本文, y, m, d, 本文, ...]
        for i in range(1, len(parts) - 3, 4):
            ey, em, ed = parts[i], parts[i + 1], parts[i + 2]
            seg = re.sub(r"<[^>]*>", " ", parts[i + 3]).strip()
            tm = re.search(r"OPEN\s*(\d{1,2}:\d{2})\s*/\s*START\s*(\d{1,2}:\d{2})",
                           seg)
            open_t = tm.group(1) if tm else ""
            start_t = tm.group(2) if tm else ""
            body = seg[:tm.start()] if tm else seg
            title = ""
            artists = ""
            qm = re.match(r"\s*『(.+?)』\s*(.*)$", body, re.S)
            if qm:
                title = qm.group(1).strip()
                rest = qm.group(2)
            else:
                cut = len(body)
                for sep in (" ・", " OPEN"):
                    j = body.find(sep)
                    if 0 <= j < cut:
                        cut = j
                title = body[:cut].strip()
                rest = body[cut:]
            acts = [a.strip(" /") for a in rest.split("・")]
            artists = " / ".join(a for a in acts if a and len(a) < 80)
            pm = re.search(r"前売\s*[￥¥]([\d,]+)", seg)
            price = f"前売 ￥{pm.group(1)}" if pm else ""
            if not pm:
                dm2 = re.search(r"当日\s*[￥¥]([\d,]+)", seg)
                if dm2:
                    price = f"当日 ￥{dm2.group(1)}"
            ev = make_event(
                venue, f"{ey}-{em}-{ed}", title=title, artists=artists,
                open_t=open_t, start_t=start_t, price=price,
                url=used_url, source=used_url)
            if ev and ev["title"]:
                events.append(ev)
    return events, errors


def adapter_chiba_look(venue, fetcher):
    """千葉 LOOK。schedule/index.html（当月分のみ・表形式）。

    行構成: 月見出し行 "YYYY.MM" / 日見出し行 "- Month D - (曜)" /
    内容行（[タイトル] + 出演 + ＊案内。前売券\\XXXX と OPEN/START を含む場合あり）/
    CHARGE 行（料金または未定）。
    """
    events, errors = [], []
    url = venue["schedule_url"]
    ok, res = fetcher.fetch(url)
    if not ok:
        return [], [f"{url}: {res}"]
    rows = re.findall(r"<tr.*?</tr>", res, re.S | re.I)
    year = month = day = None
    pending = None  # (date_str, title, artists, open, start, price)

    def flush():
        nonlocal pending
        if pending and pending[1]:
            dstr, title, artists, o, s, p = pending
            ev = make_event(venue, dstr, title=title, artists=artists,
                            open_t=o, start_t=s, price=p, url=url, source=url)
            if ev:
                events.append(ev)
        pending = None

    for row in rows:
        txt = clean(row)
        mm = re.fullmatch(r"(\d{4})\.(\d{2})", txt)
        if mm:
            flush()
            year, month, day = int(mm.group(1)), int(mm.group(2)), None
            continue
        dm = re.search(r"-\s*[A-Za-z]+\s+(\d{1,2})\s*-", txt)
        if dm and year and "CHARGE" not in txt:
            flush()
            day = int(dm.group(1))
            continue
        if "CHARGE" in txt and pending:
            val = txt.split("CHARGE", 1)[1].strip(" /")
            vm = re.fullmatch(r"[\\￥¥]?([\d,]+)", val) if val else None
            if vm:
                val = f"￥{vm.group(1)}"
            if val and val != "未定" and not pending[5]:
                dstr, title, artists, o, s, _p = pending
                pending = (dstr, title, artists, o, s, val)
            continue
        if year and day and len(txt) > 8 and "[" in txt:
            flush()
            content = txt
            tm = re.search(r"OPEN\s*(\d{1,2}:\d{2})", content)
            sm = re.search(r"START\s*(\d{1,2}:\d{2})", content)
            qm = re.match(r"\s*\[(.+?)\]\s*(.*)$", content, re.S)
            title = qm.group(1).strip() if qm else ""
            rest = qm.group(2) if qm else content
            artists = rest.split("＊")[0].strip(" /")
            artists = re.sub(r"◆.*$", "", artists).strip(" /")
            artists = re.sub(r"\s*OPEN\s*\d{1,2}:\d{2}.*$", "", artists)
            pm = re.search(r"前売券?\s*[\\￥¥]([\d,]+)", content)
            price = f"前売 ￥{pm.group(1)}" if pm else ""
            pending = (f"{year}-{month:02d}-{day:02d}", title, artists,
                       tm.group(1) if tm else "", sm.group(1) if sm else "",
                       price)
    flush()
    if not events:
        errors.append(f"{url}: no events parsed")
    return events, errors


ADAPTERS = {
    "www_shibuya": adapter_www_shibuya,
    "quattro": adapter_quattro,
    "liquidroom": adapter_liquidroom,
    "parkdiner": adapter_parkdiner,
    "heavensrock": adapter_heavensrock,
    "baysis": adapter_baysis,
    "palooza": adapter_palooza,
    "mito_lighthouse": adapter_mito_lighthouse,
    "chiba_look": adapter_chiba_look,
    # "loft_project": 未実装（全パス 403 メンテナンス表示のため保留）
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
