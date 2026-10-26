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
