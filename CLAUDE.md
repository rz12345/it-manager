# IT Manager — 專案指引

## 專案目的

統一的 IT 運維 Web 平台，整合兩大功能域：

1. **組態備份**：網路設備與 Linux 主機的定期自動備份、版本保留、差異比較
2. **郵件排程**：以 Jinja 模板 + Web 爬蟲擷取動態內容，產生並寄送定期 email（週報、維運通知等）

兩者共用排程引擎（`scheduler/runner.py`）、使用者／權限系統、系統設定與通知告警。

支援目標：
- **Linux 主機**：SSH 連線，備份指定設定檔（固定路徑 / 主機類型模板 / Glob 路徑）
- **網路設備**：Cisco SW、Aruba SW、Palo Alto FW — 透過 Netmiko 取得 running config
- **差異比較**：Side-by-side 並列比較（diff2html），可選取任意兩個版本
- **Email 任務**：多模板順序寄送、爬蟲變數注入、附件綁定、測試寄送

## 技術棧

- **後端**: Python 3.12 + Flask + SQLAlchemy（single-table inheritance）
- **資料庫**: SQLite（`data/sqlite.db`）
- **排程**: Ubuntu Cron → `scheduler/runner.py`（單一主迴圈，分派 backup / email）
- **Linux 主機備份**: Paramiko（SSH 密碼認證）
- **網路設備備份**: Netmiko（Cisco / Aruba / Palo Alto CLI）
- **Email 寄送**: smtplib + Jinja2 + MIMEMultipart（`scheduler/mailer.py`）
- **Web 爬蟲**: Playwright（Chromium）+ BeautifulSoup4 + lxml（CSS / regex / JS 三種擷取模式）
- **密碼加密**: cryptography.fernet（SSH / 設備密碼加密儲存於 DB）
- **差異比較**: difflib（後端 unified diff）+ diff2html（前端 side-by-side 渲染）
- **前端**: Jinja2 模板 + Bootstrap 5.3 + Bootstrap Icons

## 環境變數（.env）

| 變數 | 說明 |
|---|---|
| `SECRET_KEY` | Flask session 加密金鑰 |
| `DATABASE_URL` | 預設 `sqlite:///data/sqlite.db` |
| `CRYPTO_KEY` | Fernet 金鑰，用於加密 DB 中的 SSH/設備密碼 |
| `DISPLAY_TZ` | 前端顯示時區，預設 `Asia/Taipei` |

> SMTP（告警＋email 任務共用）、測試收件者、SSH 逾時、排程併發數、密碼政策等動態設定已移至資料庫，透過 Web UI「系統設定」頁面管理，讀寫工具為 `app/settings_store.py`。

## 常用指令

```bash
# 安裝依賴
pip install -r requirements.txt
python -m playwright install chromium   # 首次安裝 Playwright 瀏覽器

# 開發啟動
python run.py

# 資料庫遷移
flask db upgrade

# 建立管理者帳號
flask auth create-user --admin

# 建立預設主機類型模板（Web Server / DB Server / General）
flask hosts seed-templates

# 清理備份資料（必須指定 --mode，避免誤刪）
flask backups clean --mode orphans --dry-run
flask backups clean --mode orphans --yes
flask backups clean --mode all

# 從舊專案（config-manager + task-manager）匯入資料至新 DB
python -m scripts.migrate_legacy --dry-run
python -m scripts.migrate_legacy

# 手動觸發排程（測試用，會同時跑 backup 與 email 任務）
python -m scheduler.runner

# 部署 Cron
crontab cron/crontab.example
```

## 目錄結構

```
it-manager/
├── app/                        # Flask 應用程式（Blueprint 架構）
│   ├── static/
│   │   ├── css/
│   │   │   ├── tokens.css      # 設計 tokens（亮/暗 CSS variables）
│   │   │   ├── components.css  # 共用元件樣式（page_header/stat_card/responsive table/quick nav）
│   │   │   └── style.css       # legacy 共用樣式（tag chip/row、stat-card 向後相容）
│   │   ├── js/main.js          # Theme manager、Quick Nav、Toast、Confirm Modal、表單 spinner
│   │   └── vendor/             # 本地化前端資產（Bootstrap 5.3.2 / Bootstrap Icons 1.11.3 / Chart.js 4.4.1）
│   ├── templates/
│   │   └── _macros.html        # 共用 Jinja macros（page_header / stat_card / status_badge / empty_row / confirm_delete_form / responsive_table / form_field / submit_button）
│   ├── auth/                   # 登入、登出、初始設定
│   ├── dashboard/              # 首頁儀表板（備份＋email 統計、告警摘要）
│   ├── assets/                 # 資產總覽：hosts / devices / templates 三分頁
│   ├── hosts/                  # Linux 主機 CRUD + 備份路徑 + 主機類型模板
│   ├── devices/                # 網路設備 CRUD（Cisco/Aruba/Palo Alto）
│   ├── groups/                 # 分組管理 + 使用者授權（細粒度權限）
│   ├── credentials/            # 驗證庫：共用 SSH / 設備帳密（Admin 限定）
│   ├── tasks/                  # 備份任務 CRUD（BackupTask，多目標併發）
│   ├── email_tasks/            # Email 任務 CRUD（EmailTask，多模板順序寄送）
│   ├── templates_mgr/          # 郵件模板 CRUD + 附件 + 爬蟲變數綁定
│   ├── scrapers/               # Web 爬蟲 CRUD（CSS / regex / JS 擷取）
│   ├── backups/                # 備份歷史查詢與檔案下載
│   ├── compare/                # 版本差異比較（side-by-side）
│   ├── logs/                   # 使用者登入紀錄 + Email 寄送紀錄
│   ├── settings/               # 系統設定（Admin 專用）
│   ├── config.py               # 環境設定載入
│   ├── crypto.py               # Fernet 加/解密工具
│   ├── models.py               # 所有 SQLAlchemy Models（含 polymorphic）
│   └── settings_store.py       # DB 設定讀寫工具（get_setting / set_setting）
├── scheduler/                  # Cron 排程腳本（獨立於 Flask）
│   ├── runner.py               # 主進入點：依 Task.type 分派 backup / email
│   ├── ssh_backup.py           # Paramiko：Linux 主機備份（含 Glob 展開）
│   ├── netmiko_backup.py       # Netmiko：網路設備 CLI 備份
│   ├── email_task.py           # Email 任務執行（渲染模板、注入爬蟲變數、寄送）
│   ├── mailer.py               # SMTP + MIMEMultipart 寄送（單封 + 重試）
│   ├── scraper.py              # Playwright + BS4 / regex / JS 擷取
│   └── notifier.py             # 失敗告警（SMTP，任務型別不限）
├── scripts/
│   └── migrate_legacy.py       # 一次性：從 config-manager / task-manager 舊 DB 匯入
├── backups/
│   ├── hosts/                  # {host_id}/{timestamp}_{filename}
│   ├── devices/                # {device_id}/{timestamp}_running.cfg
│   └── legacy/                 # 舊專案 DB 備份（遷移完成後可刪）
├── data/                       # SQLite DB + scheduler.lock
│   ├── email_templates/        # 模板 HTML 檔（{template_id}.html）
│   └── uploads/                # 附件儲存（template_{id}/{uuid}_{filename}）
├── cron/                       # crontab 設定範本
├── migrations/                 # Flask-Migrate 版本管理
├── docs/                       # 補充文件
├── tests/
├── run.py                      # 開發啟動入口
└── requirements.txt
```

## 補充文件

需要深入各模組時，載入以下文件：

| 檔案 | 用途 |
|---|---|
| `docs/Todo.md` | 當前待辦項目清單 |
| `docs/Task.md` | 已完成項目歷史紀錄（含日期與分類） |
| `docs/Deploy.md` | 部署說明 |

### 工作階段流程

1. **開始前** — 讀取 `docs/Todo.md` 了解待辦，讀取 `docs/Task.md` 了解已完成歷史
2. **進行中** — 完成的項目從 `docs/Todo.md` 移除
3. **結束時** — 將本次完成的項目整理後**移入 `docs/Task.md`**，標註日期與分類
4. **同步 CLAUDE.md** — 完成項目寫入 `docs/Task.md` 後，檢查是否含有以下類別的異動，若有則同步更新本檔案：
   - 新增或移除的模組／檔案（架構圖）
   - 模組搬移或路徑變更
   - 新建的共用工具（如 crypto、settings_store 等）
   - 新的編碼規範或禁止事項

## 慣例

### 通用
- Blueprint 各自獨立：`auth`、`dashboard`、`assets`、`hosts`、`devices`、`groups`、`credentials`、`tasks`、`email_tasks`、`templates_mgr`、`scrapers`、`backups`、`compare`、`logs`、`settings`
- 所有時間欄位統一使用 UTC，前端顯示時再轉換時區（`DISPLAY_TZ`）
- 所有 SSH / 設備密碼**必須**透過 `app/crypto.py` 的 `encrypt()` / `decrypt()` 存取，禁止明文寫入 DB
- 排程腳本直接存取 DB，不經過 Flask HTTP

### 統一任務模型（重要）
- `Task` / `TaskRun` / `TaskAlert` 為基底，使用 SQLAlchemy **single-table inheritance**（`polymorphic_on='type'`）
- 子類：`BackupTask` / `EmailTask`、`BackupRun` / `EmailRun`；`XxxTask.query` 會自動過濾 `type`
- `scheduler/runner.py` 主迴圈：`Task.query.filter(...)` 抓出到期任務，依 `task.type` 分派：
  - `'backup'` → 以 `ThreadPoolExecutor` 併發跑多目標（上限 `SCHEDULER_MAX_WORKERS`，預設 5）
  - `'email'`  → 主執行緒跑（Playwright 非 thread-safe）
- runner 啟動時：(1) `fcntl.flock` 取得 `data/scheduler.lock` 獨占鎖，被佔用則跳過本輪；(2) 清理 `status='running'` 超過 `3×timeout` 的 orphan `TaskRun` 標為 failed
- `TaskAlert`（原 `BackupAlert`）泛化支援兩種任務型別的告警；Dashboard badge 讀取未讀數量

### Backup 任務
- `BackupTask` 透過 `TaskTarget` (host_id 或 device_id) 指向多目標，`retain_count` 控保留版本數
- 備份檔存放於 `backups/hosts/` 或 `backups/devices/`，DB 只存 `storage_path` + `checksum`
- 網路設備備份（`scheduler/netmiko_backup.py`）連線後會主動嘗試 `no page` / `no paging` / `terminal length 0` 等分頁關閉指令，`send_command` 偵測不到 prompt 時 fallback 到 `send_command_timing`

### 驗證庫（Credential）
- Host / Device 的 SSH 帳密**不再**直接存在各自資料表，一律透過 `credential_id` (FK, NOT NULL) 引用 `Credential`（`name` / `username` / `password_enc` / `enable_password_enc` / `description`）
- 由 `app/credentials/` blueprint 提供 CRUD，**僅 Admin** 可管理；編輯主機/設備時下拉選用
- 密碼欄位仍透過 `app/crypto.py` `encrypt()` / `safe_decrypt()`；讀取範例：`host.credential.username`、`safe_decrypt(device.credential.password_enc)`
- 被引用中的 Credential 不可刪除，需先改用其他驗證

### Email 任務
- `EmailTask` 透過 `TaskTemplate` (帶 `order`) 綁定多個 `EmailTemplate`，依序各發一封
- 模板 body 存放於 `data/email_templates/{template_id}.html`（非資料庫），附件在 `data/uploads/template_{id}/`
- `scraper_vars` 欄位為 `{var_name: scraper_id}` 映射；渲染時取爬蟲 `last_content` 注入 Jinja2 context
- 測試寄送（test-send）會寄至 `TEST_EMAIL` 設定值（非任務實際 `recipients`）

### 權限
- 細粒度權限：`Host` / `Device` / `EmailTask` 透過 `group_id` 與 `User ↔ Group` 多對多關聯控制存取範圍；Admin 可存取所有資源
- 權限檢查統一透過 `app/groups/decorators.py`：`@admin_required`、`@require_group_access(loader)`、`user_can_access(obj)`（duck-type 檢查 `obj.group_id`）
- Email 任務額外容許 `owner_id == current_user.id` 存取（作者本人）

## 網路設備廠商預設指令

| 廠商（vendor） | Netmiko device_type | 預設備份指令 |
|---|---|---|
| Cisco SW | `cisco_ios` | `show running-config` |
| Aruba SW | `aruba_os` | `show running-config` |
| Palo Alto FW | `paloalto_panos` | `show config running` |

> 每台設備可在 `Device.backup_command` 欄位覆寫預設指令（空值則使用上表預設）。

## 整合來源

本專案合併自：
- `Y:/config-manager/`（網路設備與 Linux 主機組態備份）
- `Y:/task-manager/`（Email 排程與 Web 爬蟲）

兩個舊專案的 DB 備份保留於 `backups/legacy/{config_manager,mail_scheduler}.db`，匯入腳本為 `scripts/migrate_legacy.py`（config-manager 在衝突時勝出）。
