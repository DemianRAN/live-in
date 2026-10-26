# 関東ライブまとめ (live-in)

関東のライブハウス＋小ホールの公演情報を、各会場の**公式サイトだけ**から毎日自動収集して一覧表示する静的サイト。

- リポジトリ: DemianRAN/live-in
- 公開先（予定）: https://demianran.github.io/live-in/
- 更新: GitHub Actions で毎日 07:00 JST に収集・再生成・コミット

## ソース方針

- 収集元は会場の公式サイトのみ。チケットプラットフォーム（e+ / チケットぴあ / ローソンチケット等）は**収集対象にせず**、必要ならリンク先としてのみ扱う。
- 掲載するのは公演の事実情報（日付・開場/開演・タイトル・出演者・料金）と公式詳細ページへのリンクのみ。紹介文や画像は転載しない。
- 1会場の取得失敗で全体は止めない。失敗は `data/state.json` に記録される。

## 現在の対象会場

| 会場 | 都県 | 状態 |
|---|---|---|
| 渋谷 WWW | 東京都 | 稼働中 |
| 渋谷 WWW X | 東京都 | 稼働中 |
| 渋谷 CLUB QUATTRO | 東京都 | 稼働中 |
| 恵比寿 LIQUIDROOM | 東京都 | 稼働中 |
| つくば PARKDINER | 茨城県 | 稼働中（当月分のみ） |
| HEAVEN'S ROCK 熊谷 VJ-1 | 埼玉県 | 稼働中 |
| HEAVEN'S ROCK さいたま新都心 VJ-3 | 埼玉県 | 稼働中 |
| HEAVEN'S ROCK 宇都宮 VJ-2 | 栃木県 | 稼働中 |
| HEAVEN'S ROCK 宇都宮 VJ-4 | 栃木県 | 稼働中 |
| 横浜 BAYSIS | 神奈川県 | 稼働中 |
| 柏 PALOOZA | 千葉県 | 稼働中 |
| 水戸 LIGHT HOUSE | 茨城県 | 稼働中 |
| 千葉 LOOK | 千葉県 | 稼働中（当月分のみ） |
| 下北沢 CLUB251 | 東京都 | 稼働中 |
| 下北沢 THREE | 東京都 | 稼働中 |
| 下北沢 BASEMENTBAR | 東京都 | 稼働中 |
| 下北沢 ERA | 東京都 | 稼働中 |
| 下北沢 MOSAiC | 東京都 | 稼働中（当月分のみ） |
| 下北沢 Laguna | 東京都 | 稼働中 |
| 下北沢 DaisyBar | 東京都 | 稼働中 |
| 下北沢 近松 | 東京都 | 稼働中 |
| F.A.D YOKOHAMA | 神奈川県 | 稼働中 |
| 川崎 CLUB CITTA' | 神奈川県 | 稼働中 |
| 横浜 B.B.STREET | 神奈川県 | 稼働中 |
| 新宿 LOFT | 東京都 | 保留（公式サイトが 403 を返すため） |
| 下北沢 SHELTER | 東京都 | 保留（同上） |
| 下北沢 ReG | 東京都 | 保留（公式サイトが特定できないため） |

正確な一覧と各会場のメモは `collector/venues.json` が正。

## 構成（fishing-catch プロジェクトと同型）

```
collector/
  venues.json   会場レジストリ（id・名前・都県・公式URL・スケジュールURL・アダプタ・状態）
  collect.py    収集（標準ライブラリのみ）→ data/events.json, data/state.json
  build.py      生成 → web/index.html（データ内包の単体HTML）, web/events.json
data/           収集結果（events.json / state.json）
web/            GitHub Pages に公開する生成物
.github/workflows/
  collect.yml   毎日 07:00 JST に collect + build + commit
  pages.yml     web/ の変更で Pages へデプロイ
```

## ローカル実行

```bash
python3 collector/collect.py   # 収集
python3 collector/build.py     # サイト生成
# web/index.html をブラウザで開く
```

Python 3 の標準ライブラリのみで動作する（pip install 不要）。

## 会場の追加方法

1. `collector/venues.json` に会場を追加する（`id`, `name`, `pref`, `area`, `site_url`, `schedule_url`, `adapter`, `status`, `note`）。
2. 既存アダプタで済む場合は `adapter` に既存の名前を指定する。新しいサイト構造の場合は `collector/collect.py` に `adapter_<name>` 関数を実装し、`ADAPTERS` に登録する。
   - アダプタは `(venue, fetcher)` を受け取り、`(events, errors)` を返す。`fetcher.fetch(url)` は `(ok, text_or_reason)` を返し、同一URLはキャッシュされる。
   - 日付は可能な限りページ側の明示情報（URLの YYYYMM、`data-event-date`、詳細URL末尾の日付）から確定すること。本文中の月日だけから推測する場合は「対象月 < 現在月なら翌年」のルールを明記する。
3. `python3 collector/collect.py` を実行し、`data/state.json` で対象会場が `ok` になり、件数と内容（タイトル・日付・曜日）が正しいことを確認する。
4. `python3 collector/build.py` でサイトを再生成する。

取得できない会場は無理にデータを捏造せず、`status: "pending"` と理由を `note` に書いて登録する。

## 備考

- PARKDINER のスケジュールページは当月分のみ表示される（月送りが JS のため）。翌月分は月が替わってから自動で収集される。
- WWW / WWW X の一覧ページには料金が載っていないため、料金は空欄になる（詳細ページにはある）。料金が空でも公演自体は掲載する。
- `.github/workflows/` 配下のファイルは、環境によっては GitHub App の権限でプッシュできない場合がある（fishing-catch では手動追加が必要だった）。その場合は GitHub の Web UI から同内容で追加すること。
