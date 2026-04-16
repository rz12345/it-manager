# 常用指令

## 環境變數（.env）

| 變數 | 說明 |
|---|---|
| `SECRET_KEY` | Flask session 加密金鑰 |
| `DATABASE_URL` | 預設 `sqlite:///data/sqlite.db` |
| `CRYPTO_KEY` | Fernet 金鑰，用於加密 DB 中的 SSH/設備密碼 |
| `DISPLAY_TZ` | 前端顯示時區，預設 `Asia/Taipei` |

> SMTP、測試收件者、SSH 逾時、排程併發數、密碼政策等動態設定已移至資料庫，透過 Web UI「系統設定」頁面管理，讀寫工具為 `app/settings_store.py`。
> 完整部署說明見 `docs/Deploy.md`。

## 安裝與啟動

```bash
# 安裝依賴
pip install -r requirements.txt
python -m playwright install chromium   # 首次安裝 Playwright 瀏覽器

# 開發啟動
python run.py
```

## 資料庫與初始化

```bash
# 資料庫遷移
flask db upgrade

# 建立管理者帳號
flask auth create-user --admin

# 建立預設主機類型模板（Web Server / DB Server / General）
flask hosts seed-templates
```

## 備份資料維護

```bash
# 清理備份資料（必須指定 --mode，避免誤刪）
flask backups clean --mode orphans --dry-run
flask backups clean --mode orphans --yes
flask backups clean --mode all
```

## 排程

```bash
# 手動觸發排程（測試用，會同時跑 backup 與 email 任務）
python -m scheduler.runner

# 部署 Cron
crontab cron/crontab.example
```
