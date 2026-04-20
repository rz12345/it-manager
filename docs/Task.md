# Task — 已完成項目紀錄

<!-- 格式：## YYYY-MM-DD，底下依分類列出完成項目 -->

## 2026-04-20（新增「工具」選單與 MAC 追蹤）

### 功能新增
- 新增 `工具` 頂層導覽列（Admin-only），首頁卡片式工具入口（`app/tools/`）。
- **MAC 追蹤**：輸入 MAC（支援冒號／點號／連字號／無分隔四種格式），從指定起點 switch 查 `mac address-table`，找到後依 LLDP/CDP 鄰居 hop 到下一台 switch，直到 edge port / 偵測 loop / 超過 max_hops。
- 支援廠商：Cisco IOS（`show mac address-table address` + CDP/LLDP）、Aruba OS（AOS-CX 與 ProCurve 雙語法：`show mac-address-table address` / `show mac-address`、`show lldp neighbor-info` / `show lldp info remote-device`）、Zyxel（`show mac address-table mac` + `show lldp ne`）；Palo Alto 排除。
- 鄰居比對順序：management IP → system name（含去 FQDN 後綴），僅 hop 到使用者可存取且 `is_active` 的 Device；鄰居需至少有 `system_name` 或 `mgmt_ip` 才算有效（避免 CLI 錯誤訊息被當成 remote port 誤判）。
- **LAG / Port-Channel 展開**：MAC 學到 `lag13` / `Trk1` / `Po13` 時，先查 LAG 成員（AOS-CX `show lacp aggregates`、ProCurve `show trunks`、Cisco `show etherchannel summary`），再對實體成員 port 跑 LLDP，顯示「via 成員 port」。
- **Interface description 顯示**：每跳查 `show running-config interface ...`（Cisco 用 `show interfaces ... description`）並在卡片顯示 port 描述。
- 背景執行：`threading.Thread` + 前端 `/status` 每 1.5s 輪詢；結果 timeline 卡片顯示每一跳 device/port/VLAN/description/LAG 成員/鄰居。

### 資料模型 / Migration
- 新增 `ToolRun` 表（`tool_name` / `user_id` / `query_json` / `result_json` / `status` / `error_message` / `started_at` / `finished_at`）。
- 注意：Python 屬性用 `query_json` / `result_json`（DB 欄位名仍為 `query` / `result`），避免 `query` 與 Flask-SQLAlchemy `Model.query` 描述符撞名導致 `.get_or_404` 失效。
- 由使用者自行執行 `flask db migrate -m "add tool_run table" && flask db upgrade`。

### 紀錄頁整合
- `紀錄` 新增「工具」頁籤（`logs/tool_runs.html`），可篩選 tool / status；Admin 可看全部、一般使用者只看自己。
- Admin 從列表點「詳情」進入 `tools.mac_trace_detail` 重看 hops。

### 基礎建設
- `app/__init__.py` 新增 Jinja 模板 filter `from_json`，供工具紀錄頁解析 `ToolRun.query_json` / `result_json`。
- `base.html` 導覽列（Admin）與 `cm-quicknav-data` 加入「工具」與「紀錄 — 工具」入口。

### 文件
- `docs/Architecture.md`：加入「工具集（Tools）」章節、`tools` 目錄、Zyxel 廠商預設指令列、LAG 展開與 description 說明。
- `CLAUDE.md`：Blueprint 清單加上 `tools`。

---

## 2026-04-20（測試寄信與告警收件人改為使用者信箱）

### 功能
- Email 任務「測試寄信」改為寄至當前使用者信箱（`current_user.email`），不再讀取 `TEST_EMAIL` 設定。
- 系統設定頁「SMTP 測試寄信」同樣改寄至 `current_user.email`。
- 排程失敗告警（`scheduler/notifier.py`）改寄至任務擁有者信箱（`run.task.owner.email`），新增 `_owner_email()` helper。
- 移除 `NOTIFY_EMAIL`、`TEST_EMAIL` 兩個系統設定欄位（`settings_store.py`、`forms.py`、`routes.py`、`edit.html`）。
- 設定頁 SMTP 區塊僅保留 Host / Port / User / Pass / From 五個欄位。

### 文件
- `docs/Architecture.md`：更新 notifier 說明與 Email 任務細節。
- `docs/Deploy.md`：SMTP 排錯說明更新。

---

## 2026-04-16（郵件模板與爬蟲納入分組）

### 功能
- EmailTemplate、Scraper 新增 `group_id` FK，比照 EmailTask 實作 owner + group 雙軌存取控制。
- 新增 `_user_can_access_template()`、`_visible_templates_query()`、`_populate_group_choices()` 三組 helper（templates_mgr、scrapers 各一套）。
- 模板與爬蟲的所有 route（CRUD、附件、預覽、測試）改用 group-aware 存取檢查。
- EmailTask 建立表單的模板選單、模板表單的爬蟲選單同步支援同組資源。
- 列表頁新增「分組」欄位顯示。
- 分組表單成員欄位移除冗餘括號說明。

### Migration
- `e0fa84dda3f1`: `email_templates` 與 `scrapers` 加 `group_id` 欄位（nullable, indexed, FK to groups）。

## 2026-04-16（排程時區統一）

### 修正
- `scheduler/runner.py` 的 `_compute_next_run` 原以 UTC 當基準呼叫 croniter，導致每次執行後 `next_run` 被重算成「cron 時間當 UTC」，實際觸發時刻偏移 +8h（20:30 TPE 變成 04:30 TPE 隔日）。

### 共用化
- 新增 `app/scheduling.py`：`compute_next_run(task)` 統一以 `DISPLAY_TZ` 為基準計算 cron 下一次時間並轉 UTC naive。
- `app/tasks/routes.py`、`app/email_tasks/routes.py`、`scheduler/runner.py` 三處 `_compute_next_run` 改為引用共用函式，避免時區邏輯漂移。

## 2026-04-15（前端 UI/UX 全站改進）

### 資產本地化
- 將 Bootstrap 5.3.2、Bootstrap Icons 1.11.3、Chart.js 4.4.1 下載至 `app/static/vendor/`，`base.html` 改用 `url_for('static', ...)`，擺脫 jsDelivr CDN 依賴（內網友善）。

### 設計 tokens 與深色模式
- 新增 `app/static/css/tokens.css` 定義亮／暗雙主題的 CSS variables（surface、border、text、tag 色票、陰影）。
- `app/static/css/style.css` 全面將 hard-coded 色碼改用 tokens（tag 系統、設定頁 tag row、legacy stat-card）。
- `base.html` 加入 FOUC-safe inline script：`localStorage['cm-theme']` 決定初始 theme，`auto` 時讀 `prefers-color-scheme`。
- Navbar 新增 theme toggle dropdown（亮／深／跟隨系統），icon 動態反映 preference。
- `main.js` 加入 theme manager：`setThemePref()`、監聽 `(prefers-color-scheme: dark)`、發出 `cm:theme-change` CustomEvent 供圖表重繪用。

### 元件化（Jinja macros）
- 新增 `app/templates/_macros.html`，集中：`page_header`（含 action slot）、`breadcrumb`、`stat_card`、`status_badge`、`active_badge`、`empty_row` / `empty_block`、`confirm_delete_form`（data-confirm）、`responsive_table_start/end`、`form_field`、`submit_button`、`search_input`。

### 列表頁重構
- `tasks/list.html`、`email_tasks/list.html` 重寫：改用 `page_header`、`stat_card`、`status_badge`、`confirm_delete_form` macro；表格套 `.cm-table-responsive .cm-stacked`（手機轉卡片布局，用 `data-label`）。
- `email_tasks/list.html` 移除未定義的 `showConfirmModal` onclick handler 與重複的 local toast 實作，改走 `CM.confirmModal` / `CM.showToast`。
- `main.js` 加入 `showConfirmModal(title, body, cb)` 向後相容 shim，確保 task-manager 繼承模板（`scrapers/*.html`、`templates_mgr/*.html`、`email_tasks/detail.html`）仍可用。

### Confirm 一致化
- 全專案 12 處 `onsubmit="return confirm(...)"` 原生 confirm 全數改為 `data-confirm` 屬性，統一走 `CM.confirmModal` bootstrap modal。影響檔案：`assets/index.html`（3）、`credentials/index.html`、`groups/list.html`、`hosts/detail.html`、`hosts/templates_detail.html`、`settings/edit.html`（5）。

### Dashboard 強化
- `app/dashboard/routes.py` 新增近 30 天每日 success/failed/partial 計數（backup 與 email 各一組），以 SQL `strftime('%Y-%m-%d')` group by 並以 `_fill_series()` 填補無資料日期。
- `dashboard/index.html` 加入 Chart.js 折線圖（`canvas#trendChart`），theme 切換時透過 `cm:theme-change` 事件重建圖表、重讀色票。
- Stat cards 全部改用 `stat_card` macro；backup tab 由原本兩行擴為四張卡片。
- 儲存空間 progress bar 加 tooltip（顯示 breakdown）。
- 「最近備份／寄送」表格狀態欄改用 `status_badge` macro。

### 響應式與無障礙
- `components.css` 新增 `.cm-stacked` 媒體查詢：≤767px 時 `<tr>` 轉為卡片、`<td[data-label]>` 以 pseudo-element 顯示欄位標籤。
- Toast container 加 `role="status"` + `aria-live="polite"`。
- Navbar icon-only 按鈕補 `aria-label`；確認 modal 與 quick-nav modal 加 `aria-labelledby`。

### Quick Navigation
- Navbar 新增搜尋按鈕（Ctrl+K / ⌘K 快速鍵），彈出 modal 搜尋頁面（儀表板、任務、資產 tab、紀錄 tab、郵件模板、爬蟲）。
- 鍵盤操作：↑↓ 選取、Enter 跳轉、Esc 關閉；資料來源為 `<script id="cm-quicknav-data" type="application/json">`（由後端 `url_for` 產生）。

### Form submit spinner
- `main.js` 全站攔截 `<button data-loading-text="...">`，submit 時自動加 spinner + disable；`_macros.html` 的 `submit_button` macro 提供統一寫法。

---

## 2026-04-15（紀錄頁分頁統一 + 驗證庫併入設定頁）

### 紀錄（Logs）路由統一為 `logs.index?tab={backup|email|user}`
- 仿 `assets.index` 單一派發模式：`logs.index` 依 `tab` 切換備份歷史 / Email 寄送 / 使用者紀錄
- 新增 `app/templates/_log_tabs.html` 共用分頁 nav
- 新增 `app/templates/logs/backup_runs.html`（從舊 `backups/list.html` 搬過來並改用共用 tabs）
- `logs/email_runs.html` 與 `logs/user_activity.html` 改 `{% include '_log_tabs.html' %}`，篩選表單與分頁連結補 `tab=` 參數
- 舊路由（`backups.index`、`logs.email_runs`、`logs.user_activity`）改為 302 redirect，保留向後相容並保留 query string
- 刪除 `app/templates/backups/list.html`
- `backups/routes.py` 移除原 `_visible_runs_query` 與列表邏輯（搬到 `logs/routes.py`），僅留主機／設備歷史、單檔下載 / 檢視 / 刪除
- 更新外部連結：`base.html`（側欄 `紀錄` 指向 `logs.index`）、`dashboard/index.html`（「最近備份」/「最近 email」`全部»`）、`tasks/detail.html`、`email_tasks/detail.html`（「查看紀錄」帶 `task_id`）

### 驗證庫併入設定頁 tab：`/settings/?tab=credentials`
- 抽出 `app/templates/_settings_tabs.html` 共用 nav（`settings/edit.html` 與 credentials 頁共用）
- `settings.index` 增加 `tab='credentials'` 分支：delegate 到 `app.credentials.routes._render_list()`（從原 `index()` 抽出資料查詢邏輯）
- `credentials.index` 改為 302 redirect 至 `settings.index?tab=credentials`（保留舊 URL 向後相容）
- `credentials/index.html`：改以「系統設定」為頁首，`{% with active_tab='credentials' %}{% include '_settings_tabs.html' %}{% endwith %}`
- 更新所有 `url_for('credentials.index')`：`credentials/routes.py` 內部 redirect、`credentials/form.html` 返回鈕、`hosts/form.html` 與 `devices/form.html` 的「管理驗證庫」連結，全面改為 `url_for('settings.index', tab='credentials')`

---

## 2026-04-15（資產列表即時過濾 + 序號欄）

五個資產列表頁（Linux 主機 / 網路設備 / 主機類型模板 / 郵件模板 / 爬蟲）新增快速檢索與序號顯示。

### 共用工具
- `app/static/js/main.js`：新增 `CM.initTableFilter(input, table, {emptyText})`；依 tr textContent 不分大小寫過濾，全隱藏時附加「查無符合項目」列

### 模板改動
- `templates/assets/index.html`（hosts / devices / host templates 三分頁）、`templates/scrapers/list.html`、`templates/templates_mgr/list.html`：
  - 各自加上搜尋 input group（`#asset-filter-input` + `#asset-filter-table`）
  - 表頭新增首欄「#」；無分頁頁面用 `loop.index`，分頁頁面用 `(page-1) * per_page + loop.index` 讓序號跨頁連續
  - 空狀態 `colspan` 同步 +1

### Bug 修復
- 初始化 `<script>` 原本放在 `{% block content %}` 內，早於 `base.html` 底部的 `main.js` 執行，導致 `window.CM` 未定義、過濾器未綁定。改放到 `{% block scripts %}`（渲染於 main.js 之後）後即可動態過濾

---

## 2026-04-15（驗證庫 Credential Library）

新增 Admin 限定的「驗證庫」：集中管理可復用的 SSH / 設備帳密，Host / Device 強制引用單一 Credential。

### Models（`app/models.py`）
- 新增 `Credential`（name / username / password_enc / enable_password_enc / description）
- `Host` / `Device` 移除 `username` / `password_enc`（Device 另移除 `enable_password_enc`），改以 `credential_id` (FK, NOT NULL) 關聯

### 新增 blueprint
- `app/credentials/`（`/credentials`）：列表 / 新增 / 編輯 / 刪除；全部 `@admin_required`；被引用時拒絕刪除並顯示引用數
- Templates：`app/templates/credentials/index.html`、`form.html`
- 設定頁 nav 加上「驗證庫」連結（參考 groups 同一個 nav 列）

### Host / Device 整合
- `forms.py`：移除 username / password / enable_password 欄位，改 `credential_id = SelectField(DataRequired)`
- `routes.py`：create / edit / test-connection 全面改經 credential；未綁定回傳 400
- `templates/hosts/form.html`、`devices/form.html`：改為 Credential 下拉 + 「管理驗證庫」外連
- `hosts/detail.html`、`devices/detail.html`、`assets/index.html`：顯示 `credential.username@ip:port`

### Scheduler
- `scheduler/ssh_backup.py`、`scheduler/netmiko_backup.py`：讀 `host.credential.*` / `device.credential.*`；未綁定驗證直接標記 run failed

### Migration
- `migrations/versions/a1c0d11a_add_credential_library.py`：三段式
  1. 建 `credentials` 表、`hosts` / `devices` 加上 nullable `credential_id` + FK
  2. 歷史資料以 `(username, password_enc, enable_password_enc)` 去重歸併為 Credential（自動命名 `{username}@auto-{N}`），回填 FK
  3. `credential_id` 改 NOT NULL、drop 舊 username / password_enc / enable_password_enc
- Downgrade 反向執行（複製帳密回 Host / Device 後 drop 表）

---

## 2026-04-15（config-manager + task-manager 整合為 it-manager）

一次性合併 `Y:/config-manager` 與 `Y:/task-manager` 兩專案至統一的 `Y:/it-manager`，共用 SQLite DB、使用者、權限、通知、排程引擎。

### Models（`app/models.py`）
- 以 SQLAlchemy **single-table inheritance** 統一 `Task` / `TaskRun`：`polymorphic_on='type'`，子類 `BackupTask` / `EmailTask` / `BackupRun` / `EmailRun` 自動依 `type` 過濾，最小化 call-site 改動
- `TaskAlert`（原 `BackupAlert`，保留 alias）泛化支援兩種任務型別
- 原 `task-manager` 的 `Template` 改名為 `EmailTemplate`（避開 Jinja 衝突）
- 新增 `Task.group_id` 讓 email 任務也納入 groups 權限；`Task.template_vars` JSON 欄位

### 新增 blueprint
- `app/email_tasks/`（`/email-tasks`）：Email 任務 CRUD + test-send + toggle；權限：admin / owner / group 成員
- `app/templates_mgr/`（`/templates`）：郵件模板 CRUD + 附件上傳 + 預覽（Jinja2 + 爬蟲變數注入）
- `app/scrapers/`（`/scrapers`）：Web 爬蟲 CRUD + 手動測試
- `app/logs/` 新增 `/email-runs` 列表

### Scheduler（`scheduler/`）
- `runner.py` 改為依 `task.type` 分派：backup 走 `ThreadPoolExecutor`，email 在主執行緒（Playwright 非 thread-safe）
- orphan `TaskRun` 清理涵蓋兩型別
- 新增 `mailer.py`（SMTP + MIMEMultipart + 重試）、`scraper.py`（Playwright + BS4 + regex + JS）、`email_task.py`（email 任務執行入口）
- `notifier.notify_task_failure(run, name, task_type)` 分派器

### Settings
- `settings_store.DYNAMIC_KEYS` 新增 `TEST_EMAIL`
- 通知 tab 新增「測試收件者 Email」欄位（email test-send 使用）

### 導覽列
- 「任務」改為 dropdown：備份任務 / Email 任務 / 郵件模板 / 爬蟲

### Migrations
- 清空舊 migrations，`flask db migrate` 重新產生初始版本 `415065744b20_initial_unified_schema_it_manager`（24 張資料表）

### requirements.txt
- 併入 `playwright==1.49.0` / `beautifulsoup4==4.12.3` / `lxml==5.2.1`

## 2026-04-14（差異比較渲染修正）

### `app/compare/routes.py::view`
- `difflib.unified_diff` 移除 `lineterm=''`，改用預設 `'\n'`；原本 `---`/`+++`/`@@` 控制行沒有結尾換行，會與資料行黏成一行（`--- 左+++ 右@@ ... @@+content`），diff2html 解析失敗而渲染空白區塊

## 2026-04-14（主機頁比較按鈕統一為頁首單一入口）

### `app/templates/hosts/detail.html`
- 移除備份路徑每列的「比較版本」按鈕
- 頁首按鈕列新增「比較版本」按鈕（與 `/devices/<id>` 一致位置）
- Modal 開啟時一次拉取所有路徑的所有版本，依既有「檔案」下拉先挑檔案再挑版本的流程

### `app/hosts/routes.py::versions`
- `path` query 參數改為選填：不傳時回傳該主機所有成功 records（跨檔案）；傳入時維持原本（literal 比對或 glob → SQL LIKE）

## 2026-04-14（備份歷史頁移除刪除按鈕）

### `app/templates/backups/list.html` / `history.html`
- 移除「操作」欄與垃圾桶刪除按鈕；列表更簡潔，避免在歷史頁誤刪單筆備份
- 後端 `backups.delete_run` 路由保留（未移除）

## 2026-04-14（新增全清備份 CLI）

### `app/backups/cli.py`
- 新增 `flask backups purge-all` 指令：清除所有 `BackupRun`（含 `BackupRecord` / `BackupAlert` cascade）與 `backups/hosts` / `backups/devices` 下的檔案與子目錄
- 預設互動確認；`--yes` 略過（保留 `BackupTask`、`Host`、`Device`、使用者）
- 會先列出將刪除的 run 數與檔案數，讓使用者二次確認

## 2026-04-14（任務詳細頁近期執行 → 查看紀錄按鈕）

### `app/templates/tasks/detail.html`
- 移除「近期執行」表格區塊，改為單一「查看紀錄」按鈕，導向 `backups.index` 並帶 `task_id` 篩選

### `app/backups/routes.py::index`
- `/backups/` 新增 `task_id` query 參數過濾 `BackupRun.task_id`，template context 多 `filter_task_id`

### `app/tasks/routes.py::detail`
- 移除 `recent_runs` context（不再需要）

## 2026-04-14（移除 navbar 差異比較項目）

### `app/templates/base.html`
- 主機／設備詳細頁已整合比較版本入口，navbar 的「差異比較」項目移除；`compare` blueprint 路由保留不動（仍由詳細頁 Modal 與 `/compare/view` 使用）

## 2026-04-14（版本表新增操作欄：檢視 / 下載）

### `app/backups/routes.py`
- 新增 `GET /record/<id>/view` 端點：`send_file` 以 `mimetype='text/plain; charset=utf-8'`、`as_attachment=False` 回傳，讓瀏覽器直接線上顯示（權限同 `download_record`）

### `app/templates/compare/select.html` / `hosts/detail.html` / `devices/detail.html`
- 版本表最末新增「操作」欄，每列兩顆 icon button：檢視（新分頁開啟 `backups.view_record`）、下載（`backups.download_record`）
- JS 端以 `url_for(..., record_id=0)` 產生 URL template，runtime 以字串替換插入實際 id

## 2026-04-14（設備詳細頁加入版本比較）

### `app/devices/routes.py`
- 新增 `GET /devices/<id>/versions` JSON 端點，回傳該設備所有成功 `BackupRecord`（id / file_path / started_at / size / checksum），權限沿用 `user_can_access(device)`

### `app/templates/devices/detail.html`
- 頁首按鈕列新增「比較版本」按鈕，開啟 Bootstrap Modal（設備僅 running-config 一個檔案，不需檔案下拉）
- Modal 表格包含 左/右 radio、備份時間、Hash（前 10 碼 + hover tooltip 全碼）、大小；送出導向既有 `compare.view`

## 2026-04-14（版本表加 Hash 欄位）

### `app/templates/compare/select.html` + `app/templates/hosts/detail.html` 比較 Modal
- 版本表新增 Hash 欄，顯示 `BackupRecord.checksum` 前 10 碼（`<code>`），完整 SHA256 放在 `title`（hover 顯示），讓使用者不必進入 diff 頁就能肉眼判斷是否同內容

### `app/hosts/routes.py::versions`
- JSON 回應新增 `checksum` 欄位

## 2026-04-14（compare/select 頁改為先選檔案再選版本）

### `app/compare/routes.py`
- 抽出 `_group_records_by_file(runs)` 共用工具：僅保留版本數 ≥2 的成功 records，依 `file_path` 字母排序、組內依 `started_at` 由新到舊
- `select_host` / `select_device` 改傳 `groups` 取代 `runs`

### `app/templates/compare/select.html`
- 多個檔案時頂端顯示「檔案」下拉（列出版本數），一個 `<table>` 內多個 `<tbody class="file-group" data-file="...">`，切換下拉時只顯示對應 tbody 並清掉已選 radio，強制只能同檔案比較
- 單一檔案時下拉隱藏；無可比較檔案時顯示 info alert
- 裝置頁面（僅 'running-config'）沿用同模板，下拉自動隱藏

## 2026-04-14（Glob 路徑改為先選檔案再選版本）

### `app/templates/hosts/detail.html` — 比較 Modal
- Glob 路徑展開出多個實際檔案時，Modal 頂端新增「檔案」下拉（單一檔案時隱藏），選項標示版本數；底下版本表只列當前選中檔案的所有版本，強制只能在同檔案內挑左／右，避免跨檔案誤比較
- 「檔案」欄位從版本表移除（已透過下拉顯示）
- 僅有 1 筆版本的檔案不列入下拉；全部檔案都只有 1 筆時沿用「尚無可比較的歷史版本」提示

## 2026-04-14（主機詳細頁整合差異比較）

### `app/hosts/routes.py`
- 新增 `GET /hosts/<id>/versions?path=<file_path>` JSON 端點，回傳該主機該檔案路徑的所有成功備份版本（id / file_path / started_at / size），支援 Glob 路徑（`*` → SQL `%`、`?` → `_`），權限沿用 `user_can_access(host)`

### `app/templates/hosts/detail.html`
- 備份路徑卡片每列新增「比較版本」按鈕（`bi-file-diff`），點擊開啟 Bootstrap Modal
- 頁尾新增共用 Modal：開啟時依 `data-path` 以 AJAX 拉取版本清單，顯示兩欄 radio（左／右）+ 備份時間 + 檔案 + 大小，送出以 GET 送到既有 `compare.view`（未改 compare 相關程式）
- 版本少於 2 筆時顯示提示；左右相同或未選時「比較」按鈕 disabled

## 2026-04-14（立即執行併發 + JSON 錯誤處理）

### `app/tasks/routes.py::run_now`
- 改用 `ThreadPoolExecutor`（上限 `SCHEDULER_MAX_WORKERS`）併發備份所有目標，8 台設備原本最壞 8×60s = 8 分鐘，併發 5 後縮到約 2×60s
- 全域 try/except 確保任何例外都回 JSON（避免前端 `res.json()` 收到 HTML error page 炸出 `SyntaxError: Unexpected token '<'`）

## 2026-04-14（Aruba 分頁問題 + orphan 清理）

### `scheduler/netmiko_backup.py`
- 連線後主動嘗試多種分頁關閉指令（`no page` / `no paging` / `terminal length 0` / `terminal length 1000` / `set cli pager off`），靜默 catch 不支援的指令；解決 Netmiko `aruba_os` session_preparation 對不同韌體版本分頁指令不一致造成的 `Pattern not detected` 失敗
- `send_command` 失敗時自動 fallback 到 `send_command_timing`（不靠 prompt 偵測，以輸出靜默 4s 判斷結束），對 Aruba/老舊韌體較可靠

### `scheduler/runner.py`
- 啟動時清理 orphan `BackupRun`：status=`running` 且 `started_at` 超過 `max(netmiko_timeout, ssh_timeout) × 3` 的舊紀錄，全部標為 failed + error_message，避免 runner 中斷或 Windows 無 flock 重入時的殘影

## 2026-04-14（排程器併發 + 重入保護）

### `scheduler/runner.py`
- 加入檔案鎖 `data/scheduler.lock`（Linux 使用 `fcntl.flock` 非阻塞；Windows 開發環境降級為不加鎖），避免 cron 每分鐘觸發時，前一輪尚未結束便重複啟動 runner 造成任務重覆派送
- 單一任務內的多個 target 改為 `ThreadPoolExecutor` 併發執行；子執行緒各自 `app.app_context()`、共用 Flask-SQLAlchemy scoped session（thread-local）
- 併發數由新增設定 `SCHEDULER_MAX_WORKERS` 控制（預設 5，範圍 1–50）

### 設定相關
- `app/settings_store.py`：新增 `SCHEDULER_MAX_WORKERS` key、預設 `'5'`、`get_scheduler_max_workers()` getter（clamp 1–50）
- `app/settings/forms.py`：`TimeoutForm` 新增欄位 `SCHEDULER_MAX_WORKERS`
- `app/settings/routes.py`：`_TIMEOUT_KEYS` 加入新 key、預填值
- `app/templates/settings/edit.html`：連線 tab 新增「排程併發數」欄位

## 2026-04-14（資產頁合併 / 導覽調整）

### 導覽 & 路由
- 「備份任務」→「任務」並移至「Linux 主機」左邊
- 「備份歷史」→「紀錄」並移至「系統設定」左邊
- 「Linux 主機」＋「網路設備」合併為單一「資產」導覽，採用 settings 分頁模式

### 新 blueprint `app/assets/`
- 單一路由 `/assets/?tab=hosts|devices|templates`，一般使用者僅可見 hosts/devices 兩分頁，主機類型模板分頁限 Admin
- 模板 `app/templates/assets/index.html` 合併三張列表（原 hosts/list、devices/list、templates_list），含各自的「新增」按鈕
- 既有 CRUD 路由（`hosts.create/edit/delete/detail`、`devices.*`、`hosts.templates_*`）維持不變；儲存或刪除後一律 redirect 至 `assets.index` 對應 tab
- 移除 `hosts.index` / `devices.index` / `hosts.templates_index` 三個 list 路由與對應模板；`hosts/routes.py` 與 `devices/routes.py` 的 `_visible_*_query` helper 改搬至 `assets/routes.py`
- Test：`test_hosts.py::test_index_requires_login` 改指向 `/it-manager/assets/`

## 2026-04-14（備份任務 — 多目標排程重構）

### 新增 BackupTask 概念，完全取代 Host/Device 嵌入式排程

- 參考 `Y:\task-manager` 的任務頁面機制（SelectMultipleField checkbox + basic/advanced/once 三種排程模式）
- 新 Models：`BackupTask`（name / schedule_mode / cron_expr / scheduled_at / schedule_basic_params / retain_count / next_run / last_run / last_status / is_active）、`BackupTaskTarget`（task_id × host_id / device_id，允許同一 Host/Device 屬於多個 Task）
- 新 Blueprint `app/tasks/`（獨立選單「備份任務」），URL `/tasks`：list / create / detail / edit / delete / toggle / run_now
- 新模板 `app/templates/tasks/`：`list.html`、`create.html`、`edit.html`、`detail.html`、`_form.html`（含 basic→cron 轉換 JS，與 task-manager 對齊）
- Form：兩欄 checkbox 捲動框分別列 Linux 主機、網路設備；驗證「至少選一個目標」
- `BackupRun` 新增 `task_id` FK（可 NULL，保留歷史紀錄完整性）；retain 清理改為 per-(task, target)
- `scheduler/runner.py` 改為以 `BackupTask.next_run` 為主迴圈，對每個 target 依類型呼叫 `run_host_backup` / `run_device_backup`，一次性任務執行後自動停用
- `scheduler/ssh_backup.py` / `scheduler/netmiko_backup.py` 簽章改為 `(target_id, task_id, retain_count, triggered_by)`，移除 `_update_next_run`（任務層掌控）
- 移除 Host / Device 上的 `auto_backup_enabled / cron_expr / retain_count / next_run / last_run / last_status` 欄位；Host/Device detail 改用 `last_run_info` property 顯示最近備份
- 移除 `app/backups/forms.py`（ScheduleForm）、`app/templates/backups/schedule.html`、`backups.host_schedule/device_schedule/host_run/device_run` 路由
- Dashboard「即將執行」改顯示 BackupTask；navbar 在「備份歷史」前新增「備份任務」入口
- Migration `b1a7e2c9f4d0_backup_tasks`：建立 backup_tasks / backup_task_targets 兩表，`backup_runs` 加 `task_id`，Host/Device 移除 6 個排程欄位與相應索引

## 2026-04-14（UI — navbar 統一化）

### 14 個頁面模板改為繼承 `app/templates/base.html`

- 原本這些頁面是獨立的完整 HTML 文件（自載 Bootstrap/Icons CDN、自寫 `<body>`），因此不會顯示 `base.html` 的 navbar
- 改為 `{% extends 'base.html' %}` + `{% block content %}`，全站 navbar（`navbar navbar-expand-lg navbar-dark bg-dark shadow-sm`）一致
- 清單頁：`hosts/list.html`、`devices/list.html`、`backups/list.html`、`groups/list.html`
- 詳細/表單頁：`hosts/form.html`、`hosts/detail.html`、`hosts/templates_list.html`、`hosts/templates_form.html`、`hosts/templates_detail.html`、`devices/form.html`、`devices/detail.html`、`groups/form.html`、`backups/history.html`、`backups/schedule.html`
- 移除各頁重複的 flash 渲染區塊（`base.html` 已統一處理）與「返回儀表板」按鈕（navbar 已有入口）
- 表單頁以 `<div class="mx-auto" style="max-width: ...">` 取代原先的 `container py-4 style="max-width"`，保留置中排版
- 內嵌 `<script>` 移至 `{% block scripts %}`（`hosts/detail`、`devices/detail`、`backups/history`）
- 內嵌 `<style>` 移至 `{% block head_extra %}`（`groups/form`）

## 2026-04-14（Phase 15 — 部署文件）

### docs/Deploy.md（12 章節）

- 系統需求（Ubuntu 22.04/24.04 + Python 3.12+）
- Git clone → `/opt/it-manager`、venv 建立、`pip install -r requirements.txt`
- `.env` 設定（`SECRET_KEY` 以 `secrets.token_hex(32)`、`CRYPTO_KEY` 以 `Fernet.generate_key()`），並警示金鑰不可換
- `flask db upgrade` + `flask hosts seed-templates` 初始化
- systemd unit（gunicorn 3 workers，bind `127.0.0.1:8017`，access/error log 落在 `data/`）
- nginx `location /it-manager/` 反向代理範例（帶 `X-Forwarded-Prefix`）
- Cron 安裝步驟（`sudo crontab -u www-data -e` 以與 systemd 服務同權限執行 `python -m scheduler.runner`）
- Web UI 系統設定頁面用途說明（SMTP、逾時、密碼政策）
- 升級流程：`git pull` → `pip install` → `flask db upgrade` → `systemctl restart`
- 備援：`.env` + `data/*.db` + `backups/` + `data/scheduler.log`，建議 rsync
- 常見排錯表：404 / CSRF / InvalidToken / cron 不執行 / SMTP 失敗

## 2026-04-14（Phase 14 — 測試）

### Pytest 配置（tests/conftest.py）

- `TestConfig`：`TESTING=True` / `WTF_CSRF_ENABLED=False` / `SECRET_KEY='test-secret'` / `CRYPTO_KEY=Fernet.generate_key()`
- `app` fixture：每個測試獨立 `tempfile.mkdtemp()`，動態組 `SQLALCHEMY_DATABASE_URI=sqlite:///{tmpdir}/test.db`（不使用 `:memory:` 因 `create_app()` 的 `os.makedirs(os.path.dirname(...))` 對該 URI 會失敗），`BACKUP_BASE_PATH=tmpdir`；進入 `app_context()` + `db.create_all()`，結束時 `drop_all()`
- 使用者 fixtures：`admin_user`（is_admin=True）、`regular_user`；`login(username, password)` helper + `logged_in_admin` / `logged_in_user` 自動登入

### 驗證（tests/test_auth.py，6 項）

- 無使用者時 `/login` → 302 到 `/setup`
- `/setup` 成功建立 admin 並自動登入 → 302 到 dashboard
- 已有使用者時 `/setup` → 302 到 `/login`
- 登入成功 / 失敗（失敗會留一筆 `LoginLog(status='failed')`）
- 登出會寫入 `LoginLog(action='logout')`

### 主機（tests/test_hosts.py，9 項）

- 未登入列表 → 302 `/auth/login`
- Admin POST `/create` → 寫入 DB，`password_enc` 非明文，`decrypt()` 可還原
- 一般使用者 POST `/create` → 403
- 分組可見性：未加入分組時 detail 403；加入後 200
- 編輯時密碼留白保留原 `password_enc`
- 刪除 → DB 記錄移除
- `POST /paths/add`：新增 `HostFilePath(source='manual')`；相對路徑會被 Regexp 擋下
- 模板套用：`template_id` 展開 `HostTemplatePath` 為 `HostFilePath(source='template')`

### 網路設備（tests/test_devices.py，5 項）

- Admin 建立 `cisco_ios` 設備 → `effective_command` 使用廠商預設 `show running-config`
- 自訂 `backup_command` 優先於廠商預設
- 分組可見性（同 hosts 模式）
- 一般使用者 POST `/delete` → 403
- Admin 刪除成功

### 備份（tests/test_backups.py，8 項）

- `host_with_run` fixture：建立 Host + `BackupRun(success)` + `BackupRecord` 指向 `tmp_path` 下的實體檔案
- 列表頁未登入 302；Admin 看到所有 run；一般使用者（無分組）列表中看不到該 run
- Admin 下載檔案回 200；一般使用者（無分組）下載回 403
- Admin 刪除 run → 實體檔案被 `os.remove()`、cascade 刪 BackupRecord
- 排程 POST → `auto_backup_enabled=True`、`cron_expr` 寫入、`next_run` 由 croniter 計算
- `monkeypatch` 將 `scheduler.ssh_backup` 設為 `None` 模擬 ImportError → 手動備份 AJAX 回 501

### 結果

- 28 個測試全數通過（執行指令：`py -m pytest tests/`，耗時約 24s）
- SQLAlchemy `Query.get()` Legacy 警告不影響通過（沿用專案既有用法）

## 2026-04-14（Phase 13 — 前端共用）

### 模板（app/templates/base.html）

- Bootstrap 5.3 + Bootstrap Icons 共用版型，含 `<meta name="csrf-token">` 供 AJAX 使用
- Navbar：品牌連結、dashboard/hosts/devices/backups/compare、Admin 可見 groups/settings；依 `request.endpoint` 前綴自動高亮 `active`
- Navbar 右側：告警鈴鐺（紅色 pill badge 顯示 `unread_alert_count`，錨點跳至 dashboard `#alerts`）、使用者下拉（登出）
- 區塊：`title` / `head_extra` / `content` / `scripts`；底部預置全域 `#toast-container` 與 `#confirm-modal`
- Flash messages 以 `alert-{category}` + `alert-dismissible` 呈現

### 靜態資源（app/static/）

- `css/style.css`：字型堆疊（Noto Sans TC / PingFang TC / 微軟正黑）、navbar active 樣式、`.stat-card` 四色左側邊條（primary/success/warning/danger/info）、`.member-list` 分組成員捲動容器、diff2html 容器微調
- `js/main.js`：`CM.showToast(message, level, delay)` — Bootstrap Toast 彈出；`CM.confirmModal({title, body, okText, okClass})` — Promise-based 共用 Modal；`CM.postJSON(url, body)` — 自動夾帶 `X-CSRFToken` header 的 fetch helper；`data-confirm` 全站表單攔截（會以 Modal 代替 `window.confirm`，按下確認後重新觸發原始 submit）

### Flask 整合（app/__init__.py）

- `@app.context_processor inject_alert_count`：未登入回傳 0；登入後查詢 `BackupAlert.is_read=False` 數量，table 缺失時（初始部署）吞掉 `SQLAlchemyError` 回 0

> 既有頁面（auth/hosts/devices/groups/backups）仍為獨立頁面樣式；新頁面（dashboard/compare/settings）皆繼承 base.html

## 2026-04-14（Phase 11 — 排程器 scheduler）

### 主流程（scheduler/runner.py）

- `main()`：`create_app().app_context()` 內查詢 `Host.auto_backup_enabled=True AND is_active=True AND next_run<=now`，對 Device 同樣處理
- 逐筆呼叫 `run_host_backup` / `run_device_backup(triggered_by='schedule')`，例外 `db.session.rollback()` 並寫 stderr；log 寫 stdout 供 cron 重導向
- 進入點：`python -m scheduler.runner`（每分鐘由 cron 觸發一次，由 `next_run` 決定是否執行）

### Linux 主機備份（scheduler/ssh_backup.py）

- `run_host_backup(host_id, triggered_by)`：建立 `BackupRun(status='running')` 並立即 commit（避免長時間連線期間 row 不可見）
- Paramiko `AutoAddPolicy`、`allow_agent=False, look_for_keys=False`，逾時由 `get_ssh_timeout()` 控制；密碼透過 `app.crypto.safe_decrypt`
- `_expand_glob(sftp, pattern)`：逐層展開 path（`*` / `?` → regex `.*` / `.`），用 `sftp.listdir` 匹配後以 `sftp.stat` 過濾出 regular file
- 逐個 SFTP `sftp.get()` 下載至 `backups/hosts/{id}/{YYYYMMDD_HHMMSS}_{sanitized_path}`，計算 SHA-256 checksum，寫入 `BackupRecord`
- 匹配不到檔案記一筆 `status='failed'`；連線/認證錯誤（`AuthenticationException` / `SSHException` / `socket.timeout` / `OSError`）整筆 run 標 failed 並記 error_message
- 狀態彙整：無 error → `success`（全數成功）/ `partial`（有成功也有失敗）/ `failed`（全失敗或連線錯）
- `Host.last_run` / `last_status` 更新；`triggered_by='schedule'` 時以 croniter 重算 `next_run`
- 失敗/部分失敗時建立 `BackupAlert` 並呼叫 `notifier.notify_backup_failure`（SMTP 異常吞掉不影響 commit）
- `_cleanup_old_runs(retain)`：保留最近 N 筆 `BackupRun`，其餘 `os.remove()` storage_path 後 `db.session.delete()`（cascade 刪 BackupRecord）

### 網路設備備份（scheduler/netmiko_backup.py）

- `run_device_backup(device_id, triggered_by)`：結構比照 ssh_backup；Netmiko `ConnectHandler(device_type=vendor, ...)`
- enable_password 若存在，加入 `secret` 並 `conn.enable()`；執行 `device.effective_command`（自訂或廠商預設）
- 處理 `NetmikoAuthenticationException` / `NetmikoTimeoutException` / 其他例外
- 成功時寫入 `backups/devices/{id}/{timestamp}_running.cfg`，一次 `BackupRun` 只會產生 0 或 1 筆 `BackupRecord(file_path='running-config')`

### 告警通知（scheduler/notifier.py）

- `send_email(subject, body, to_addr=None)`：從 `settings_store.get_smtp_cfg()` 取 SMTP 設定，預設收件者為 `NOTIFY_EMAIL`；未設定則 return `(False, '略過寄送')`
- SMTP 建立後先 `ehlo()` → 嘗試 `starttls()`（失敗忽略）→ 若有 user/pass 則 `login()` → `send_message()`
- `notify_backup_failure(run, target_name, target_type)`：僅對 `failed` / `partial` 狀態寄發，內容含 run 時間/檔案數/error_message，並附每筆 failed BackupRecord

### Cron 範本（cron/crontab.example）

- 範本提示替換 `<PROJECT_PATH>` 與 `<VENV_PY>`
- 每分鐘 `cd <PROJECT_PATH> && <VENV_PY> -m scheduler.runner >> data/scheduler.log 2>&1`

## 2026-04-14（Phase 9 — 差異比較）

### 路由（app/compare/routes.py）

- `GET /`：列出使用者可見的 Host + Device（Admin 看全部；一般使用者以 `group_ids` 過濾）
- `GET /host/<id>` / `GET /device/<id>`：`user_can_access` 檢查後列出目標所有 `BackupRun` 及其 `BackupRecord`（僅 `status='success'`）供左右 radio 選取
- `GET /view?left=<record_id>&right=<record_id>`：權限檢查（兩端皆要可存取）+ 同一目標檢查（`target_type` 相同、`host_id`/`device_id` 相同）；讀取兩檔以 `difflib.unified_diff` 產生 diff 文字傳入模板

### 模板（app/templates/compare/）

- `index.html`：兩欄 card 分列主機與設備，項目為連結
- `select.html`：表格（左 radio / 右 radio / 備份時間 / 狀態 / 檔案 / 大小），提交前以 `CM.showToast` 驗證「兩側皆選且不同」
- `view.html`：CDN 載入 `diff2html@3.4.48` CSS + `diff2html-ui.min.js`，`new Diff2HtmlUI(container, diffText, {outputFormat: 'side-by-side', matching: 'lines', highlight: true})` 渲染；內容一致時顯示「兩個版本內容完全相同」alert

## 2026-04-14（Phase 10 — 儀表板）

### 路由（app/dashboard/routes.py）

- `GET /`：統計卡（Host 數 / Device 數 / 啟用排程數 / 24h 內總備份 + 失敗數）、最近 10 筆 BackupRun、未讀 Alert 列表（top 20）、即將執行的 Host/Device（各取 5 筆）
- 一般使用者以 `_visible_ids()` 過濾所有查詢
- `POST /alerts/<id>/read`：任何使用者可將自己可見的告警標為已讀
- `POST /alerts/read-all`：Admin 一鍵全部標為已讀

### 模板（app/templates/dashboard/index.html）

- 四張 `stat-card`（色條 info/info/success/danger 視失敗數）
- 左側：最近備份表格 + 即將執行列表；右側：未讀告警 list（錨點 `#alerts` 供 navbar badge 跳轉）
- 每筆告警附「標為已讀」按鈕（單筆）與 Admin 可見「全部已讀」按鈕

## 2026-04-14（Phase 12 — 系統設定）

### 表單（app/settings/forms.py）

- `SettingsForm`：SMTP（host/port/user/pass/from/notify_email）、逾時（SSH/Netmiko）、密碼政策（min_length/upper/lower/digit/special/expire_days）
- `SMTP_PASS` 留白時保留原值；整數欄位均有 `NumberRange` 限制

### 路由（app/settings/routes.py，`@admin_required`）

- `GET/POST /`：以 `set_setting(key, str(value))` 迭代 `DYNAMIC_KEYS` 寫入；GET 時從 `get_setting` 預填（跳過 `SMTP_PASS`），傳遞 `has_smtp_pass` 讓模板顯示「已設定」提示

### 模板（app/templates/settings/edit.html）

- 三張 card：SMTP 告警 / 連線逾時 / 密碼政策；每區以 Bootstrap grid 欄位排版

## 2026-04-14（Phase 8 — 備份排程模組）

### 表單（app/backups/forms.py）

- `ScheduleForm`：auto_backup_enabled / cron_expr（`_validate_cron` 以 croniter 驗證，ImportError 時略過）/ retain_count（`NumberRange 1–1000`）
- `ScheduleForm.validate()`：啟用自動備份時強制要求 cron_expr 非空

### 路由（app/backups/routes.py）

- `_visible_runs_query()`：Admin 全部；一般使用者先撈可見 Host/Device id，再以 `target_type + id.in_()` 過濾 BackupRun
- `_compute_next_run(cron_expr)`：croniter 計算下次執行時間（UTC）
- `GET /`：備份歷史全局列表（分頁 30/頁），支援 `?type=host|device`、`?status=success|partial|failed|running` 篩選
- `GET /host/<id>`、`GET /device/<id>`：單一目標的備份歷史（含檔案清單 details/summary 可展開）
- `GET/POST /host/<id>/schedule`、`GET/POST /device/<id>/schedule`：Admin 專用排程編輯，儲存時同步計算 `next_run`（關閉時清空）
- `POST /host/<id>/run`、`POST /device/<id>/run`：Admin 專用 AJAX 手動立即備份，呼叫 `scheduler.ssh_backup.run_host_backup` / `scheduler.netmiko_backup.run_device_backup`；Phase 11 尚未實作時回傳 501 提示
- `POST /run/<run_id>/delete`：Admin 刪除單筆 BackupRun，逐一移除 `storage_path` 實體檔案後 cascade 刪除 BackupRecord
- `GET /record/<id>/download`：依 `user_can_access` 檢查後以 `send_file` 下載備份實體檔案

### 模板（app/templates/backups/）

- `list.html`：全局備份歷史表格 + 類型/狀態篩選表單 + 分頁，行內刪除含 confirm
- `history.html`：單一目標頁含排程摘要 bar、`details/summary` 展開每次 BackupRun 的檔案清單（含下載連結）、立即備份按鈕（AJAX，spinner + alert 顯示結果，成功後自動 reload）、排程設定入口
- `schedule.html`：auto_backup 開關、Cron 表達式輸入（font-monospace）+ 常用範例提示、retain_count、下次執行時間預覽
- 均沿用獨立頁面樣式（未繼承 base.html，待 Phase 13 整合）

## 2026-04-14（Phase 7 — 網路設備模組）

### 表單（app/devices/forms.py）

- `DeviceForm`：name / ip_address / port（預設 22，`NumberRange 1–65535`）/ vendor（下拉：`cisco_ios` / `aruba_os` / `paloalto_panos`，以 `VENDOR_LABEL` 顯示中文）/ username / password（選填，編輯時留白保留原值）/ enable_password（選填，Cisco enable 模式）/ backup_command（選填，留白使用廠商預設）/ description / group_id / is_active

### 路由（app/devices/routes.py）

- `_visible_devices_query()`：比照 hosts 邏輯（Admin 全部；一般使用者以 `group_ids` 過濾，無分組回傳空集合）
- `GET /`：`@login_required` 列出可見設備
- `GET/POST /create`、`GET/POST /<id>/edit`、`POST /<id>/delete`：`@admin_required`，密碼/enable 密碼透過 `app.crypto.encrypt` 加密；編輯時密碼留白則保留原值
- `GET /<id>`：`user_can_access` 檢查後顯示詳情，含廠商預設指令 vs. 自訂指令 vs. `effective_command` 對照
- `POST /<id>/test-connection`：Admin 專用 AJAX，透過 Netmiko `ConnectHandler` 連線測試，逾時秒數來自 `get_netmiko_timeout()`；分別處理 `NetmikoAuthenticationException` / `NetmikoTimeoutException` / `socket.timeout` / `OSError`，成功時回傳 `find_prompt()`

### 模板（app/templates/devices/）

- `list.html`：Bootstrap 表格（名稱/廠商/連線/分組/狀態/排程 icon/最近備份 badge/操作）
- `form.html`：create/edit 共用，兩欄式佈局含 vendor 下拉、密碼/enable 密碼 `autocomplete="new-password"`、backup_command placeholder 明列三家預設指令
- `detail.html`：左側基本資訊（含「測試連線（Netmiko）」按鈕，spinner + 結果 icon），右側備份指令卡（廠商預設 / 自訂 / 實際執行三行對照）
- 均沿用獨立頁面樣式（未繼承 base.html，待 Phase 13 整合）

## 2026-04-14（Phase 6 — 主機類型模板）

### 表單（app/hosts/forms.py）

- `HostTemplateForm`：name（必填，≤100）、description（選填，≤256）
- `HostTemplatePathForm`：path（必填，`Regexp(^/)` 絕對路徑，≤512，支援 Glob）

### 路由（app/hosts/routes.py，全部 `@admin_required`）

- `GET /templates/`：列出所有模板（含預設路徑數 badge）
- `GET/POST /templates/create`：新建模板，name 唯一性檢查，建立後導向 detail
- `GET/POST /templates/<id>/edit`：編輯模板名稱／描述
- `POST /templates/<id>/delete`：刪除模板（已套用至主機的 HostFilePath 不受影響）
- `GET /templates/<id>`：檢視基本資訊 + 預設路徑列表
- `POST /templates/<id>/paths/add`、`POST /templates/<id>/paths/<path_id>/delete`：HostTemplatePath 增刪（避免重複）
- Phase 5 已實作 `_apply_template(host, template_id)`，於主機新增/編輯時展開 `HostTemplatePath` → `HostFilePath(source='template')`，不覆蓋手動路徑

### 模板（app/templates/hosts/）

- `templates_list.html`：Bootstrap 表格（名稱／描述／預設路徑數 badge／操作），含 confirm 刪除
- `templates_form.html`：create/edit 共用（`mode` 切換），編輯模式提示「預設路徑請至檢視頁面管理」
- `templates_detail.html`：基本資訊卡 + 預設路徑列表（新增輸入框，支援 Glob placeholder，逐筆 confirm 移除）
- `hosts/list.html` 新增「主機類型模板」按鈕（Admin 專用，連至 templates_index）

### CLI（app/hosts/cli.py，Blueprint `cli_group='hosts'`）

- `flask hosts seed-templates`：idempotent 建立三個預設模板
  - **Web Server**：Nginx / Apache 設定檔（`/etc/nginx/nginx.conf`、`/etc/nginx/conf.d/*.conf`、`/etc/nginx/sites-enabled/*`、`/etc/apache2/apache2.conf`、`/etc/apache2/sites-enabled/*.conf`）
  - **DB Server**：MySQL / MariaDB / PostgreSQL 設定檔（`/etc/mysql/my.cnf`、`/etc/mysql/mariadb.conf.d/*.cnf`、`/etc/postgresql/*/main/postgresql.conf`、`/etc/postgresql/*/main/pg_hba.conf`）
  - **General**：通用系統設定檔（`/etc/hosts`、`/etc/hostname`、`/etc/resolv.conf`、`/etc/ssh/sshd_config`、`/etc/crontab`）
- 已存在名稱會略過，避免覆蓋使用者修改

## 2026-04-14（Phase 5 — Linux 主機模組）

### 表單（app/hosts/forms.py）

- `HostForm`：name / ip_address / port（預設 22，`NumberRange 1–65535`）/ username / password（選填，編輯時留白保留原密碼）/ description / group_id（SelectField，選項含「（未分組）」=0）/ template_id（套用主機類型模板，0=不套用）/ is_active
- `HostFilePathForm`：path（必填，`Regexp(^/)` 要求絕對路徑，最長 512）

### 路由（app/hosts/routes.py）

- `_visible_hosts_query()`：Admin 全部；一般使用者以 `current_user.group_ids` 過濾，無分組回傳空集合
- `_apply_template(host, template_id)`：展開 `HostTemplate.template_paths` → `HostFilePath(source='template')`，同路徑不重複加入；新增/編輯皆可套用（不覆蓋既有手動路徑）
- `GET /`：`@login_required`，依可見性列出主機
- `GET/POST /create`、`GET/POST /<id>/edit`、`POST /<id>/delete`：`@admin_required`；密碼欄位透過 `app.crypto.encrypt` 加密寫入 `password_enc`
- `GET /<id>`：`user_can_access` 檢查，不通過則 `abort(403)`；顯示主機詳情 + 備份路徑管理
- `POST /<id>/paths/add`、`POST /<id>/paths/<path_id>/delete`：Admin 專用，HostFilePath 增刪（避免路徑重複）
- `POST /<id>/test-connection`：Admin 專用 AJAX，以 Paramiko `AutoAddPolicy` 連線測試（`allow_agent=False`, `look_for_keys=False`），逾時秒數來自 `settings_store.get_ssh_timeout()`；分別處理 `AuthenticationException` / `SSHException` / `socket.timeout` / `OSError`；回傳 `{ok, message}`，成功時附上 SSH banner

### 模板（app/templates/hosts/）

- `list.html`：Bootstrap 表格（名稱/連線/分組/狀態/排程 icon/最近備份 + `last_status` badge/操作），行內連結至 detail、edit、delete（confirm）；一般使用者僅看到「檢視」按鈕
- `form.html`：create/edit 共用（`mode` 切換），兩欄式欄位佈局，密碼欄位於編輯模式顯示「留白保留原密碼」提示；`autocomplete="new-password"` 避免瀏覽器自動填入
- `detail.html`：左側基本資訊卡（連線/分組/排程/保留數/最近備份），右側備份路徑列表（區分 `manual` / `template` badge，含新增與移除）；Admin 可見「測試 SSH 連線」按鈕，fetch `/test-connection` 並以 spinner + 結果 icon 呈現（攜帶 `X-CSRFToken` header）
- 仍沿用獨立頁面樣式，待 Phase 13 整合 `base.html`

## 2026-04-14（Phase 4 — 分組與權限模組）

### 表單（app/groups/forms.py）

- 建立 `GroupForm`：name（必填，≤100）、description（選填，≤256）、members（`_MultiCheckboxField`，勾選 User 指派至該分組）
- `_MultiCheckboxField`：繼承 `SelectMultipleField`，以 `ListWidget + CheckboxInput` 渲染為 checkbox 清單，`coerce=int`

### 權限裝飾器（app/groups/decorators.py）

- `admin_required`：包裝 `@login_required`，非 Admin 直接 `abort(403)`
- `user_can_access(obj)` 工具：Admin 全通；一般使用者需 `obj.group_id in current_user.group_ids`；`group_id=None` 僅 Admin 可存取
- `require_group_access(loader)`：由 loader 載入 Host/Device 後檢查 `user_can_access`，被包裝函式會收到 `obj` 作為第一參數

### 路由（app/groups/routes.py，全部 `@admin_required`）

- `GET /`：列出分組，預先以 `GROUP BY` 統計 host/device 數量，加上 `g.users.count()` 成員數
- `GET/POST /create`：新建分組，含名稱唯一性檢查、成員指派
- `GET/POST /<id>/edit`：編輯分組，GET 時預填 `members`，提交時以 `User.id.in_()` 覆寫 `group.users`
- `POST /<id>/delete`：阻擋仍關聯 Host/Device 的分組刪除（先提示移出）

### 模板（app/templates/groups/）

- `list.html`：Bootstrap 表格（名稱/描述/成員/主機/設備計數 badge）+ 行內編輯/刪除按鈕（含 `confirm()` 二次確認 + CSRF token）
- `form.html`：create / edit 共用（以 `mode` 變數切換標題與 icon），成員區以可捲動 `.member-list` 容器包住 checkbox 清單
- 沿用 auth/ 獨立頁面樣式（尚未繼承 base.html，Phase 13 後再整合）

## 2026-04-14（Phase 3 — 驗證模組）

### 表單（app/auth/forms.py）

- 建立 `LoginForm`：username / password / remember / submit，含長度驗證
- 建立 `SetupForm`：首次啟動建立 Admin（username / email / password / password_confirm），密碼 ≥8 碼且需二次確認一致

### 路由（app/auth/routes.py）

- `/login`（GET/POST）：驗證帳密 → `login_user()` → 寫入 `LoginLog(action='login')`（成功/失敗都記錄，失敗 user_id=None）；支援 `?next=` 只允許站內相對路徑；尚無任何 User 時自動導向 `/setup`
- `/logout`（需登入）：`logout_user()` + `LoginLog(action='logout')`
- `/setup`（GET/POST）：僅在無任何 User 時可用，建立後自動登入並導向 dashboard；已有使用者則重導 `/login`
- 共用工具 `_client_ip()` 優先讀 `X-Forwarded-For`（配合 `ProxyFix`）、`_log(user_id, username, action, status)` 寫入 `LoginLog`

### 模板（app/templates/auth/）

- `login.html` / `setup.html`：Bootstrap 5.3 + Bootstrap Icons 獨立頁面（未繼承 base.html，Phase 13 後再整合）
- Flash messages 以 `alert-{category}` 顯示
- WTForms 錯誤於欄位下方以 `.text-danger.small` 逐行顯示

### Flask 整合

- `before_request` 守衛（Phase 1 已建立）驗證通過：無使用者 / DB 未初始化時自動導向 `/auth/setup`，放行 endpoint: `auth.setup`、`auth.login`、`static`

## 2026-04-14（Phase 2 — 資料庫層）

### 資料模型（app/models.py）

- 建立 13 張資料表的 SQLAlchemy Model：
  - **權限** — `User`（含 is_admin、password_hash）、`Group`（細粒度分組）、`user_groups`（User ↔ Group 多對多）
  - **主機類型模板** — `HostTemplate`（Web Server / DB Server 等）+ `HostTemplatePath`（預設路徑清單）
  - **Linux 主機** — `Host`（含加密密碼 `password_enc`、group_id、嵌入式排程欄位 cron_expr / retain_count / next_run / last_run）+ `HostFilePath`（實際備份路徑，支援 Glob，source='manual'|'template'）
  - **網路設備** — `Device`（含 vendor、`enable_password_enc`、自訂 `backup_command`；`effective_command` property 自動 fallback 至廠商預設）
  - **備份執行** — `BackupRun`（一次執行，含 status / triggered_by / file_count）+ `BackupRecord`（單檔案快照，含 checksum / storage_path）
  - **告警與日誌** — `BackupAlert`（未讀 Dashboard 告警）、`LoginLog`（登入/登出活動紀錄）
  - **設定 KV** — `AppSetting`
- 加入常數：`DEVICE_VENDORS`、`VENDOR_LABEL`、`VENDOR_DEFAULT_COMMAND`（Cisco/Aruba: `show running-config`、Palo Alto: `show config running`）
- `Device.effective_command` property：有自訂指令則用之，否則回傳廠商預設
- `User.group_ids` property：方便 route 層過濾使用者可存取的 Host/Device
- cascade delete：Host/Device → BackupRun → BackupRecord + BackupAlert，HostTemplate → HostTemplatePath，Host → HostFilePath

### Flask-Migrate 初始化

- 在 `app/__init__.py` `create_app()` 內 `from app import models`，讓 Alembic autogenerate 能掃描到 metadata
- 執行 `flask db init` 建立 `migrations/` 目錄
- 執行 `flask db migrate -m "initial schema"` 產生 `migrations/versions/86aacfb3da11_initial_schema.py`（13 張表 + 所有索引）
- 執行 `flask db upgrade` 於 `data/sqlite.db` 建立所有表
- 修正 `.env`：移除相對路徑的 `DATABASE_URL`（改用 `config.py` 內 `__file__` 計算的絕對路徑，避免 Flask-Migrate 執行時 CWD 偏移）

### 環境補強

- 安裝 `tzdata`（Python 3.14 Windows 預設不含 IANA 時區資料庫，ZoneInfo('Asia/Taipei') 會失敗）
- 產生 `.env` 內隨機 SECRET_KEY（`secrets.token_hex(32)`）

## 2026-04-14（Phase 1 — 基礎建設）

### 目錄結構

- 建立完整目錄結構：`app/`（含 8 個 Blueprint 子目錄 + `static/css`、`static/js`、`templates/`）、`scheduler/`、`backups/hosts/`、`backups/devices/`、`data/`、`cron/`、`tests/`
- 各 Blueprint 以 `__init__.py` + `routes.py` stub 建立（auth、dashboard、hosts、devices、groups、backups、compare、settings）

### 依賴與環境設定

- 建立 `requirements.txt`：Flask 3.1、SQLAlchemy、Flask-Login、Flask-Migrate、Flask-WTF、paramiko 3.5、netmiko 4.4、cryptography 44.0、croniter 5.0、python-dotenv
- 建立 `.env.example`：`SECRET_KEY`、`DATABASE_URL`、`CRYPTO_KEY`（含產生指令註解）、`DISPLAY_TZ`、`BACKUP_BASE_PATH`
- 建立 `.gitignore`：排除 `__pycache__/`、`.env`、`data/*.db`、`backups/hosts/*`、`backups/devices/*`（保留 `.gitkeep`）

### Flask 應用核心

- 建立 `run.py`（`app.run(host='0.0.0.0', debug=True)`）
- 建立 `app/config.py`：從 .env 載入設定，含 `APPLICATION_ROOT='/it-manager'`、`CRYPTO_KEY`、`BACKUP_BASE_PATH`、`DISPLAY_TZ`，DATABASE_URL 使用絕對路徑計算（解決 Alembic env.py CWD 問題）
- 建立 `app/__init__.py`（`create_app()` 工廠函式）：
  - 初始化 db / login_manager / migrate / csrf
  - `ProxyFix` 處理 nginx reverse proxy headers
  - 自動建立 `data/`、`backups/hosts/`、`backups/devices/` 目錄
  - 註冊 8 個 Blueprint，統一 `url_prefix=/it-manager/{name}`
  - `before_request` 守衛：無使用者或 DB 未初始化時導向 `/auth/setup`
  - `/` 根路由重導至 `dashboard.index`
  - 全域 `localtime` template filter（UTC → `Asia/Taipei`）

### 共用工具

- 建立 `app/crypto.py`：Fernet 加/解密（`encrypt` / `decrypt` / `safe_decrypt`），從 `current_app.config['CRYPTO_KEY']` 讀取金鑰，未設定時拋出含指令提示的錯誤訊息
- 建立 `app/settings_store.py`：`get_setting` / `set_setting` / `get_smtp_cfg` / `get_ssh_timeout` / `get_netmiko_timeout`；`DYNAMIC_KEYS` 含 SMTP、逾時、密碼政策；支援 Flask 路由（session=None）與獨立 scheduler 進程（傳入 session）

## 2026-04-14（需求分析與規劃）

### 需求確認

- 確認備份觸發方式：排程自動備份（Cron）
- 確認連線方式：SSH 密碼認證（Paramiko）+ Netmiko（網路設備 CLI）
- 確認版本保留策略：每台設備/主機保留最近 N 個版本，舊版自動清除
- 確認備份路徑支援：固定路徑清單 + 主機類型模板 + Glob 萬用字元
- 確認差異比較：Side-by-side 並列（diff2html 前端渲染）
- 確認失敗通知：Email 告警 + Web UI Dashboard 告警 badge
- 確認設備備份指令：先用廠商預設指令（Cisco: show running-config / Aruba: show running-config / Palo Alto: show config running），後續擴充每台自訂
- 確認權限管理：多使用者 + 細粒度（Host/Device 依分組授權，User 只能看所屬 Group）

### 技術架構規劃

- 確認技術棧：Python 3.12 + Flask + SQLAlchemy + SQLite（與 task-manager 一致）
- 確認加密方案：Fernet（`cryptography` 套件）加密 SSH/設備密碼
- 確認備份儲存：檔案系統（`backups/hosts/{id}/` + `backups/devices/{id}/`），非 DB TEXT 欄位
- 確認 Blueprint 架構：auth / dashboard / hosts / devices / groups / backups / compare / settings
- 確認排程器架構：`scheduler/runner.py` + `ssh_backup.py` + `netmiko_backup.py` + `notifier.py`
- 建立 `docs/Todo.md` 完整 15 Phase 實作待辦清單
