# 関東 Live House + 小厅汇总站 — MVP 调研 (2026-10-26)

决策：先做关东 Live House + 小厅，不做全日本/大型票务汇总。数据源只用会场官网，票务平台只放链接。

## 实测可抓性 (2026-10-26, 静态抓取测试)

### A 类：一个适配器覆盖多家（系统已确认，直抓待突破）
- LOFT PROJECT (loft-prj.co.jp/schedule/<venue>/): 系统结构经搜索索引确认——日程页含完整
  schedule（日期/OPEN-START/出演/票价），同系统还有 LOFT HEAVEN、LOFT PLUS ONE、
  FLOWERS LOFT 等，一套解析吃多家。但 2026-10-26 用普通脚本 UA 直抓新宿LOFT、
  下北沢SHELTER 均返回 403 Forbidden，需换请求头/浏览器方式再验，不能算已抓通。
- HEAVEN'S ROCK (heavensrock.com/<venue>/): 熊谷 VJ-1、さいたま新都心 VJ-3 为同站分页面（搜索确认），未直抓验证。

### B 类：独立站，静态 HTML，实测抓通 (2026-10-26 脚本实测)
- 渋谷 WWW (www-shibuya.jp/schedule/) 200，94,877 bytes，含日程
- 渋谷 CLUB QUATTRO (club-quattro.com/shibuya/schedule/) 200，183,283 bytes，含日程
- 恵比寿 LIQUIDROOM (liquidroom.net/schedule) 200，82,265 bytes，含日程（日程页路径已确认）

### C 类：情况已更新 / 待专案
- つくば PARKDINER (parkdiner.jp): 实测 200，56,696 bytes，含日程信息——并非 JS 空壳，
  可能可抓，需做解析验证（此前“仅 2.9KB”的说法有误，已纠正）
- 水戸 LIGHT HOUSE (mitolighthouse.com): 域名可达，/schedule/ 返回 404，是日程页路径不对，待找正确路径
- 千葉 LOOK (chibalook.com): 实测 200（首页 6,706 bytes，含日程提示），日程页路径待确认
- 横浜 BAYSIS、柏 PALOOZA: 实测连接被服务器断开 (RemoteDisconnected)，未验证，需换方式重试

### D 类：小厅（市政ホール）— 结构最杂，建议二期
- つくば ノバホール: 月度催物案内是 PDF，解析成本高
- 水戸市民会館: 逐条お知らせ文章式发布，无统一日程表
- 结论：小厅先只收有 HTML 日程表的（如つくばカピオ等再核），PDF/文章式二期处理

## MVP 范围建议 (v1)
- 会场：约 15–20 家，以 A+B 类为主，东京为核心 + 横浜/埼玉/千葉/茨城能抓通的先收
- 字段：日期、OPEN/START、标题、出演者、票价、会场、都县、官网详情链接
- 筛选：日期（本周/周末）、都县、会场、关键词搜索；首页按日期升序
- 技术复用钓鱼站：Python stdlib 采集器 + venues.json 注册表 + 静态单页 + GitHub Actions 每日跑 + GitHub Pages
- 不做：售罄实时状态、票务平台抓取、图片转载（只存文字事实+链接）

## MVP 构建状态 (2026-10-26 本地完成，未推送)
- [x] 用户确认范围并建仓 DemianRAN/live-in（推送待用户/主代理另行处理；workflows 文件可能需手动添加）
- [x] 采集器 + 建站脚本完成并实跑：241 条采集（2026-10-01〜11-30），其中今日起 134 条进首页
  - WWW 55 / WWW X 56 / QUATTRO 58 / LIQUIDROOM 59 / PARKDINER 13（当月分，今日起 2 条）
- [x] PARKDINER 解析验证：/schedule/ 页（当月分）可解析日期/open-start/料金（excerpt 截断时料金不完整）
- [ ] LOFT 家族：浏览器请求头重试仍 403，已登记 pending（venues.json），不造数据
- [ ] 二期：找正确日程页路径 LIGHT HOUSE、千葉LOOK；重试 BAYSIS、柏PALOOZA；小厅 HTML 日程表

## 扩充结果 (2026-10-26 下午，本地实跑验证，未推送)
总量 241 → **494 条**（+253），今日起 134 → **269 条**。既存 5 家件数完全不变（无回归）。
新增 8 家，全部逐家抽查 2 条与官网原文核对一致：

- [x] HEAVEN'S ROCK 4 家（同一适配器 heavensrock）：熊谷 VJ-1 22 / さいたま新都心 VJ-3 30 /
  宇都宮 VJ-2 25 / 宇都宮 VJ-4 25。月页 /<slug>/schedule/YYYYMM。
  注意：月页会以 **HTTP 404 返回正确内容**（WP 主题的毛病），适配器用 accept_404 取得后
  再验证月标题一致才采用。列表页不带票价（详情页才有），price 为空属源站限制。
- [x] 横浜 BAYSIS 63：真官网是 **yokohamabaysis.com**（schedule.php?mt=YYYY.MM）。
  baysis.jp 从本网络访问是域名停放页（iframe 停放服务），勿用；旧调查的「551KB」亦源于此误判。
- [x] 柏 PALOOZA 32：官网 kashiwa-palooza.com（https 会断连，用 http），
  pc/Schedule/YYYYMM.html 手风琴结构，标签式+自由式两种格式都已处理。
- [x] 水戸 LIGHT HOUSE 34：首页是 splash（enter → pctop.htm → top_sche.html），
  月页为 sche{YY}{月码}.html（月码按年有表记差异，如 11 月 = nor；适配器按候选码试取并验证年月）。
- [x] 千葉 LOOK 22：schedule/index.html 表格页（月标题行/日标题行/[标题]内容行/CHARGE 行），仅当月分。
- [ ] LOFT 家族仍 blocked：本轮把能试的都试了——UA、浏览器头、cookie 会话+Referer、
  HTTP/1.1 / HTTP/2、非 www 主机、/feed/、/wp-json/、robots.txt、sitemap.xml——
  全部返回同一张 1,973 字节的「システムメンテナンスのお知らせ」403 页。
  即站点对本网络一律返回维护页。维持 pending；若以后从日本国内网络/浏览器能打开，再议适配器。
- 已知限制：LOOK 只有 OPEN 无 START 的公演较多（源站写法）；BAYSIS 出演者里的换行会变成「/」；
  HR/PALOOZA 个别自由格式公演的字段完整度随源站写法浮动。

## 扩充结果・第2批 (2026-10-26 晚，本地实跑验证，未推送)

总量 494 → **1062 条**（+568），今日起 269 → **606 条**。既存 13 家件数完全不变（无回归、无警告）。
新增 11 家全部逐家抽查 2 条与官网原文核对一致。全量収集の所要時間は約 11 分
（大半は toos.co.jp の詳細ページ取得：約 3 秒/件）。

### 下北沢集群（此前为零 → 8 家 459 条）
- [x] CLUB251 46：月页 /schedule/?mo=M&yr=YYYY（Events Manager 形式）。月页会混入
  前月/次月的端数日（eventful-pre/post），只保留当月・翌月分；同一公演在两个月页
  重复出现 5 条，靠主循环去重（原始 51 → 46）。
- [x] THREE 62 / BASEMENTBAR 63：同一适配器 toos_calabash（toos.co.jp 共通
  calabash 系统）。月历（?cb_month=YYYY-MM）→ 日别页（多公演日）→ 详细页解析。
  件数与官网日历自报的「公演X件」合计**完全一致**（THREE 33+29=62、
  BASEMENTBAR 34+29=63）。两店合同公演按官网日历的登载方式在两家各登一条。
- [x] ERA 63：月归档 schedule_cat/YYYY-MM，time datetime 明示日期；
  [出演] 标签有无两种写法都已处理，ADV/DOOR 取自 detail-grid。
- [x] MOSAiC 21：schedule.html 表格页，仅当月分（无月页）。31 天中 21 天有公演
  （无 live_title 的休业/贷切日不登）。
- [x] Laguna 75 / DaisyBar 73：同一 WP 主题 → 同一适配器 shimokita_ticket，
  月页 /schedule/YYYY/M/。料金は前売/当日のみ採用（配信チケットは除外）。
- [x] 近松 56：月一覧 /schedule/YYYY/MM/ + 详细页（OPEN/START・ADV/DOOR・LINE UP）。
  详细页有两种时刻写法（"OPEN / START H:MM/H:MM" 与 "OPEN H:MM / START H:MM"）
  都已对应，最终 43/56 有时刻、54/56 有料金。注意：调查中途官网列表的 HTML
  属性顺序变过一版（一度全灭），解析侧已改成属性顺序不敏感。
  10/4「アスノポラリス＆ゼロカルpre.」是延期公演，详细页只有 INFORMATION
  通知、无时刻料金，按列表页原样登载。

### 横浜・川崎（+3 家 109 条）
- [x] F.A.D YOKOHAMA 36：公式 WP（/fad/）投稿一覧は公演日昇順、标题冒头的
  'YY.MM.DD が公演日。10/26〜11/30 **每天恰好 1 场、无缺日**。详细页补全后
  35/36 有时刻、33/36 有料金。踩坑：详细页 <title> 与正文 h1 同文，
  find 锚点一度落到 <head> 导致补全全灭，已改 rfind 锚到正文侧。
  标题里公演名与出演混排是官网写法，原样登载。
- [x] 川崎 CLUB CITTA' 36：/schedule?year=YYYY&month=Mon（月は英語略称）。
  当月分官网只显示「今日起」（源站仕様）。一覧に料金なし（詳細のみ）のため
  price 空栏（HEAVEN'S ROCK と同扱い）。
- [x] 横浜 B.B.STREET 37：月归档 /YYYY/MM/?cat=5 的卡片里日期・标题・
  OPEN/START・ADV/DOOR・出演一应俱全，一览即可完结。

### 未加入
- [ ] 下北沢 ReG：pending 登记。Web 搜索 + 下北沢门户 shimonite 都没找到
  官方网站，只有 TIGET 等的公演情报。按「只收官网」方针保留 pending
  （site_url 留空，页脚链接会是死链，属已知小瑕疵；找到官网再补）。
- FLOWERS LOFT：LOFT 家族（全パス 403），按既定方针跳过，未重复登记。

### 共通代码修正
- Fetcher：IncompleteRead（服务器中途截断）时自动重试 1 次。本批中途实跑时
  BAYSIS 10 月页被截断、一度掉到 33 条，靠此修正恢复 63 条。

### 已知限制（第2批）
- CLUB251 料金文字列含官网原样的多档票价（如优先票）；ERA 有官网占位条目
  （11/30「EVENT」TBA、10/27 PRIVATE RENTAL）原样登载；MOSAiC 仅当月分
  （月替自动跟进）；CITTA' 料金空栏（同上）。

### 第3批候选（东京缺口・只做了域名核实与可达性初测，未做适配器）
- 新宿 Marble：官网 shinjuku-marble.com，有 /schedule/（200、94KB，静态可取性高）
- 吉祥寺 WARP：官网 warp.rinky.info，有 /schedules/（200、73KB，同上）
- 新宿 Motion：官网 motion-web.jp，首页抓取被服务器断开（RemoteDisconnected，未验证，与 BAYSIS/PALOOZA 初期现象同类）
- 吉祥寺 SHUFFLE：官网 k-shuffle.com（200、33KB），首页未见 schedule 链接，路径待找
- 池袋 手刀 (Chop)：官网 chop-tokyo.info（200 但仅 2KB，像 frameset/跳转壳），日程页待找
- 高円寺 HIGH：本轮搜索未核实到官方域名（只搜到 Bandsintown 等二级来源）

## 数据质量批 (2026-10-26 夜，本地实跑验证，未推送)

总量 1062 → **1092 条**（+30，全部来自任务 3 的翌月分：PARKDINER +13、LOOK +17），
今日起 606 → **636 条**。其余 22 家件数与第 2 批完全一致（补完不增删条目）。
全量耗时约 **16 分**（补完增加约 5 分，低于 ~25 分上限，全范围实施、未做 upcoming 限定）。
字段完整度：料金 **72.0% → 93.8%**（765→1024）、OPEN **91.9% → 93.2%**（976→1018）、
START **91.2% → 91.1%**（969→995；绝对数 +26，百分比持平是因为新增 30 条
多为源站只写 OPEN 的 LOOK/PARKDINER 翌月分）。

### 任务 1/2：详细页补完（只取官网详情页，只补缺字段的条目）
- [x] WWW 料金 0→51/55、WWW X 0→47/56：详情页 dl（OPEN/START・ADV./DOOR）解析，
  料金は ADV./DOOR 欄を最初の ※ 注記手前まで採用。残りは詳細にも金額表記なし（未定等）。
- [x] HEAVEN'S ROCK ×4 料金 0→99/102（熊谷 20/22・さいたま 30/30・宇都宮 VJ-2 25/25・
  VJ-4 24/25）：详情页情報行「Open H:MM Start H:MM Adv … Door … Ticket …」から
  Adv/Door 段を抽出（※ドリンク代注記は除去、円表記は ¥ に正規化、多段料金はそのまま）。
  残り 3 件は詳細が「SOLD OUT / 未定」で金額なし——捏造せず空欄。
- [x] CLUB CITTA' 料金 0→33/36、OPEN 19→33、START 21→36（全件に START 揃った）：
  详情页冒頭の OPEN/START と「座種/料金」節を採用。
- 缺时刻的 117 条已逐家核对：能补的都补了（大半在 CITTA'）；WWW/HR/B.B.STREET 的
  详情页本身也只写 OPEN 或時刻なし的，按源站原样留空。B.B.STREET 详情确认无 START
  （卡片即全部信息），未加补完対象。

### 任务 3：PARKDINER / LOOK 翌月分 — 两家都有正规端点，已实装
- [x] PARKDINER 13→26（10月13＋11月13）：TCD DIVA 主题自带 AJAX
  （wp-admin/admin-ajax.php の `get_events_ajax`；nonce と URL は /schedule/ 页
  埋め込みの `event_ajax` オブジェクトから取得、応答の month_label を検証して採用）。
  実測：2026-11 分 13 件を当月分と同一形式で取得。詳細補完も併用。
- [x] 千葉 LOOK 22→39（10月22＋11月17）：index.html フッターからリンクされた
  先取り情報ページ `schedule/new.html`（同一表形式で 2026.11〜2027.06 掲載）から
  翌月分だけを採用（他会場と揃える）。
  付随修正：フッターのナビ行「ルックのホーム」が 10/31 の公演として混入していた
  バグと、前置き付き行（「学生限定イベント / [FASTLIVE] …」10/28）の脱落を修正
  （内容行は OPEN を含む行のみ採用、タイトル括弧は行途中からでも拾う）。
  10月分は 22 件のまま中身が正しくなった（−ゴミ1＋実公演1）。
  なお 10 月分の料金が 14/22 に見えるのは、公式ページ自体が 7 件「CHARGE 未定」のため。

### スポットチェック（詳細ページ原文と一致を確認）
- WWW 10/28 Yuma Koda（schedule/020047.php）：OPEN/START 18:00/19:00、
  ADV./DOOR「一般：¥4,500（税込 / オールスタンディング / ドリンク代別） / U-22：¥3,500…」
- HEAVEN'S ROCK さいたま 10/31 BabyKingdom：情報行「Open 16:30 Start 17:00
  Adv スタンディング ¥5,500 ※ドリンク代別 Door スタンディング ¥6,000 ※ドリンク代別」
- CLUB CITTA' 10/26 松山あおい（schedule/1770）：冒頭「OPEN 17:00 START 18:30」、
  座種/料金の段位表記（玄人 10,000円〜初心者 2,000円＋当日券）

### 備考
- 初回の単体テスト時と本収集で WWW X の補完件数が変動（54→47）したが、取得失敗は
  0 件で、本収集 2 回と単体再実行は 47 で完全一致。会場側の日内更新と判断し、
  再現性のある本収集分を正式データとした。
- 次批（機能）：ジャンルタグ、.ics 导出、完売标记（源站明記時のみ）。

## 機能批 (2026-10-26 夜，本地实跑验证，未推送)

件数不変：合計 **1092 条** / 今日起 **636 条**（会場別件数も従来どおり）。
※初回の全量収集は実行環境の再起動＋ネットワーク断（Connection refused）が
途中で発生し 276 条まで落ちたため、復旧後に再収集して 1092 条を確認した。
再収集時にもう1回回し、状態マークの誤検出を潰してから正式データとした。

### 1. 状態マーク（完売・中止・延期）
- [x] `status` フィールド（sold_out / cancelled / postponed / ""）を collect.py の
  `detect_status` で付与。入力は公演自身の一覧セグメント／詳細本文のみ。
- [x] 誤検出対策（実例で確認して潰した）:
  - 詳細ページ定型文の払い戻し注記（「※公演中止の場合を除き払い戻し…」等）は
    区間単位で除去してから判定（HR・WWW で実発生）
  - 「前売り完売の場合は当日券なし」等の条件文は状態とみなさない（CITTA' で実発生）
  - 「SOLD OUT 間近」は未完売として除外
  - WWW 詳細ページは過去公演一覧に他公演の「公演延期」が混ざるため、状態判定は
    料金欄＋タイトルだけに限定。CITTA' も料金節＋タイトルだけに限定
  - CITTA' の一覧セグメントは次のマッチまで他公演を含むため、状態判定は
    自公演の txt_wrap 本文＋タイトルだけに限定（他公演の THANK YOU SOLD OUT が
    混入する実例を確認）
- [x] UI：カードにバッジ（SOLD OUT 赤／公演中止 暗色＋カード減光／延期 橙）、
  「完売・中止を隠す」チェックで sold_out と cancelled を非表示にできる。
- 件数と実例は末尾の検証結果に記載。

### 2. ジャンルタグ
- [x] `genres` フィールドを collect.py の `GENRE_RULES`（キーワード規則、
  タイトル＋出演者のみ・複数可・手がかりなしは無タグ）で付与。規則表は README に明記。
- [x] UI：ジャンル chips で絞り込み、カードにタグ表示。
- 分布は末尾の検証結果に記載（無タグ率が高いのは「推測で埋めない」方針どおり）。

### 3. カレンダー書き出し (.ics)
- [x] 各カードに「カレンダーに追加 (.ics)」ボタン（ブラウザ側生成・単体公演）。
  一覧上部に「表示中を .ics で書き出す」ボタン（現在の絞り込み結果を一括）。
- [x] 仕様：DTSTART は START（無ければ OPEN）、DTEND は +2時間（終了時刻は
  公式に無いため）、時刻なしは終日（VALUE=DATE、DTEND は翌日）。
  時刻は JST フローティング表記。SUMMARY=タイトル、LOCATION=会場名（都県・
  エリア）、DESCRIPTION=出演・料金・公式URL、UID=会場ID＋日付＋タイトル等の
  ハッシュ（安定）。中止公演は STATUS:CANCELLED。
- [x] 検証：生成済み index.html から実際の ICS 関数を抽出して全公演分を生成し、
  パースし直して必須項目・UID 一意性・DTSTART 形式を確認（結果は末尾）。

### 検証結果（機能批・最終収集分）
- 状態マーク：全 1092 件中 sold_out **56**（今日起 24）、postponed **4**（今日起 1）、
  cancelled **0**。postponed の4件は全件原典確認済み（近松 10/4 延期公演＝既知事例、
  WWW X 10/10「【振替】Ivy to Fraudulent Game」、LIQUIDROOM 10/13「〈振替公演〉Sukekiyo」、
  CITTA' 10/31「【公演延期】THE MODS」）。
  cancelled が 0 件なのは、候補だった2件を原文確認した結果、どちらも公演自体の中止では
  なかったため：BAYSIS 10/22 は配信（ツイキャス）だけの中止で会場公演は開催、
  DaisyBar 10/24 は出演者変更の上で「変更して開催」。この2パターン
  （配信のみ中止／変更して開催）は検出側でも明示的に除外した。
  sold_out の原文例：WWW X 10/1 Cloudy 公演の料金欄「…（税込）SOLD OUT」、
  HEAVEN'S ROCK 宇都宮 10/3 aoen 詳細「Ticket Thank you,SOLD OUT!!」、
  LIQUIDROOM 10/31「¥6,000（税込）SOLD OUT」。
  既知の限界：券種限定の完売表記でも sold_out が付く場合がある（最終確認は公式へ）。
- ジャンル分布（今日起 636 件）：ロック/バンド 45、DJ/クラブ 14、
  アコースティック/弾き語り 10、アイドル 2、クラシック 2、ジャズ 1
  （延べ 74 タグ・重複あり）。無タグ **571 件（89.8%）**——タイトル＋出演者に
  ジャンル語が含まれない公演が大半で、方針どおり推測では埋めていない。
  トーク/お笑い・ヒップホップは今回の対象会場の文字列には現れなかった（0件）。
- ICS 検証：生成済み index.html の実際の関数を抽出し 636 件全件を VEVENT 化 →
  パースし直して必須項目（UID/DTSTAMP/DTSTART/DTEND/SUMMARY/LOCATION/
  DESCRIPTION）・UID 一意性（636/636）・DTSTART 形式を全件確認、問題なし。
  この検証で時刻欄が "TBA" の公演（46件が終日扱い）で DTSTART が壊れる
  バグを発見し、時刻形式を満たす場合だけ定時イベントにするよう修正済み。
  JS 全体の構文チェック（node --check）も通過。
- サイト生成：web/index.html に 636 件内包、status/genres が埋め込み JSON に
  含まれていることを確認。バッジ・ジャンル chips・完売/中止を隠す・
  一括書き出しボタンの UI 要素が生成物に存在することを静的に確認。

## 運維批 (2026-10-26 夜，本地实跑验证，未推送)

件数不変：合計 **1092 条** / 今日起 **636 条**（会場別件数も前回と完全一致）。
build.py は state.json を読まない（入力は events.json + venues.json のみ）ため、
state への alerts 追加は生成物に影響なし。再 build 済み・件数再確認済み。

### 1. 失敗・件数減少アラート
- [x] `collect.py` に `load_previous` / `build_alerts` を実装。実行開始時に
  前回の state.json（生件数）と events.json を読み、会場別に比較する。
  アラートは state.json の `alerts`（venue / venue_name / kind / prev / new /
  message）に保存し、ログ末尾にも要約を出す。collect 自体の終了コードは
  従来どおり 0（ジョブの失敗化は workflow 側の検査ステップが担う）。
- 閾値と方式：
  - `fetch_failed`：取得失敗（status=fail）→ 常時アラート
  - `zero_events`：成功扱いで 0 件 → 常時アラート
  - `count_drop`：**like-for-like** 件数が前回比 40% 超減少、かつ前回
    （窓側）が 5 件以上（`ALERT_DROP_RATIO=0.40` / `ALERT_MIN_PREV=5`）。
    前回 events.json が読めない場合のみ state の生件数で代用し message に明記。
  - like-for-like の窓：前回 events.json のうち「今回の実行日以降の公演」
    だけを数え直し、今回分も同じ窓で数える。月替わりで前月分が一斉失効
    しても、翌月分は前回ファイルにも含まれるため誤報にならない。
  - 部分警告（翌月ページ未公開等で件数が残る場合）は単独ではアラートに
    しない（実害は count_drop が拾う）。
  - `month_roll: true` を venues.json に付与：PARKDINER / 千葉 LOOK
    （当月+翌月型）、MOSAiC（当月のみ）、CLUB CITTA'（当月は本日以降のみ
    表示で件数が月内に自然減する）。既知の限界：MOSAiC のような当月のみ型は
    月末に窓側の前回件数が 5 未満に縮み減少判定が自動的に外れるため、
    月替わり直後の減少は検出できない。アラート message には
    month-rolling の注記が付く。
- [x] workflow 側：`collect.yml` の Commit ステップの後に
  「Fail if collection alerts exist」ステップ（`if: always()`）を追加。
  データの commit/push が先に済み、その後 state.json の alerts を検査して
  あれば要約を出力してジョブを失敗させる（GitHub の失敗通知で届く）。

### 2. 1日2回収集
- [x] `collect.yml` の schedule を 07:00 JST（`0 22 * * *` UTC）と
  19:00 JST（`0 10 * * *` UTC）の2本に変更。YAML 妥当性とステップ順序は
  ローカルで検証済み。
- ⚠️ 注意：collect.yml は GitHub App の権限ではプッシュできないため、
  **ユーザーが GitHub 上で collect.yml を新しい内容に差し替える手作業が
  必要**（今回の変更分はローカルに完成済み）。collect.py / venues.json /
  README / PLAN / data / web は通常のプッシュで届く。

### 検証結果（運維批）
- テスト (a) 通常全量収集（19:22〜19:39 JST）：24 active 全会場 ok、
  会場別件数は前回（18:33 分）と完全一致、合計 1092 件、
  **alerts = []**（正当なアラートもなし）。
- テスト (b) 失敗系シミュレーション（/tmp のスクラッチコピー、実 venues.json
  は不変）：WWW の schedule_url をデッド URL（127.0.0.1:9）に向けると
  `fetch_failed`（prev=55 → 0）が発火。MOSAiC の前回イベントを 3 倍化した
  前回ファイルでは `count_drop`（like-for-like 15 → 5、-67%）が発火。
  どちらも state.json の alerts に記録され、ログ要約にも出力された。
  追加の単体チェック：zero_events の発火、前回 5 件未満ガード、20% 減では
  発火しないこと、初回（前回なし）で発火しないこと、生件数フォールバック
  （message に "raw totals" 明記）を確認。
- workflow のアラート検査スニペット自体もスクラッチ state で実行し、
  アラートありで exit 1・要約出力になることを確認。
