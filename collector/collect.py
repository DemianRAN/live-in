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
  - 収集後に前回実行分と比較してアラートを生成する（会場の取得失敗・
    0件・like-for-like で 40%超の件数減少）。アラートは state.json の
    "alerts" に保存し、ログ末尾にも要約を出す。詳細は build_alerts 参照。
  - 日付は各サイトの月別ページの文脈（URL の YYYYMM 等）から確定する。
    年跨ぎは「対象月 < 現在月 なら翌年」ではなく、月別 URL を
    現在月・翌月で生成するため自然に正しい年になる。

対応アダプタ:
  - www_shibuya: 渋谷 WWW / WWW X（月別 YYYYMM.php、placeLabel で振り分け。
    一覧に無い料金・時刻は公式詳細ページの dl から補完する）
  - quattro:     渋谷 CLUB QUATTRO（?ym=YYYYMM、data-event-date に日付）
  - liquidroom:  恵比寿 LIQUIDROOM（/schedule/YYYY/MM、詳細URL末尾に日付）
  - parkdiner:   つくば PARKDINER（WPイベントアーカイブ。当月分は通常ページ、
    翌月分はテーマ標準の AJAX (get_events_ajax) で取得。不足フィールドは
    詳細ページから補完する）
  - heavensrock: HEAVEN'S ROCK 各店（/schedule/YYYYMM、詳細URL末尾に日付。
    料金は詳細ページの "Open/Start/Adv/Door" 情報行から補完する）
  - baysis:      横浜 BAYSIS（yokohamabaysis.com/schedule.php?mt=YYYY.MM）
  - palooza:     柏 PALOOZA（pc/Schedule/YYYYMM.html、アコーディオン形式）
  - mito_lighthouse: 水戸 LIGHT HOUSE（sche{YY}{月}.html の月別ページ）
  - chiba_look:  千葉 LOOK（schedule/index.html が当月分、翌月分は
    先取り情報ページ schedule/new.html を同一パーサで読む・表形式）
  - club251:     下北沢 CLUB251（?mo=M&yr=YYYY、Events Manager 形式）
  - toos_calabash: 下北沢 THREE / BASEMENTBAR（toos.co.jp 共通 "calabash"
    イベントシステム。月カレンダー→詳細ページで取得、place_label で振り分け）
  - era:         下北沢 ERA（schedule_cat/YYYY-MM、time datetime に日付明示）
  - shimokita_ticket: 下北沢 Laguna / DaisyBar（同一テーマ・同一アダプタ、
    /schedule/YYYY/M/ の schedule-ticket 記事）
  - mosaic:      下北沢 MOSAiC（schedule.html、当月分のみ・表形式）
  - chikamatsu:  下北沢 近松（/schedule/YYYY/MM/ 一覧 + 詳細ページ）
  - fad:         F.A.D YOKOHAMA（WP投稿一覧、タイトル冒頭の日付が公演日）
  - citta:       川崎 CLUB CITTA'（/schedule?year=YYYY&month=Mon。
    料金と不足時刻は詳細ページの「座種/料金」節などから補完する）
  - bbstreet:    横浜 B.B.STREET（月別アーカイブ /YYYY/MM/?cat=5 のカード）
  - tcf:         つくば ノバホール / つくばカピオ（つくば文化振興財団の
    会場別イベント一覧 /exhibition/<会場>/ の表。tcf_filter で振り分け。
    詳細ページで時刻・出演を補完する）
  - mito_civic:  水戸市民会館（/event/ の月タブ DL カレンダー。公演ホール
    の催しだけに絞り、非公演の催しはタイトルで除外する）
  - hirosawa:    ザ・ヒロサワ・シティ会館（/event/ の「これからのイベント」
    から公演カテゴリのみ。詳細ページに開催日・時間・料金・出演者あり）
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


# ------------------------------------------------------------ status / genre

_STATUS_CANCELLED = (
    r"開催中止|中止となりました|中止といたしました|中止いたします|"
    r"中止を決定|中止のお知らせ|開催の中止|公演を中止|開催を中止|"
    r"【[^】]{0,24}中止[^】]{0,12}】")
_STATUS_POSTPONED = (
    r"開催延期|公演延期|延期となりました|延期いたします|延期を決定|"
    r"延期のお知らせ|振替公演|振替開催|【振替】")
_STATUS_SOLDOUT = r"SOLD\s*OUT|SOLDOUT|ソールドアウト|完売|売り切れ"
_STATUS_ANNOUNCE = (
    r"中止となりました|中止いたします|中止を決定|中止のお知らせ|開催中止")


def _strip_boilerplate(t):
    """状態の「告知」ではない定型文を除去する。

    詳細ページには「※公演中止の場合を除き払い戻しは行いません」
    「※前売り完売の場合は当日券なし」のような条件文・払い戻し注記が
    常設されている。これらは公演の状態ではないため、判定前に落とす。
    払い戻しに触れる区間でも、中止の告知表現を含むものは残す。
    """
    parts = re.split(r"[。/]", t)
    kept = []
    for p in parts:
        if ("払い戻し" in p or "払戻" in p or "返金" in p) and not re.search(
                _STATUS_ANNOUNCE, p):
            continue
        kept.append(p)
    t = " / ".join(kept)
    t = re.sub(r"(完売|SOLD\s*OUT|売り切れ)\s*(の場合|した場合は|の際は?)",
               " ", t, flags=re.I)
    t = re.sub(r"中止\s*(の場合|以外|の際は?)", " ", t)
    t = re.sub(r"(SOLD\s*OUT|完売|売り切れ)\s*(間近|目前)", "", t,
               flags=re.I)
    return t


def detect_status(text):
    """公演自身のテキストから状態を検出する（保守的・明示表現のみ）。

    対象はその公演の一覧セグメントや詳細ページ本文だけ。
    定型文（払い戻し注記・条件文）は _strip_boilerplate で落としてから
    判定する。ページ全体の告知（他公演の案内など）は呼び出し側で
    渡さないこと。戻り値: "cancelled" / "postponed" / "sold_out" / ""。
    """
    if not text:
        return ""
    t = clean(text) if "<" in text else re.sub(r"\s+", " ", text)
    t = _strip_boilerplate(t)
    # 中止の判定はさらに絞る:
    # - 「配信は中止・会場公演は開催」のような配信だけの中止は公演中止にしない
    #   （中止を含む区間のうち配信に触れるものを落としてから判定する）
    # - 「内容を変更して開催」の場合は、公演自体は開催されるため中止にしない
    if not re.search(r"変更して開催", t):
        t_cancel = " / ".join(
            p for p in re.split(r"[。/]", t)
            if not ("配信" in p and "中止" in p))
        if re.search(_STATUS_CANCELLED, t_cancel):
            return "cancelled"
    if re.search(_STATUS_POSTPONED, t):
        return "postponed"
    if re.search(_STATUS_SOLDOUT, t, flags=re.I):
        return "sold_out"
    return ""


# ジャンルタグのキーワード規則（タイトル＋出演者の文字列だけから判定し、
# 手がかりが無ければ付けない。複数タグ可）。規則表は README / PLAN にも明記。
GENRE_RULES = [
    ("ロック/バンド", [r"ロック", r"ROCK", r"パンク", r"PUNK", r"メタル",
                        r"METAL", r"ハードコア", r"HARDCORE",
                        r"シューゲイザー", r"ヴィジュアル系", r"ビジュアル系",
                        r"バンド", r"BAND"]),
    ("アコースティック/弾き語り", [r"アコースティック", r"ACOUSTIC",
                                    r"弾き語り", r"アコギ"]),
    ("アイドル", [r"アイドル", r"IDOL"]),
    ("ヒップホップ", [r"ヒップホップ", r"HIP\s*HOP", r"ラッパー", r"\bRAP\b"]),
    ("ジャズ", [r"ジャズ", r"JAZZ"]),
    ("クラシック", [r"クラシック", r"CLASSIC", r"オーケストラ", r"交響楽団",
                     r"室内楽", r"弦楽四重奏", r"リサイタル"]),
    ("DJ/クラブ", [r"\bDJ\b", r"\bEDM\b", r"テクノ", r"クラブイベント",
                    r"ドラムンベース"]),
    ("トーク/お笑い", [r"トーク", r"お笑い", r"落語", r"漫才",
                       r"TALK\s*(SHOW|EVENT)"]),
]


def detect_genres(title, artists=""):
    """タイトル＋出演者のキーワードからジャンルタグを付ける。"""
    up = f"{title or ''} {artists or ''}".upper()
    return [tag for tag, pats in GENRE_RULES
            if any(re.search(p, up) for p in pats)]


def make_event(venue, date_str, title, artists="", open_t="", start_t="",
               price="", url="", source="", status_src=""):
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
        "status": detect_status(status_src) if status_src else "",
        "genres": detect_genres(title, artists),
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
        転送が途中で切れる IncompleteRead のときだけ1回リトライする
        （BAYSIS 等のサーバが大きなページを途中で切ることがあるため）。
        """
        if url in self.cache:
            return self.cache[url]
        result = self._fetch_once(url, timeout, accept_404)
        if not result[0] and "IncompleteRead" in result[1]:
            result = self._fetch_once(url, timeout, accept_404)
        self.cache[url] = result
        return result

    def _fetch_once(self, url, timeout, accept_404):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            try:
                resp_ctx = urllib.request.urlopen(req, timeout=timeout)
            except urllib.error.HTTPError as e:
                if not (accept_404 and e.code == 404):
                    raise
                raw = e.read()
                return (True, self._decode(raw, ""))
            with resp_ctx as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "") or ""
            result = (True, self._decode(raw, ctype))
        except Exception as e:  # noqa: BLE001 - 失敗は記録して続行する
            result = (False, f"{type(e).__name__}: {e}")
        return result

    def fetch_post(self, url, data, timeout=25):
        """フォーム POST 版（PARKDINER のテーマ標準 AJAX 用）。

        成功時 (True, text)、失敗時 (False, reason)。GET と同じく
        IncompleteRead のときだけ1回リトライし、結果はキャッシュする。
        """
        key = ("POST", url, tuple(sorted(data.items())))
        if key in self.cache:
            return self.cache[key]
        result = self._fetch_post_once(url, data, timeout)
        if not result[0] and "IncompleteRead" in result[1]:
            result = self._fetch_post_once(url, data, timeout)
        self.cache[key] = result
        return result

    def _fetch_post_once(self, url, data, timeout):
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers = dict(HEADERS)
        headers["Content-Type"] = ("application/x-www-form-urlencoded; "
                                   "charset=UTF-8")
        headers["X-Requested-With"] = "XMLHttpRequest"
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "") or ""
            result = (True, self._decode(raw, ctype))
        except Exception as e:  # noqa: BLE001 - 失敗は記録して続行する
            result = (False, f"{type(e).__name__}: {e}")
        return result


# ---------------------------------------------------------------- adapters

def _enrich_www(events, fetcher):
    """WWW 系の詳細ページで料金・時刻を補完する（一覧に無い公演のみ）。

    詳細ページは <dl><dt>OPEN/START</dt><dd>…</dd></dl> と
    <dl><dt>ADV./DOOR</dt><dd>…</dd></dl> の構造化表記。
    料金は ※ で始まる注記を落とし、金額（または無料表記）を含む
    場合だけ採用する。
    """
    filled_p = filled_t = fetched = 0
    for ev in events:
        if ev["price"] and ev["open"] and ev["start"]:
            continue
        url = ev["url"]
        if ".php" not in url:
            continue
        ok, det = fetcher.fetch(url)
        fetched += 1
        if not ok:
            continue
        pairs = {}
        for dt, dd in re.findall(r"<dt>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>",
                                 det, re.S):
            pairs.setdefault(clean(dt), dd)
        if not ev["open"] or not ev["start"]:
            tm = re.search(r"(\d{1,2}:\d{2})\s*/\s*(\d{1,2}:\d{2})",
                           clean(pairs.get("OPEN/START", "")))
            if tm:
                ev["open"], ev["start"] = tm.group(1), tm.group(2)
                filled_t += 1
        if not ev["price"] and "ADV./DOOR" in pairs:
            ptxt = clean(pairs["ADV./DOOR"]).split("※")[0].strip(" /")
            if re.search(r"[¥￥]\s*[\d,]+", ptxt) or "無料" in ptxt:
                if len(ptxt) > 160:
                    ptxt = ptxt[:160].rstrip() + "…"
                ev["price"] = ptxt
                filled_p += 1
        # 状態は詳細ページ全体からは付けない（過去公演一覧や定型注記に
        # 他公演の状態が混ざるため）。料金欄（SOLD OUT 表記が付く場所）と
        # タイトルだけを対象にする。
        if not ev.get("status"):
            st = detect_status(f"{ev['title']} {ev['price']}")
            if st:
                ev["status"] = st
    if fetched:
        print(f"    [enrich] www detail: fetched={fetched} "
              f"price+={filled_p} times+={filled_t}")


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
                url=link.group(1) if link else "", source=url,
                status_src=seg)
            if ev:
                events.append(ev)
    _enrich_www(events, fetcher)
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
                source=url, status_src=seg)
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
                price=" / ".join(prices), url=link.group(1), source=url,
                status_src=seg)
            if ev:
                events.append(ev)
    return events, errors


def _parkdiner_parse_page(res, venue, source_url):
    """PARKDINER の月別 HTML（通常ページ / AJAX 応答共通）を解析する。

    月はページ見出しの month_label、年は各公演の year スパンが正。
    excerpt 内の "open/start HH:MM/HH:MM" と "adv/door ..." を抽出する
    （excerpt はサイト側で省略され、料金が途中で切れる場合がある）。
    month_label が無い場合は (None, []) を返す。
    """
    head = re.search(r'month_label">(\d{1,2})</span>', res)
    if not head:
        return None, []
    month = int(head.group(1))
    events = []
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
            price=price, url=link.group(1) if link else "",
            source=source_url, status_src=seg)
        if ev:
            events.append(ev)
    return month, events


def adapter_parkdiner(venue, fetcher):
    """つくば PARKDINER。WP のイベントアーカイブ（TCD DIVA テーマ）。

    当月分は通常の /schedule/ ページ。翌月分はテーマ標準の AJAX
    エンドポイント（admin-ajax.php, action=get_events_ajax。サイト自身の
    event.js が使う方式で、nonce は /schedule/ ページに埋め込まれた
    event_ajax オブジェクトから取る）で月別 HTML を取得する。
    不足フィールドは詳細ページから補完する。
    """
    events, errors = [], []
    url = venue["schedule_url"]
    ok, res = fetcher.fetch(url)
    if not ok:
        return [], [f"{url}: {res}"]
    month, evs = _parkdiner_parse_page(res, venue, url)
    if month is None:
        return [], [f"{url}: month_label not found"]
    events += evs
    # 翌月分: サイト自身の月送り AJAX
    ny, nm = two_months(now_jst())[1]
    nonce = re.search(r'"nonce":"([0-9a-f]+)"', res)
    ajax = re.search(r'"url":"(https:[^"]*admin-ajax\.php)"', res)
    if nonce and ajax:
        ajax_url = ajax.group(1).replace("\\/", "/")
        ok2, res2 = fetcher.fetch_post(ajax_url, {
            "action": "get_events_ajax",
            "security": nonce.group(1),
            "event_month": f"{ny}-{nm:02d}",
            "filter_event_tag": "0",
        })
        if ok2:
            m2, evs2 = _parkdiner_parse_page(res2, venue, url)
            if m2 == nm:
                events += evs2
            else:
                errors.append(
                    f"parkdiner ajax {ny}-{nm:02d}: month_label={m2}")
        else:
            errors.append(f"parkdiner ajax {ny}-{nm:02d}: {res2}")
    else:
        errors.append("parkdiner: event_ajax params not found "
                      "(next month skipped)")
    # 詳細ページで不足フィールドを補完
    filled_p = filled_t = fetched = 0
    for ev in events:
        if ev["price"] and ev["open"] and ev["start"]:
            continue
        if "/schedule/" not in ev["url"]:
            continue
        ok3, det = fetcher.fetch(ev["url"])
        fetched += 1
        if not ok3:
            continue
        txt = clean(det)
        if not ev.get("status"):
            st = detect_status(txt)
            if st:
                ev["status"] = st
        if not ev["open"] or not ev["start"]:
            tm = re.search(
                r"open/start\s*(\d{1,2}:\d{2})\s*/\s*(\d{1,2}:\d{2})",
                txt, re.I)
            if tm:
                ev["open"], ev["start"] = tm.group(1), tm.group(2)
                filled_t += 1
        if not ev["price"]:
            pm = re.search(r"adv/door\s*[¥￥]([\d,]+)", txt, re.I)
            if pm:
                ev["price"] = f"￥{pm.group(1)}"
                filled_p += 1
    if fetched:
        print(f"    [enrich] parkdiner detail: fetched={fetched} "
              f"price+={filled_p} times+={filled_t}")
    return events, errors


def _parse_hr_detail(txt):
    """HEAVEN'S ROCK 詳細ページの情報行を解析する。

    情報行は "Open H:MM Start H:MM Adv <…> ※ドリンク代別… Door <…>
    ※ドリンク代別… Ticket …" の形式。Adv / Door の各区間から
    ドリンク代注記を除き、金額を含む区間だけを料金として組み立てる
    （SOLD OUT や「未定」だけの区間は料金にしない）。
    戻り値: (open, start, price)。
    """
    open_t = start_t = price = ""
    m = re.search(
        r"Open\s*(?:（1部）|\(1部\))?\s*(\d{1,2}:\d{2})\s+"
        r"Start\s*(?:（1部）|\(1部\))?\s*(\d{1,2}:\d{2})", txt)
    if m:
        open_t, start_t = m.group(1), m.group(2)
    ai = txt.find("Adv", m.end() if m else 0)
    if ai < 0:
        return open_t, start_t, price
    seg_all = txt[ai + 3:ai + 420]
    ti = seg_all.find("Ticket")
    if ti >= 0:
        seg_all = seg_all[:ti]
    di = seg_all.find("Door")
    adv_seg = seg_all[:di] if di >= 0 else seg_all
    door_seg = seg_all[di + 4:] if di >= 0 else ""

    def seg_price(seg):
        seg = re.sub(r"※ドリンク代(別|別途)?\s*[¥￥]?[\d,]*", "", seg)
        seg = seg.replace("※", " / ").replace("￥", "¥")
        seg = re.sub(r"([\d,]+)円", r"¥\1", seg)
        return re.sub(r"\s+", " ", seg).strip(" /")

    parts = []
    a = seg_price(adv_seg)
    if re.search(r"¥[\d,]+", a):
        parts.append("Adv " + a[:90])
    if door_seg:
        d = seg_price(door_seg)
        if re.search(r"¥[\d,]+", d):
            parts.append("Door " + d[:90])
    price = " / ".join(parts)
    return open_t, start_t, price


def _enrich_heavensrock(events, fetcher):
    """HR の詳細ページで料金・時刻を補完する（不足のある公演のみ）。"""
    filled_p = filled_t = fetched = 0
    for ev in events:
        if ev["price"] and ev["open"] and ev["start"]:
            continue
        ok, det = fetcher.fetch(ev["url"])
        fetched += 1
        if not ok:
            continue
        o, s, p = _parse_hr_detail(clean(det))
        if not ev.get("status"):
            st = detect_status(det)
            if st:
                ev["status"] = st
        if (not ev["open"] or not ev["start"]) and o and s:
            ev["open"], ev["start"] = o, s
            filled_t += 1
        if not ev["price"] and p:
            ev["price"] = p
            filled_p += 1
    if fetched:
        print(f"    [enrich] heavensrock detail: fetched={fetched} "
              f"price+={filled_p} times+={filled_t}")


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
                url=detail_url, source=url, status_src=seg)
            if ev and ev["title"]:
                events.append(ev)
    _enrich_heavensrock(events, fetcher)
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
                url=f"{base}?mt={y}.{m:02d}#{head.group(1)}", source=url,
                status_src=seg)
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
                start_t=start_t, price=price, url=url, source=url,
                status_src=seg)
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
                url=used_url, source=used_url, status_src=seg)
            if ev and ev["title"]:
                events.append(ev)
    return events, errors


def _chiba_look_parse(res, venue, page_url):
    """千葉 LOOK の表形式ページ（index.html / new.html 共通）を解析する。

    行構成: 月見出し行 "YYYY.MM" / 日見出し行 "- Month D - (曜)" /
    内容行（[タイトル] + 出演 + ＊案内。前売券\\XXXX と OPEN/START を含む場合あり）/
    CHARGE 行（料金または未定）。
    new.html の先頭の月見出しは案内文と同じ行に混ざるため、行末の
    "YYYY.MM" でも月見出しとして検出する。
    """
    events = []
    rows = re.findall(r"<tr.*?</tr>", res, re.S | re.I)
    year = month = day = None
    pending = None  # (date_str, title, artists, open, start, price, status)

    def flush():
        nonlocal pending
        if pending and pending[1]:
            dstr, title, artists, o, s, p, st = pending
            ev = make_event(venue, dstr, title=title, artists=artists,
                            open_t=o, start_t=s, price=p, url=page_url,
                            source=page_url)
            if ev:
                if st:
                    ev["status"] = st
                events.append(ev)
        pending = None

    for row in rows:
        txt = clean(row)
        mm = re.fullmatch(r"(\d{4})\.(\d{2})", txt)
        if not mm and "[" not in txt and "CHARGE" not in txt:
            mm = re.search(r"(\d{4})\.(\d{2})\s*$", txt)
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
                dstr, title, artists, o, s, _p, st = pending
                pending = (dstr, title, artists, o, s, val, st)
            continue
        if year and day and len(txt) > 8 and "[" in txt and "OPEN" in txt:
            # OPEN を含まない行はフッター等のナビ行として除外する。
            # タイトル括弧が行頭にない行（「学生限定イベント / [FASTLIVE] …」
            # のような前置き付き）にも対応するため括弧は途中から探す。
            flush()
            content = txt
            tm = re.search(r"OPEN\s*(\d{1,2}:\d{2})", content)
            sm = re.search(r"START\s*(\d{1,2}:\d{2})", content)
            qm = re.search(r"\[(.+?)\]\s*(.*)", content, re.S)
            title = qm.group(1).strip() if qm else ""
            rest = qm.group(2) if qm else content
            artists = rest.split("＊")[0].strip(" /")
            artists = re.sub(r"◆.*$", "", artists).strip(" /")
            artists = re.sub(r"\s*OPEN\s*\d{1,2}:\d{2}.*$", "", artists)
            pm = re.search(r"前売券?\s*[\\￥¥]([\d,]+)", content)
            price = f"前売 ￥{pm.group(1)}" if pm else ""
            pending = (f"{year}-{month:02d}-{day:02d}", title, artists,
                       tm.group(1) if tm else "", sm.group(1) if sm else "",
                       price, detect_status(content))
    flush()
    return events


def adapter_chiba_look(venue, fetcher):
    """千葉 LOOK。当月分は schedule/index.html、翌月分は先取り情報ページ
    schedule/new.html（index からリンクされている公式ページで、
    index と同一の表形式で翌月以降数ヶ月分が載る）から取る。
    他会場に揃えて当月・翌月の2ヶ月分だけを採用する。
    """
    events, errors = [], []
    url = venue["schedule_url"]
    ok, res = fetcher.fetch(url)
    if not ok:
        return [], [f"{url}: {res}"]
    events += _chiba_look_parse(res, venue, url)
    ny, nm = two_months(now_jst())[1]
    new_url = urllib.parse.urljoin(url, "new.html")
    ok2, res2 = fetcher.fetch(new_url)
    if ok2:
        for ev in _chiba_look_parse(res2, venue, new_url):
            if (int(ev["date"][:4]), int(ev["date"][5:7])) == (ny, nm):
                events.append(ev)
    else:
        errors.append(f"{new_url}: {res2}")
    if not events:
        errors.append(f"{url}: no events parsed")
    return events, errors


def adapter_club251(venue, fetcher):
    """下北沢 CLUB251。/schedule/?mo=M&yr=YYYY の月別ページ（Events Manager）。

    1日分が <div class="schedule-in"> で、内側 div の class が
    eventful-pre / eventful-post の日は前月・翌月の端数日。
    公演は table.about-in ごとに1件で、h2.eventname がタイトル、
    p.fw-bold が出演、続く <p> に OPEN/START と CHARGE（料金）。
    端数日は当月・翌月の対象期間外になるため、最後に対象月で絞る。
    """
    events, errors = [], []
    base = venue["schedule_url"].rstrip("/") + "/"
    months = two_months(now_jst())
    for (y, m) in months:
        url = f"{base}?mo={m}&yr={y}"
        ok, res = fetcher.fetch(url)
        if not ok:
            errors.append(f"{url}: {res}")
            continue
        for _mt, block in split_segments(res, r'<div class="schedule-in">'):
            cm = re.search(r'class="\s*(eventful[-\w]*)"', block)
            cls = cm.group(1) if cm else ""
            if "eventful-pre" in cls:
                ey, em = (y - 1, 12) if m == 1 else (y, m - 1)
            elif "eventful-post" in cls:
                ey, em = (y + 1, 1) if m == 12 else (y, m + 1)
            else:
                ey, em = y, m
            dm = re.search(
                r'<tr class="list_date[^"]*">\s*<th><span class="fw-bold">'
                r"[^<]*?(\d{1,2})", block)
            if not dm:
                continue
            day = int(dm.group(1))
            for _m2, evseg in split_segments(block, r'<table[^>]*class="about-in"'):
                t = re.search(
                    r'<h2 class="mb10 eventname mt10">(.*?)</h2>', evseg, re.S)
                if not t:
                    continue
                art = re.search(r'<p class="fw-bold">(.*?)</p>', evseg, re.S)
                info = ""
                for pm in re.finditer(r"<p>(.*?)</p>", evseg, re.S):
                    if "OPEN" in pm.group(1):
                        info = clean(pm.group(1))
                        break
                tm = re.search(
                    r"OPEN\s*(\d{1,2}:\d{2})\s*/\s*START\s*(\d{1,2}:\d{2})",
                    info)
                prm = re.search(r"CHARGE\s*[:：]\s*(.+)$", info)
                ev = make_event(
                    venue, f"{ey}-{em:02d}-{day:02d}",
                    title=clean(t.group(1)),
                    artists=clean(art.group(1)) if art else "",
                    open_t=tm.group(1) if tm else "",
                    start_t=tm.group(2) if tm else "",
                    price=prm.group(1).strip() if prm else "",
                    url=f"{base}?mo={em}&yr={ey}", source=url,
                    status_src=evseg)
                if ev:
                    events.append(ev)
    wset = set(months)
    events = [e for e in events
              if (int(e["date"][:4]), int(e["date"][5:7])) in wset]
    return events, errors


def adapter_toos_calabash(venue, fetcher):
    """下北沢 THREE / BASEMENTBAR。toos.co.jp の共通 "calabash" システム。

    会場トップの月カレンダー（?cb_month=YYYY-MM）から公演日と詳細URLを集め
    （複数公演の日は日別ページ経由）、詳細ページ（calabash.b1f/event/...）
    を解析する。詳細の time datetime が日付、h1 がタイトル、
    summary より前の p.p1/p2 が出演、summary〜reservation 間の <p> に
    OPEN/START と料金。両会場の合同公演は各会場のカレンダーに載るため
    それぞれの会場の公演として登録する（サイトの表示どおり）。
    """
    events, errors = [], []
    top = venue["schedule_url"]
    detail_urls = {}  # url -> カレンダー上の日付
    for (y, m) in two_months(now_jst()):
        url = f"{top}?cb_month={y}-{m:02d}"
        ok, res = fetcher.fetch(url)
        if not ok:
            errors.append(f"{url}: {res}")
            continue
        for lab, href in re.findall(
                r'aria-label="([^"]+)"[^>]*href="([^"]+)"', res):
            dm = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", lab)
            if not dm:
                continue
            dstr = (f"{int(dm.group(1))}-{int(dm.group(2)):02d}-"
                    f"{int(dm.group(3)):02d}")
            href = html_mod.unescape(href)
            if "/event/" in href:
                detail_urls.setdefault(href, dstr)
            elif "calabash_day=" in href:
                ok2, day_html = fetcher.fetch(href)
                if not ok2:
                    errors.append(f"{href}: {day_html}")
                    continue
                for eu in set(re.findall(
                        r'href="(https://toos\.co\.jp/calabash\.b1f/event/'
                        r'[^"]+)"', day_html)):
                    detail_urls.setdefault(html_mod.unescape(eu), dstr)
    for u, dstr in sorted(detail_urls.items(), key=lambda kv: kv[1]):
        ok, det = fetcher.fetch(u)
        if not ok:
            errors.append(f"{u}: {det}")
            continue
        art = re.search(r"<article\b.*?</article>", det, re.S)
        seg = art.group(0) if art else det
        dtm = re.search(r'datetime="(\d{4}-\d{2}-\d{2})"', seg)
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", seg, re.S)
        pre = seg.split("toos-event__summary")[0]
        acts = [clean(p) for p in re.findall(
            r'<p class="p[12]">(.*?)</p>', pre, re.S)]
        acts = [a for a in acts if a]
        post = (seg.split("toos-event__summary", 1)[1]
                if "toos-event__summary" in seg else "")
        post = post.split("toos-event__reservation")[0]
        open_t = start_t = ""
        price_parts = []
        for ln in [clean(p) for p in re.findall(
                r"<p[^>]*>(.*?)</p>", post, re.S)]:
            om = re.search(r"OPEN\s*(\d{1,2}:\d{2})", ln)
            sm = re.search(r"START\s*(\d{1,2}:\d{2})", ln)
            if om:
                open_t = om.group(1)
            if sm:
                start_t = sm.group(1)
            if ("¥" in ln or "￥" in ln) and not om and not sm:
                price_parts.append(ln.replace("￥", "¥"))
        ev = make_event(
            venue, dtm.group(1) if dtm else dstr,
            title=clean(h1.group(1)) if h1 else "",
            artists=" / ".join(acts), open_t=open_t, start_t=start_t,
            price=" / ".join(price_parts), url=u, source=top,
            status_src=seg)
        if ev and ev["title"]:
            events.append(ev)
    return events, errors


def adapter_era(venue, fetcher):
    """下北沢 ERA。schedule_cat/YYYY-MM の月別アーカイブ（WP）。

    <article class="block schedule-box"> ごとに1公演。
    <time datetime="YYYY-MM-DD"> に日付明示、h4 がタイトル、
    .w-flyer 冒頭（[出演] ラベル有無ゆれあり）が出演、
    detail-grid の OPEN/START/ADV/DOOR スパンから時刻と料金。
    詳細URLは article id の投稿IDから /schedule/<id>.html を組み立てる。
    """
    events, errors = [], []
    base = venue["schedule_url"].rstrip("/") + "/"
    for (y, m) in two_months(now_jst()):
        url = f"{base}{y}-{m:02d}"
        ok, res = fetcher.fetch(url)
        if not ok:
            errors.append(f"{url}: {res}")
            continue
        for _mt, seg in split_segments(res, r"<article\b"):
            dt = re.search(r'<time datetime="(\d{4}-\d{2}-\d{2})"', seg)
            if not dt or not dt.group(1).startswith(f"{y}-{m:02d}"):
                continue
            t = re.search(r"<h4>(.*?)</h4>", seg, re.S)
            artists = ""
            wf = re.search(
                r'<div class="w-flyer">(.*?)(?:<div class="detail-texts">|'
                r'<section class="notes-wrapper">)', seg, re.S)
            if wf:
                txt = clean(wf.group(1))
                parts = re.split(r"\[[^\]]+\]", txt, maxsplit=1)
                artists = (parts[1] if txt.startswith("[出演]")
                           and len(parts) > 1 else parts[0]).strip(" /")
                artists = re.sub(r"\s*/\s*/\s*", " / ", artists)
            pairs = dict(re.findall(
                r'<span class="title">(OPEN|START|ADV|DOOR)</span>\s*'
                r'<span class="strong">(.*?)</span>', seg))
            prices = []
            if pairs.get("ADV"):
                prices.append(f"ADV {clean(pairs['ADV'])}")
            if pairs.get("DOOR"):
                prices.append(f"DOOR {clean(pairs['DOOR'])}")
            price = " / ".join(prices)
            extra = re.search(r'class="inline-block">\(([^<]+)\)', seg)
            if extra and price:
                price += f" ({clean(extra.group(1))})"
            pid = re.search(r'<article id="box-\d+-(\d+)"', seg)
            url_ev = (f"http://s-era.jp/schedule/{pid.group(1)}.html"
                      if pid else url)
            ev = make_event(
                venue, dt.group(1),
                title=clean(t.group(1)) if t else "",
                artists=artists,
                open_t=clean(pairs.get("OPEN", "")),
                start_t=clean(pairs.get("START", "")),
                price=price, url=url_ev, source=url, status_src=seg)
            if ev and ev["title"]:
                events.append(ev)
    return events, errors


def adapter_shimokita_ticket(venue, fetcher):
    """下北沢 Laguna / DaisyBar（同一 WP テーマ・同一アダプタ）。

    /schedule/YYYY/M/ の月別ページ。<article class="schedule-ticket">
    ごとに1公演。日は .month/.day スパン、h2 がタイトル、
    p.artist が出演、中段のラベル/値ペア（OPEN/START/前売/当日/配信）
    から時刻と料金（配信は除く）。
    """
    events, errors = [], []
    base = venue["schedule_url"].rstrip("/") + "/"
    for (y, m) in two_months(now_jst()):
        url = f"{base}{y}/{m}/"
        ok, res = fetcher.fetch(url)
        if not ok:
            errors.append(f"{url}: {res}")
            continue
        for _mt, seg in split_segments(res, r'<article class="schedule-ticket">'):
            mm = re.search(
                r"<span class='month'>(\d{1,2})\s*/</span>"
                r"<span class='day'>(\d{1,2})</span>", seg)
            if not mm or int(mm.group(1)) != m:
                continue
            t = re.search(r"<h2>(.*?)</h2>", seg, re.S)
            art = re.search(r'<p class="artist">(.*?)</p>', seg, re.S)
            pairs = {}
            for lm, vm in re.findall(
                    r"<div>\s*<p>([^<]+)</p>\s*<p>([^<]*)</p>\s*</div>", seg):
                pairs[lm.strip()] = vm.strip()
            prices = []
            if pairs.get("前売"):
                prices.append(f"前売 {pairs['前売']}")
            if pairs.get("当日"):
                prices.append(f"当日 {pairs['当日']}")
            ev = make_event(
                venue, f"{y}-{m:02d}-{int(mm.group(2)):02d}",
                title=clean(t.group(1)) if t else "",
                artists=clean(art.group(1)) if art else "",
                open_t=pairs.get("OPEN", ""), start_t=pairs.get("START", ""),
                price=" / ".join(prices), url=url, source=url,
                status_src=seg)
            if ev and ev["title"]:
                events.append(ev)
    return events, errors


def adapter_mosaic(venue, fetcher):
    """下北沢 MOSAiC。schedule.html（当月分のみ・旧来の表レイアウト）。

    <div class="centerCont bottomLiner" id="D"> ごとに1日分。
    listCal の th "M/D" が日付、p.live_title がタイトル、
    td.live_menu の <strong> が出演、続く行に OPEN/START と料金。
    live_title のない日（休業・貸切のみ等）は対象外。
    """
    events, errors = [], []
    url = venue["schedule_url"]
    ok, res = fetcher.fetch(url)
    if not ok:
        return [], [f"{url}: {res}"]
    now = now_jst()
    for _mt, block in split_segments(res, r'<div class="centerCont bottomLiner"'):
        dm = re.search(r'<th width="90">(\d{1,2})/(\d{1,2})</th>', block)
        if not dm:
            continue
        mo, day = int(dm.group(1)), int(dm.group(2))
        if mo != now.month:
            errors.append(f"{url}: month mismatch page={mo} now={now.month}")
            break
        titles = re.findall(r'<p class="live_title">(.*?)</p>', block, re.S)
        if not titles:
            continue
        menu = re.search(
            r'<td width="896" class="live_menu">(.*?)</td>', block, re.S)
        menu_txt = clean(menu.group(1)) if menu else ""
        strong = (re.search(r"<strong>(.*?)</strong>", menu.group(1), re.S)
                  if menu else None)
        artists = clean(strong.group(1)) if strong else ""
        if artists and menu_txt.startswith(artists):
            menu_txt = menu_txt[len(artists):].strip(" /")
        tm = re.search(
            r"OPEN\s*(\d{1,2}:\d{2})\s*/\s*START\s*(\d{1,2}:\d{2})", menu_txt)
        rest = menu_txt[tm.end():] if tm else menu_txt
        parts = [p.strip() for p in rest.split(" / ")]
        price = " / ".join(p for p in parts
                           if ("¥" in p or "￥" in p) and not p.startswith("●"))
        ev = make_event(
            venue, f"{now.year}-{mo:02d}-{day:02d}",
            title=clean(titles[0]), artists=artists,
            open_t=tm.group(1) if tm else "",
            start_t=tm.group(2) if tm else "",
            price=price, url=f"{url}#{day}", source=url, status_src=block)
        if ev and ev["title"]:
            events.append(ev)
    return events, errors


def adapter_chikamatsu(venue, fetcher):
    """下北沢 近松。/schedule/YYYY/MM/ の月別一覧 + 個別詳細ページ。

    一覧の <a class="entry-link"> 内に time datetime（日付明示）と
    h2（タイトル）。詳細ページ本文の "OPEN / START H:MM/H:MM"、
    "ADV / DOOR ..."、"LINE UP ..." から時刻・料金・出演を取る。
    """
    events, errors = [], []
    base = venue["schedule_url"].rstrip("/") + "/"
    for (y, m) in two_months(now_jst()):
        url = f"{base}{y}/{m:02d}/"
        ok, res = fetcher.fetch(url)
        if not ok:
            errors.append(f"{url}: {res}")
            continue
        entries = []
        seen_u = set()
        for am in re.finditer(
                r'<a [^>]*href="([^"]+/schedule/\d{4}/\d{2}/\d{2}-id\d+\.php)"'
                r"[^>]*>(.*?)</a>", res, re.S):
            inner = am.group(2)
            tm2 = re.search(r'<time[^>]*datetime="(\d{4}-\d{2}-\d{2})"', inner)
            h2 = re.search(r"<h2[^>]*>(.*?)</h2>", inner, re.S)
            if tm2 and h2 and am.group(1) not in seen_u:
                seen_u.add(am.group(1))
                entries.append((am.group(1), tm2.group(1), clean(h2.group(1))))
        if not entries:
            errors.append(f"{url}: no entries parsed")
        for u, dstr, title in entries:
            open_t = start_t = price = artists = ""
            ok2, det = fetcher.fetch(u)
            if not ok2:
                errors.append(f"{u}: {det}")
            else:
                txt = clean(det)
                # 詳細には "OPEN / START H:MM/H:MM" 形式と
                # "OPEN H:MM / START H:MM" 形式の2レイアウトがある
                tm = re.search(
                    r"OPEN\s*(\d{1,2}:\d{2})\s*/\s*START\s*(\d{1,2}:\d{2})",
                    txt)
                if not tm:
                    tm = re.search(
                        r"OPEN\s*/\s*START\s*(\d{1,2}:\d{2})\s*/\s*"
                        r"(\d{1,2}:\d{2})", txt)
                if tm:
                    open_t, start_t = tm.group(1), tm.group(2)
                pm = re.search(r"ADV\s*/\s*DOOR\s*(.+?)\s*LINE UP", txt)
                if pm:
                    price = pm.group(1).replace("￥", "¥")
                am2 = re.search(r"LINE UP\s*(.+?)\s*TICKET", txt)
                if am2:
                    artists = re.sub(r"\s*/\s*", " / ", am2.group(1)).strip()
            status_src = ""
            if ok2:
                _t = clean(det)
                _i = _t.find(title[:20]) if title else -1
                status_src = _t[_i:_i + 2000] if _i >= 0 else _t[:2000]
            ev = make_event(
                venue, dstr, title=title, artists=artists,
                open_t=open_t, start_t=start_t, price=price,
                url=u, source=url, status_src=status_src)
            if ev and ev["title"]:
                events.append(ev)
    return events, errors


def adapter_fad(venue, fetcher):
    """F.A.D YOKOHAMA。公式 WP（/fad/）の投稿一覧を使う。

    投稿は公演日昇順に並び、タイトル冒頭の 'YY.MM.DD [曜] が公演日
    （日付のない告知投稿や期間まとめ投稿は対象外）。
    一覧は最大3ページまで辿り、当月・翌月の公演だけ詳細ページから
    OPEN/START と ADV/DOOR を補う。タイトルには公演名と出演が
    混在するのがサイトの表記のため、そのままタイトルとして掲載する。
    """
    events, errors = [], []
    base = venue["schedule_url"].rstrip("/") + "/"
    months = two_months(now_jst())
    wset = set(months)
    posts = {}  # url -> (date_str, title)
    for page in range(1, 4):
        url = base if page == 1 else f"{base}?paged={page}"
        ok, res = fetcher.fetch(url)
        if not ok:
            errors.append(f"{url}: {res}")
            break
        found = 0
        for u, raw_t in re.findall(
                r'<h3 class="entry-title"><a[^>]+href="([^"]+)"[^>]*>'
                r"(.*?)</a></h3>", res, re.S):
            t = clean(raw_t)
            dm = re.search(r"(\d{2})\.(\d{1,2})\.(\d{1,2})\s*\[[^\]]*\]",
                           t[:20])
            if not dm:
                continue
            yy = 2000 + int(dm.group(1))
            dstr = f"{yy}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}"
            posts[u] = (dstr, t[dm.end():].strip())
            found += 1
        if not found:
            break
    for u, (dstr, title) in sorted(posts.items(), key=lambda kv: kv[1][0]):
        if (int(dstr[:4]), int(dstr[5:7])) not in wset:
            continue
        open_t = start_t = price = ""
        ok, det = fetcher.fetch(u)
        if not ok:
            errors.append(f"{u}: {det}")
        else:
            txt = clean(det)
            # <title> にも同じ文字列があるため、本文側の出現（最後の一致）を
            # アンカーにする。取れなければページ全体から探す。
            i = txt.rfind(title[:20])
            seg = txt[i:i + 1500] if i >= 0 else txt
            om = re.search(r"OPEN\s*(\d{1,2}:\d{2})", seg)
            sm = re.search(r"START\s*(\d{1,2}:\d{2})", seg)
            if not om:
                om = re.search(r"OPEN\s*(\d{1,2}:\d{2})", txt)
                sm = re.search(r"START\s*(\d{1,2}:\d{2})", txt)
            open_t = om.group(1) if om else ""
            start_t = sm.group(1) if sm else ""
            pm = re.search(
                r"ADV\s*[¥￥]([\d,]+)(?:\s*/\s*DOOR\s*[¥￥]([\d,]+))?", seg)
            if not pm:
                pm = re.search(
                    r"ADV\s*[¥￥]([\d,]+)(?:\s*/\s*DOOR\s*[¥￥]([\d,]+))?",
                    txt)
            if pm:
                price = f"ADV ¥{pm.group(1)}"
                if pm.group(2):
                    price += f" / DOOR ¥{pm.group(2)}"
        ev = make_event(
            venue, dstr, title=title, open_t=open_t, start_t=start_t,
            price=price, url=u, source=base,
            status_src=seg if ok else "")
        if ev and ev["title"]:
            events.append(ev)
    return events, errors


_CITTA_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _parse_citta_detail(txt):
    """CLUB CITTA' 詳細ページから OPEN/START と料金節を取る。

    時刻はページ冒頭の見出しブロックにある最初の OPEN/START。
    料金は「座種/料金」節（一般発売日などの次節まで）から ※ 注記を
    除いて組み立て、金額表記を含む場合だけ採用する（金額の無い
    自由形式の案内文は料金にしない）。
    戻り値: (open, start, price)。
    """
    om = re.search(r"OPEN\s*(\d{1,2}:\d{2})", txt)
    sm = re.search(r"START\s*(\d{1,2}:\d{2})", txt)
    price = ""
    i = txt.find("座種/料金")
    if i >= 0:
        seg = txt[i + len("座種/料金"):]
        for marker in ("一般発売日", "チケット販売", "お問い合わせ", "関連公演"):
            j = seg.find(marker)
            if j >= 0:
                seg = seg[:j]
        parts = [p.strip() for p in seg.split(" / ")]
        parts = [p for p in parts if p and not p.startswith("※")]
        seg2 = " / ".join(parts)
        if re.search(r"[\d,]+円|[¥￥][\d,]+", seg2):
            price = seg2[:140].rstrip()
            if len(seg2) > 140:
                price += "…"
    return (om.group(1) if om else "", sm.group(1) if sm else "", price)


def _enrich_citta(events, fetcher):
    """CITTA' の詳細ページで料金・時刻を補完する（不足のある公演のみ）。"""
    filled_p = filled_t = fetched = 0
    for ev in events:
        if ev["price"] and ev["open"] and ev["start"]:
            continue
        ok, det = fetcher.fetch(ev["url"])
        fetched += 1
        if not ok:
            continue
        o, s, p = _parse_citta_detail(clean(det))
        # 状態は料金節とタイトルだけから付ける（詳細ページ全体には
        # 「前売り完売の場合は…」等の定型条件文があるため）
        if not ev.get("status"):
            st = detect_status(f"{ev['title']} {p}")
            if st:
                ev["status"] = st
        got_t = False
        if not ev["open"] and o:
            ev["open"] = o
            got_t = True
        if not ev["start"] and s:
            ev["start"] = s
            got_t = True
        if got_t:
            filled_t += 1
        if not ev["price"] and p:
            ev["price"] = p
            filled_p += 1
    if fetched:
        print(f"    [enrich] citta detail: fetched={fetched} "
              f"price+={filled_p} times+={filled_t}")


def adapter_citta(venue, fetcher):
    """川崎 CLUB CITTA'。/schedule?year=YYYY&month=Mon の月別ページ。

    <div class="item"> ごとに1公演。日は item_detail の <p>、
    h3 がタイトル、txt_wrap の <p> 冒頭に OPEN/START、続いて出演。
    当月分はサイト仕様で本日以降のみ表示される。料金は一覧に無いため
    詳細ページから補完する（_enrich_citta）。
    """
    events, errors = [], []
    base = venue["schedule_url"].rstrip("/")
    for (y, m) in two_months(now_jst()):
        url = f"{base}?year={y}&month={_CITTA_MONTHS[m - 1]}"
        ok, res = fetcher.fetch(url)
        if not ok:
            errors.append(f"{url}: {res}")
            continue
        for match, seg in split_segments(
                res, r'<div class="item"><a href="'
                r'(https://clubcitta\.co\.jp/schedule/\d+)">'):
            dm = re.search(
                r'<div class="item_detail[^"]*">\s*<p>(\d{1,2})<span>', seg)
            t = re.search(r"<h3>(.*?)</h3>", seg, re.S)
            if not dm or not t:
                continue
            tw = re.search(r'<div class="txt_wrap">(.*?)</div>\s*</div>',
                           seg, re.S)
            body = (re.search(r"<p>(.*?)</p>", tw.group(1), re.S)
                    if tw else None)
            txt = clean(body.group(1)) if body else ""
            om = re.search(r"OPEN\s*(\d{1,2}:\d{2})", txt)
            sm = re.search(r"START\s*(\d{1,2}:\d{2})", txt)
            artists = re.sub(
                r"^(OPEN\s*\d{1,2}:\d{2}\s*/\s*START\s*\d{1,2}:\d{2}|"
                r"START\s*\d{1,2}:\d{2}～?|OPEN\s*\d{1,2}:\d{2})\s*", "",
                txt).strip(" /")
            ev = make_event(
                venue, f"{y}-{m:02d}-{int(dm.group(1)):02d}",
                title=clean(t.group(1)), artists=artists,
                open_t=om.group(1) if om else "",
                start_t=sm.group(1) if sm else "",
                url=match.group(1), source=url,
                # seg は次のマッチまで長く伸びて他公演を含むため、
                # 状態判定は自公演の本文（txt_wrap）とタイトルだけに限る
                status_src=f"{clean(t.group(1))} {txt}")
            if ev and ev["title"]:
                events.append(ev)
    _enrich_citta(events, fetcher)
    return events, errors


def adapter_bbstreet(venue, fetcher):
    """横浜 B.B.STREET。月別アーカイブ /YYYY/MM/?cat=5 のカード形式。

    カードのアンカーテキストに "YYYY.MM.DD (曜) タイトル OPEN H:MM
    START H:MM ADV ¥X(+1D) DOOR ¥Y(+1D) 出演 MORE INFO" まで含まれる
    ため、一覧だけで完結する。月は各カードの日付が明示。
    """
    events, errors = [], []
    origin = venue["site_url"].rstrip("/")
    for (y, m) in two_months(now_jst()):
        url = f"{origin}/{y}/{m:02d}/?cat=5"
        ok, res = fetcher.fetch(url)
        if not ok:
            errors.append(f"{url}: {res}")
            continue
        cards = {}
        for u, raw in re.findall(
                r'href="(https://www\.bbstreet\.com/schedule/[^"]+)"[^>]*>'
                r"(.*?)</a>", res, re.S):
            t = clean(raw)
            dm = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})\s*\([^)]*\)\s*",
                          t)
            if dm and (u not in cards or len(t) > len(cards[u][1])):
                dstr = (f"{dm.group(1)}-{int(dm.group(2)):02d}-"
                        f"{int(dm.group(3)):02d}")
                cards[u] = (dstr, t)
        for u, (dstr, full) in sorted(cards.items(), key=lambda kv: kv[1][0]):
            if not dstr.startswith(f"{y}-{m:02d}"):
                continue
            om = re.search(r"OPEN\s+(\d{1,2}:\d{2})", full)
            sm = re.search(r"START\s+(\d{1,2}:\d{2})", full)
            cuts = [mm.start() for mm in re.finditer(
                r"\s+(?:OPEN|ADV|DOOR)\s+(?:\d|TBA|[¥￥]|FREE)", full)]
            title = (full[:min(cuts)] if cuts else full)
            title = re.sub(
                r"^\d{4}\.\d{1,2}\.\d{1,2}\s*\([^)]*\)\s*", "", title).strip()
            price_parts = []
            tail = full
            for lab in ("ADV", "DOOR"):
                pm = re.search(
                    lab + r"\s*([¥￥][\d,]+(?:\+1D\([¥￥][\d,]+\))?|FREE|TBA)",
                    full)
                if pm and pm.group(1) != "TBA":
                    price_parts.append(f"{lab} {pm.group(1)}")
            for mm in re.finditer(
                    r"(?:ADV|DOOR)\s*(?:[¥￥][\d,]+(?:\+1D\([¥￥][\d,]+\))?"
                    r"|FREE|TBA)", full):
                tail = full[mm.end():]
            artists = (tail.replace("MORE INFO", "").strip(" /")
                       if price_parts else "")
            ev = make_event(
                venue, dstr, title=title, artists=artists,
                open_t=om.group(1) if om else "",
                start_t=sm.group(1) if sm else "",
                price=" / ".join(price_parts), url=u, source=url,
                status_src=full)
            if ev and ev["title"]:
                events.append(ev)
    return events, errors


# ---------------------------------------------------------------- halls
# 公共ホール（小ホール二期）。方針: 公演ホールでの公開公演だけを載せる。
# 学校・教室の発表会、施設の一般開放・見学会、映画上映、講座・セミナー
# 類はタイトルパターンで除外する（判断の根拠は PLAN.md 参照）。

_HALL_EXCLUDE_TITLE = re.compile(
    r"発表会|一般開放|施設見学会|見学会|上映|コンクール|セミナー|"
    r"講演会|講座|相談会|体験会|式典|催物一覧|科学フェスティバル|"
    r"安全・安心フェスタ|スクール対抗戦|３×３|3X3|保育園|幼稚園")


def _enrich_tcf(events_by_url, fetcher):
    """TCF 詳細ページの「日時」節から開演・開場時刻、「出演」節から
    出演者を補完する。多日程・昼夕2部制の場合は先頭の時刻を採用する。"""
    fetched = filled_t = filled_a = 0
    for url, evs in events_by_url.items():
        ok, det = fetcher.fetch(url)
        fetched += 1
        if not ok:
            continue
        txt = clean(det)
        # 詳細ページには2つの書式がある: 「日時 … 14：00開演（12：30開場）」
        # と「開催日時 … / 開場 17:30 / 開演 18:00」。日時見出しから
        # 400字の範囲で両書式を探す
        i = txt.find("日時")
        seg = txt[i:i + 400] if i >= 0 else txt[:1200]
        sm = (re.search(r"(\d{1,2})[:：](\d{2})\s*開演", seg)
              or re.search(r"開演\s*(\d{1,2})[:：](\d{2})", seg))
        om = (re.search(r"(\d{1,2})[:：](\d{2})\s*開場", seg)
              or re.search(r"開場\s*(\d{1,2})[:：](\d{2})", seg))
        start_t = f"{sm.group(1)}:{sm.group(2)}" if sm else ""
        open_t = f"{om.group(1)}:{om.group(2)}" if om else ""
        artists = ""
        am = re.search(r"出演\s*(.*?)\s*(?:料金|発売日|チケット)", txt)
        if am:
            artists = am.group(1).strip(" /")[:140]
        st = detect_status(seg)
        for ev in evs:
            if start_t and not ev["start"]:
                ev["start"] = start_t
                filled_t += 1
            if open_t and not ev["open"]:
                ev["open"] = open_t
            if artists and not ev["artists"]:
                ev["artists"] = artists
                filled_a += 1
            if st and not ev["status"]:
                ev["status"] = st
    if fetched:
        print(f"    [enrich] tcf detail: fetched={fetched} "
              f"start+={filled_t} artists+={filled_a}")


def adapter_tcf(venue, fetcher):
    """つくば文化振興財団（TCF）の会場別イベント一覧を読む。

    /exhibition/novahall/ ・ /exhibition/capio/ の表
    （tr data-filter="<会場キー>": 公演名リンク / 日程 / 場所 / 備考）。
    月刊 PDF「催物案内」は施設全体の暦（アリーナのスポーツ催事や
    学校行事も含む）だが、この HTML 一覧は財団が公演情報として
    整理したもの。それでも学校の発表会等が混ざるため
    _HALL_EXCLUDE_TITLE で落とす。備考欄を料金として採用し、
    詳細ページで時刻・出演を補完する。
    """
    ok, page = fetcher.fetch(venue["schedule_url"])
    if not ok:
        return [], [page]
    filt = venue.get("tcf_filter", "")
    events, by_url = [], {}
    pat = r'<tr data-filter="%s">(.*?)</tr>' % re.escape(filt)
    for row in re.findall(pat, page, re.S):
        m = re.search(r'<a href="([^"]+)">(.*?)</a>', row, re.S)
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if not m or len(tds) < 3:
            continue
        title = clean(m.group(2))
        if not title or _HALL_EXCLUDE_TITLE.search(title):
            continue
        if "大会" in title and not re.search(
                r"コンサート|演奏会|音楽会|ライブ|LIVE|ミュージカル|リサイタル",
                title):
            continue
        price = clean(tds[2])
        if not re.search(r"円|無料|有料", price):
            price = ""
        if len(price) > 120:
            price = price[:120].rstrip() + "…"
        url = urllib.parse.urljoin("https://www.tcf.or.jp/", m.group(1))
        date_txt = clean(tds[0])
        for y, mo, d in re.findall(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_txt):
            ev = make_event(
                venue, f"{int(y):04d}-{int(mo):02d}-{int(d):02d}", title,
                price=price, url=url, source=venue["schedule_url"],
                status_src=title)
            if ev:
                events.append(ev)
                by_url.setdefault(url, []).append(ev)
    if by_url:
        _enrich_tcf(by_url, fetcher)
    return events, []


_MITO_HALL_SPACES = {"グロービスホール", "ユードムホール", "小ホール"}


def _mito_space_ok(space_text):
    """会場欄が公演ホール（グロービス/ユードム/小ホール）だけで
    構成される催しだけを通す。会議室・展示室等が混ざる催しは落とす。"""
    parts = [p.strip() for p in re.split(r"[、・,\s]+", space_text) if p.strip()]
    if not parts:
        return False
    for p in parts:
        p = re.sub(r"（(大|中)ホール）$", "", p)
        if p not in _MITO_HALL_SPACES:
            return False
    return True


def _mito_dates(date_text, tab_y, tab_m):
    """水戸市民会館カレンダーの開催日テキストから日付リストを作る。

    対応形式: "10月2日(金)" / "10月10日(土)-12日(月・祝)" /
    "10月30日(金)～11月1日(日)" / "12月26日(土)・27日(日)"。
    年はタブの年月から付与する（トークンの月 < タブの月 なら翌年）。
    """
    toks = []
    for m in re.finditer(r"(\d{1,2})月(\d{1,2})日|(\d{1,2})日", date_text):
        if m.group(1):
            toks.append((m.start(), int(m.group(1)), int(m.group(2))))
        else:
            toks.append((m.start(), None, int(m.group(3))))
    if not toks:
        return []
    dates = []
    cur_month = None
    for _, mo, d in toks:
        if mo is None:
            mo = cur_month
            if mo is None:
                continue
            if dates and d < dates[-1].day:
                mo += 1
                if mo == 13:
                    mo = 1
        cur_month = mo
        y = tab_y + (1 if mo < tab_m else 0)
        try:
            dates.append(datetime(y, mo, d).date())
        except ValueError:
            continue
    if len(dates) >= 2:
        between = date_text[toks[0][0]:toks[-1][0]]
        if re.search(r"[～~\-−]", between):
            out, cur = [], dates[0]
            while cur <= dates[-1] and len(out) <= 10:
                out.append(cur)
                cur += timedelta(days=1)
            return out
    return dates


def adapter_mito_civic(venue, fetcher):
    """水戸市民会館の月タブ DL カレンダーを読む。

    当月タブは施設全体の暦（講座・健康相談・展示会まで含む）だが、
    会場が公演ホールのみの催しに絞り、タイトルでも非公演を除外する。
    翌月以降のタブは主催公演中心でほぼそのまま使える。
    特設詳細ページ（event/event_YYYYMMDDNN.html）がトップや一覧から
    リンクされている場合は、日付で候補を引き、タイトル一致を確認
    できたものだけ公演 URL として採用し、料金・時刻を補完する。
    """
    ok, raw = fetcher.fetch(venue["schedule_url"])
    if not ok:
        return [], [raw]
    # 特設ページ候補（日付→URL）。リンクはトップページ側にある
    # （/event/ には無い）。昨年の同名ページ等も候補に入るが、
    # 採用はタイトル照合を通過したものだけ
    detail_by_date = {}
    ok_top, top = fetcher.fetch(venue["site_url"])
    for src_html in (raw, top if ok_top else ""):
        for href, y, mo, d in re.findall(
                r'href="[^"]*?(event/event_(\d{4})(\d{2})(\d{2})\d{2}\.html)"',
                src_html):
            key = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
            # href はトップページ基準の "event/event_*.html" 形式。
            # ベースはサイトルートにする（/event/ を基点にすると
            # event/event/ と二重になる）
            url = urllib.parse.urljoin("https://www.mito-hall.jp/", href)
            detail_by_date.setdefault(key, [])
            if url not in detail_by_date[key]:
                detail_by_date[key].append(url)
    page = re.sub(r"<!--.*?-->", "", raw, flags=re.S)  # 古い内容がコメントに残る
    tabs = {}
    for m in re.finditer(
            r'for="month(\d+)">\s*(\d{4})年<BR[^>]*><SPAN[^>]*>(\d{1,2})', page):
        tabs[int(m.group(1))] = (int(m.group(2)), int(m.group(3)))
    events = []
    tab_marks = list(re.finditer(
        r'class="tab_content" id="month(\d+)_item"', page))
    for i, tcm in enumerate(tab_marks):
        idx = int(tcm.group(1))
        if idx not in tabs:
            continue
        tab_y, tab_m = tabs[idx]
        seg_end = (tab_marks[i + 1].start() if i + 1 < len(tab_marks)
                   else len(page))
        block = page[tcm.start():seg_end]
        for dl in re.findall(r"<DL>(.*?)</DL>", block, re.S):
            fields = {}
            for dt_, dd_ in re.findall(
                    r"<DT[^>]*>(.*?)</DT>\s*<DD[^>]*>(.*?)</DD>", dl, re.S):
                fields[clean(dt_)] = dd_
            title_m = re.search(r'class="title[^"]*"[^>]*>(.*?)</LI>', dl, re.S)
            title = clean(title_m.group(1)) if title_m else ""
            if not title:
                tm = re.search(r"催事名.*?<span>(.*?)</span>", clean(dl))
                title = tm.group(1) if tm else ""
            if not title or _HALL_EXCLUDE_TITLE.search(title):
                continue
            space = clean(fields.get("会場", ""))
            if not _mito_space_ok(space):
                continue
            price = clean(fields.get("チケット等", ""))
            if price and not re.search(r"円|無料", price):
                price = ""
            if len(price) > 120:
                price = price[:120].rstrip() + "…"
            for dt_ in _mito_dates(clean(fields.get("開催日", "")), tab_y, tab_m):
                ev = make_event(
                    venue, dt_.strftime("%Y-%m-%d"), title, price=price,
                    url=venue["site_url"], source=venue["schedule_url"],
                    status_src=title)
                if ev:
                    events.append(ev)
    # 特設ページで URL・料金・時刻を補完
    by_date = {}
    for ev in events:
        by_date.setdefault(ev["date"], []).append(ev)
    matched = 0
    for date_str, evs in by_date.items():
        for cand in detail_by_date.get(date_str, []):
            okd, det = fetcher.fetch(cand)
            if not okd:
                continue
            txt = clean(det)
            # 特設ページはチラシ画像主体で、公演名は冒頭の HTML コメント
            # （<!--日付_公演名_特設ページ-->）にしか無いことが多いため、
            # 照合はコメントを含む生 HTML に対して行う
            flat = re.sub(r"\s+", "", det)
            pm = re.search(r"料金[：:]\s*([^/。]{0,80}?円)", txt)
            sm = re.search(r"開演\s*(\d{1,2}:\d{2})", txt)
            om = re.search(r"開場\s*(\d{1,2}:\d{2})", txt)
            for ev in evs:
                key = re.sub(r"\s+", "", ev["title"])[:10]
                if key and key in flat:
                    ev["url"] = cand
                    matched += 1
                    if pm and not ev["price"]:
                        ev["price"] = pm.group(1).strip()
                    if sm and not ev["start"]:
                        ev["start"] = sm.group(1)
                    if om and not ev["open"]:
                        ev["open"] = om.group(1)
    if matched:
        print(f"    [enrich] mito detail pages matched={matched}")
    return events, []


_HIROSAWA_KEEP = {"コンサート", "ミュージカル", "茨城県芸術祭"}


def adapter_hirosawa(venue, fetcher):
    """ザ・ヒロサワ・シティ会館の「これからのイベント」を読む。

    /event/ の schedule_pickup 節（展示室・ギャラリーの節より前）から
    公演カテゴリ（コンサート/ミュージカル/茨城県芸術祭）の記事だけを
    取り、詳細ページの開催日・時間・料金・出演者で確定させる。
    一覧の赤字 span（発売日などの販売注記）はタイトルから除く。
    """
    ok, page = fetcher.fetch(venue["schedule_url"])
    if not ok:
        return [], [page]
    start = page.find('id="schedule_pickup"')
    if start < 0:
        return [], ["schedule_pickup section not found"]
    end = page.find("一般展示室", start)
    seg = page[start:end if end > start else len(page)]
    events = []
    for item in re.findall(r"<ARTICLE>(.*?)</ARTICLE>", seg, re.S):
        cm = re.search(r'class="category">(.*?)</LI>', item, re.S)
        if not cm:
            continue
        cat = clean(cm.group(1)).replace("－", "ー")
        if cat not in _HIROSAWA_KEEP:
            continue
        hm = re.search(r"<H4>(.*?)</H4>", item, re.S)
        if not hm:
            continue
        h4 = re.sub(r'<span[^>]*style="[^"]*color[^"]*"[^>]*>.*?</span>',
                    "", hm.group(1), flags=re.S)
        title = clean(h4)
        lm = re.search(r'href="(\d{8}\.html)"', item)
        if not title:
            continue
        detail_url = (urllib.parse.urljoin(venue["schedule_url"], lm.group(1))
                      if lm else "")
        date_str = open_t = start_t = price = artists = ""
        if detail_url:
            okd, det = fetcher.fetch(detail_url)
            if okd:
                txt = clean(det)
                dm = re.search(r"開催日\s*(\d{4})年(\d{1,2})月(\d{1,2})日", txt)
                if dm:
                    date_str = (f"{int(dm.group(1)):04d}-{int(dm.group(2)):02d}"
                                f"-{int(dm.group(3)):02d}")
                tm = re.search(r"時間\s*(.*?)\s*会場", txt)
                tseg = tm.group(1) if tm else txt
                sm = re.search(r"開演\s*(\d{1,2}:\d{2})", tseg)
                om = re.search(r"開場\s*(\d{1,2}:\d{2})", tseg)
                if sm:
                    start_t = sm.group(1)
                if om:
                    open_t = om.group(1)
                pm = re.search(
                    r"料金\s*(.*?)\s*(?:チケット発売日|チケットのお求め|お問合せ|"
                    r"席種|発売日|プレイガイド|出演)",
                    txt)
                if pm and re.search(r"円|￥|¥|無料", pm.group(1)):
                    price = pm.group(1).strip(" /")[:160]
                am = re.search(
                    r"出演者?\s*(.*?)\s*(?:チケット発売日|チケットのお求め|お問合せ)",
                    txt)
                if am:
                    artists = am.group(1).strip(" /")[:140]
        if not date_str:
            dm2 = re.search(r'class="date">\s*(\d{4})/(\d{1,2})/(\d{1,2})',
                            item)
            if dm2:
                date_str = (f"{int(dm2.group(1)):04d}-{int(dm2.group(2)):02d}"
                            f"-{int(dm2.group(3)):02d}")
            elif lm:
                fn = lm.group(1)
                date_str = f"{fn[:4]}-{fn[4:6]}-{fn[6:8]}"
        if not date_str:
            continue
        ev = make_event(
            venue, date_str, title, artists=artists, open_t=open_t,
            start_t=start_t, price=price,
            url=detail_url or venue["site_url"],
            source=venue["schedule_url"],
            status_src=f"{title} {price}")
        if ev:
            events.append(ev)
    return events, []


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
    "club251": adapter_club251,
    "toos_calabash": adapter_toos_calabash,
    "era": adapter_era,
    "shimokita_ticket": adapter_shimokita_ticket,
    "mosaic": adapter_mosaic,
    "chikamatsu": adapter_chikamatsu,
    "fad": adapter_fad,
    "citta": adapter_citta,
    "bbstreet": adapter_bbstreet,
    "tcf": adapter_tcf,
    "mito_civic": adapter_mito_civic,
    "hirosawa": adapter_hirosawa,
    # "loft_project": 未実装（全パス 403 メンテナンス表示のため保留）
}


# ---------------------------------------------------------------- alerts

# 件数減少アラートの閾値。前回（like-for-like）がこの件数未満の会場は
# 減少判定の対象にしない（小さい会場の自然な増減で誤報しないため）。
ALERT_DROP_RATIO = 0.40
ALERT_MIN_PREV = 5


def load_previous(state_path, out_path, today_str):
    """前回実行の件数を読み込む。

    戻り値: (raw_counts, like_counts)
      raw_counts:  前回 state.json の会場別件数 {venue_id: count}
      like_counts: 前回 events.json のうち「today_str 以降の公演」だけを
                   数えた会場別件数。events.json が読めない場合は None
                   （呼び出し側で raw_counts にフォールバックする）。
    like-for-like で数える理由: ほとんどの会場は当月+翌月の2ヶ月分を
    返すため、月替わりでは前月分が一斉に失効するが、同時に翌月分が
    入って生件数はほぼ横ばいになる。生件数同士の比較でも概ね問題ないが、
    「前回ファイルに含まれる今日以降の公演」と「今回の今日以降の公演」を
    同じ窓で比べることで、月替わりの失効分を比較から完全に外せる。
    当月分しか無い会場（MOSAiC 等）は、月末が近づくと窓側の前回件数が
    自然に小さくなり、ALERT_MIN_PREV 未満になって減少判定が自動的に
    外れる（月替わり直後の減少は検出できない、という既知の限界）。
    """
    raw = {}
    try:
        prev_state = json.loads(Path(state_path).read_text(encoding="utf-8"))
        for vid, info in prev_state.get("venues", {}).items():
            if isinstance(info, dict) and isinstance(info.get("count"), int):
                raw[vid] = info["count"]
    except Exception:  # noqa: BLE001 - 前回が無い/壊れている場合は空で続行
        raw = {}
    like = None
    try:
        prev_events = json.loads(Path(out_path).read_text(encoding="utf-8"))
        like = {}
        for ev in prev_events.get("events", []):
            if ev.get("date", "") >= today_str:
                vid = ev.get("venue_id", "")
                like[vid] = like.get(vid, 0) + 1
    except Exception:  # noqa: BLE001
        like = None
    return raw, like


def build_alerts(active_ids, new_state_venues, new_like, prev_raw, prev_like,
                 names, month_roll_ids, today_str):
    """今回の結果と前回を比較してアラートのリストを作る。

    アラート条件（active 会場のみ）:
      - fetch_failed: 取得が失敗した（status == "fail"）
      - zero_events:  取得は成功扱いだが 0 件だった
      - count_drop:   like-for-like 件数が前回比で ALERT_DROP_RATIO 超
                      減少した（前回が ALERT_MIN_PREV 未満なら対象外。
                      前回 events.json が無い場合は state の生件数で代用し、
                      その旨を message に明記する）
    部分的な警告（翌月ページ未公開など、件数が残っているもの）は単独では
    アラートにしない。実害が出れば count_drop が拾う。
    各アラートは {venue, venue_name, kind, prev, new, message}。
    prev/new は比較に使った件数（count_drop では窓側の件数、それ以外は
    state の件数）。
    """
    alerts = []
    for vid in active_ids:
        info = new_state_venues.get(vid, {})
        new_total = info.get("count", 0)
        name = names.get(vid, vid)
        roll_note = (" (month-rolling venue; like-for-like window used)"
                     if vid in month_roll_ids else "")
        if info.get("status") == "fail":
            alerts.append({
                "venue": vid, "venue_name": name, "kind": "fetch_failed",
                "prev": prev_raw.get(vid, 0), "new": 0,
                "message": f"fetch failed: {info.get('error', '')[:200]}"})
            continue
        if info.get("status") != "ok":
            continue
        if new_total == 0:
            alerts.append({
                "venue": vid, "venue_name": name, "kind": "zero_events",
                "prev": prev_raw.get(vid, 0), "new": 0,
                "message": ("returned 0 events "
                            f"(previous run: {prev_raw.get(vid, 0)})"
                            + roll_note)})
            continue
        if prev_like is not None:
            prev_cmp = prev_like.get(vid)
            new_cmp = new_like.get(vid, 0)
            basis = f"dates >= {today_str}"
        else:
            prev_cmp = prev_raw.get(vid)
            new_cmp = new_total
            basis = "raw totals (previous events.json unavailable)"
        if prev_cmp is None or prev_cmp < ALERT_MIN_PREV:
            continue  # 前回実績が無い/小さい会場は減少判定をしない
        if new_cmp < prev_cmp * (1 - ALERT_DROP_RATIO):
            drop_pct = (1 - new_cmp / prev_cmp) * 100 if prev_cmp else 0
            alerts.append({
                "venue": vid, "venue_name": name, "kind": "count_drop",
                "prev": prev_cmp, "new": new_cmp,
                "message": (f"count dropped {prev_cmp} -> {new_cmp} "
                            f"(-{drop_pct:.0f}%, like-for-like: {basis})"
                            + roll_note)})
    return alerts


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
    today_str = now_jst().strftime("%Y-%m-%d")
    prev_raw, prev_like = load_previous(args.state, args.out, today_str)
    active_ids = [v["id"] for v in venues if v.get("status") == "active"]
    names = {v["id"]: v["name"] for v in venues}
    month_roll_ids = {v["id"] for v in venues if v.get("month_roll")}
    new_like = {}
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
        kept_like = 0
        for ev in events:
            key = (ev["venue_id"], ev["date"], ev["title"], ev["url"])
            if key in seen:
                continue
            seen.add(key)
            all_events.append(ev)
            kept += 1
            if ev["date"] >= today_str:
                kept_like += 1
        new_like[vid] = kept_like
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
    from collections import Counter
    sc = Counter(e["status"] for e in all_events if e.get("status"))
    gc = Counter(g for e in all_events for g in e.get("genres", []))
    print(f"status marks: {dict(sc)}")
    print(f"genre tags: {dict(gc)} "
          f"untagged={sum(1 for e in all_events if not e.get('genres'))}")
    state["total_events"] = len(all_events)
    alerts = build_alerts(active_ids, state["venues"], new_like,
                          prev_raw, prev_like, names, month_roll_ids,
                          today_str)
    state["alerts"] = alerts
    if alerts:
        print(f"=== ALERTS: {len(alerts)} ===")
        for a in alerts:
            print(f"  [{a['kind']}] {a['venue_name']} ({a['venue']}): "
                  f"prev={a['prev']} new={a['new']} - {a['message']}")
    else:
        print("alerts: none")
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
