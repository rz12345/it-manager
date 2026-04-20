# IT Manager

統一的 IT 運維 Web 平台，整合**組態備份**與**郵件排程**兩大功能域，共用排程引擎、使用者權限系統與告警通知。

---

## 功能概覽

### 組態備份
- **Linux 主機備份**：透過 SSH（Paramiko）依路徑備份，支援 Glob 展開與 sudo 自動送密碼
- **網路設備備份**：透過 Netmiko CLI 備份 Cisco / Aruba / Palo Alto，自動關閉分頁輸出
- **版本保留**：每個目標可設定保留版本數（`retain_count`），自動清除舊版
- **差異比較**：side-by-side unified diff（difflib + diff2html），快速定位變更
- **備份歷史**：可查詢、下載任意歷史版本

### 郵件排程
- **Jinja2 模板**：所見即所得（TinyMCE）編輯，支援變數注入與附件
- **Web 爬蟲**：Playwright + BeautifulSoup4 擷取動態頁面（CSS / regex / JS 三種模式）
- **多模板任務**：單一 Email 任務可依序寄送多封模板，爬蟲內容自動注入
- **測試寄送**：一鍵寄至測試信箱，不影響正式收件者

### 共用基礎設施
- **使用者與分組**：細粒度 Group 存取控制，Admin 可存取全部資源
- **驗證庫（Credential）**：集中管理 SSH / 設備帳密，Fernet 加密儲存，主機/設備透過 FK 引用
- **排程引擎**：Cron → `scheduler/runner.py`，備份任務 ThreadPoolExecutor 併發，Email 任務主執行緒（Playwright 限制）
- **告警通知**：任務失敗自動發送 SMTP 告警，儀表板顯示未讀 badge
- **系統設定**：SMTP、SSH 逾時、密碼政策等，由 Admin 於 Web UI 管理

---

## 技術棧

| 層次 | 技術 |
|---|---|
| 後端框架 | Python 3.12 + Flask + SQLAlchemy（single-table inheritance） |
| 資料庫 | SQLite（`data/sqlite.db`）+ Flask-Migrate |
| 排程 | Ubuntu Cron → `scheduler/runner.py` |
| SSH 備份 | Paramiko |
| 設備備份 | Netmiko（Cisco / Aruba / Palo Alto） |
| Email | smtplib + Jinja2 + MIMEMultipart |
| Web 爬蟲 | Playwright（Chromium）+ BeautifulSoup4 + lxml |
| 密碼加密 | cryptography.fernet |
| 差異比較 | difflib + diff2html |
| 前端 | Jinja2 + Bootstrap 5.3 + Bootstrap Icons + Chart.js |

---

## 快速開始

### 需求
- Python 3.12+
- Ubuntu 22.04 / 24.04（生產環境）或 Windows（開發環境）

### 安裝

```bash
# 克隆專案
git clone <REPO_URL> /opt/it-manager
cd /opt/it-manager

# 建立虛擬環境
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安裝依賴
pip install -r requirements.txt
python -m playwright install chromium
```

### 設定 `.env`

```bash
cp .env.example .env
```

| 變數 | 說明 |
|---|---|
| `SECRET_KEY` | Flask session 加密金鑰 |
| `CRYPTO_KEY` | Fernet 金鑰（SSH / 設備密碼加密，**不可事後更換**） |
| `DATABASE_URL` | 預設 `sqlite:///data/sqlite.db` |
| `DISPLAY_TZ` | 前端顯示時區，預設 `Asia/Taipei` |

產生金鑰：

```bash
# SECRET_KEY
python -c "import secrets; print(secrets.token_hex(32))"

# CRYPTO_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> **重要**：`CRYPTO_KEY` 一旦寫入任何密碼後即不可更換，請備份 `.env` 至安全位置。

### 初始化資料庫

```bash
export FLASK_APP=run.py
flask db upgrade
flask hosts seed-templates   # 建立 Web / DB / General 預設主機類型模板
```

### 開發啟動

```bash
python run.py
# 瀏覽器開啟 http://localhost:5000/it-manager/
# 首次進入會導向 /auth/setup 建立 Admin 帳號
```

---

## 部署（Ubuntu + gunicorn + nginx）

完整部署步驟請參考 [`docs/Deploy.md`](docs/Deploy.md)，概要如下：

1. 安裝 gunicorn：`pip install gunicorn`
2. 建立 systemd service（監聽 `127.0.0.1:8018`）
3. nginx 反向代理至 `/it-manager/`
4. 設定 cron 每分鐘執行排程器：
   ```cron
   * * * * * cd /opt/it-manager && /opt/it-manager/venv/bin/python -m scheduler.runner >> data/scheduler.log 2>&1
   ```

---

## 常用指令

```bash
# 手動觸發排程（測試）
python -m scheduler.runner

# 建立管理者帳號
flask auth create-user --admin

# 清理孤立備份檔
flask backups clean --mode orphans --dry-run
flask backups clean --mode orphans --yes

# 升級資料庫 schema
flask db upgrade
```

---

## 目錄結構

```
it-manager/
├── app/                  # Flask Blueprint 架構（auth/dashboard/hosts/devices/...）
├── scheduler/            # 排程腳本（runner/ssh_backup/netmiko_backup/email_task/...）
├── backups/              # 備份檔案（hosts/{id}/ + devices/{id}/）
├── data/                 # SQLite DB + 郵件模板 HTML + 上傳附件
├── migrations/           # Flask-Migrate 版本
├── cron/                 # crontab 範本
├── docs/                 # 補充文件（Architecture / Commands / Deploy / Todo / Task）
├── tests/
├── run.py                # 開發啟動入口
└── requirements.txt
```

詳細架構說明見 [`docs/Architecture.md`](docs/Architecture.md)。

---

## 支援廠商

| 廠商 | Netmiko device_type | 預設備份指令 |
|---|---|---|
| Cisco SW | `cisco_ios` | `show running-config` |
| Aruba SW | `aruba_os` | `show running-config` |
| Palo Alto FW | `paloalto_panos` | `show config running` |

> 每台設備可在 Web UI 覆寫備份指令。

---

## 文件索引

| 文件 | 說明 |
|---|---|
| [`docs/Architecture.md`](docs/Architecture.md) | 技術棧、目錄結構、任務模型、權限、廠商預設指令 |
| [`docs/Commands.md`](docs/Commands.md) | 環境變數、常用 CLI、排程觸發 |
| [`docs/Deploy.md`](docs/Deploy.md) | 完整生產環境部署流程 |
| [`docs/Todo.md`](docs/Todo.md) | 當前待辦項目 |
| [`docs/Task.md`](docs/Task.md) | 已完成功能歷史紀錄 |
