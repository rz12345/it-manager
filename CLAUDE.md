# IT Manager — 專案指引

## 專案目的

統一的 IT 運維 Web 平台，整合兩大功能域：

1. **組態備份**：網路設備（Cisco / Aruba / Palo Alto）與 Linux 主機的定期自動備份、版本保留、side-by-side 差異比較
2. **郵件排程**：Jinja 模板 + Web 爬蟲（Playwright）擷取動態內容，產生並寄送定期 email

兩者共用排程引擎（`scheduler/runner.py`）、使用者／權限系統、系統設定與通知告警。

## 補充文件

| 檔案 | 用途 |
|---|---|
| `docs/Architecture.md` | 技術棧、目錄結構、任務/備份/Email/權限細節、廠商預設指令 |
| `docs/Commands.md` | 環境變數、常用 CLI、排程觸發 |
| `docs/Deploy.md` | 部署（Ubuntu + gunicorn + nginx + cron） |
| `docs/Todo.md` | 當前待辦項目清單 |
| `docs/Task.md` | 已完成項目歷史紀錄（含日期與分類） |

### 工作階段流程

1. **開始前** — 讀取 `docs/Todo.md` 了解待辦，讀取 `docs/Task.md` 了解已完成歷史
2. **進行中** — 完成的項目從 `docs/Todo.md` 移除
3. **結束時** — 將本次完成的項目整理後**移入 `docs/Task.md`**，標註日期與分類
4. **同步文件** — 完成項目寫入 `docs/Task.md` 後，檢查是否含有以下類別的異動：
   - 新增或移除的模組／檔案 → 更新 `docs/Architecture.md` 目錄結構
   - 新建的共用工具、新慣例或禁止事項 → 更新本檔案的「核心慣例」
   - 新增 CLI 指令 → 更新 `docs/Commands.md`

## 核心慣例

### 通用（必守）
- Blueprint 各自獨立：`auth`、`dashboard`、`assets`、`hosts`、`devices`、`groups`、`credentials`、`tasks`、`email_tasks`、`templates_mgr`、`scrapers`、`backups`、`compare`、`logs`、`tools`、`settings`
- 所有時間欄位統一使用 UTC，前端顯示時再轉換時區（`DISPLAY_TZ`）
- SSH / 設備密碼**必須**透過 `app/crypto.py` 的 `encrypt()` / `safe_decrypt()` 存取，禁止明文寫入 DB
- 排程腳本（`scheduler/`）直接存取 DB，不經過 Flask HTTP

### 統一任務模型
- `Task` / `TaskRun` / `TaskAlert` 為 polymorphic 基底，子類 `BackupTask` / `EmailTask`（single-table inheritance，`polymorphic_on='type'`）
- `scheduler/runner.py` 依 `task.type` 分派：`backup` 走 ThreadPoolExecutor 併發、`email` 走主執行緒（Playwright 非 thread-safe）
- 以 `data/scheduler.lock` 檔案鎖避免重入；詳見 `docs/Architecture.md`

### 驗證庫（Credential）
- Host / Device **必須**透過 `credential_id` FK 引用 `Credential`（不得在 Host/Device 資料表存帳密）
- `app/credentials/` CRUD 僅 Admin 可操作；被引用中的 Credential 不可刪除

### 權限
- 檢查入口：`app/groups/decorators.py` 的 `@admin_required`、`@require_group_access(loader)`、`user_can_access(obj)`
- `Host` / `Device` / `EmailTask` 透過 `group_id` + User↔Group 多對多控制；Admin 可存取全部，EmailTask 另容許 `owner_id` 本人
