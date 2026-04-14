# 部署指引

適用環境：Ubuntu 22.04 / 24.04（Python 3.12+）+ nginx 反向代理 + cron 排程。

---

## 1. 系統需求

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git nginx
```

> Python 3.14 Windows 需額外 `pip install tzdata` 才能 `ZoneInfo('Asia/Taipei')`；Ubuntu 自帶 `tzdata`。

---

## 2. 取得原始碼

```bash
sudo mkdir -p /opt/config-manager
sudo chown "$USER":"$USER" /opt/config-manager
git clone <REPO_URL> /opt/config-manager
cd /opt/config-manager
```

---

## 3. 建立虛擬環境 + 安裝依賴

```bash
cd /opt/config-manager
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 4. 設定 `.env`

```bash
cp .env.example .env

# 產生 SECRET_KEY
python -c "import secrets; print(secrets.token_hex(32))"

# 產生 CRYPTO_KEY（Fernet）— 後續所有 SSH/設備密碼加密皆依賴此金鑰
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 將兩個值填入 .env
nano .env
```

關鍵欄位：

| 變數 | 值 |
|---|---|
| `SECRET_KEY` | 上述 `token_hex(32)` 輸出 |
| `CRYPTO_KEY` | 上述 `Fernet.generate_key()` 輸出 |
| `DATABASE_URL` | 保留預設 `sqlite:///data/config_manager.db`（絕對路徑） |
| `BACKUP_BASE_PATH` | 預設專案內 `backups/`；生產環境建議 `/var/lib/config-manager/backups` |
| `DISPLAY_TZ` | `Asia/Taipei` |

> **重要**：`CRYPTO_KEY` 一旦建立並寫入任何密碼後即不可更換，否則無法解密既有資料。備份 `.env` 至安全位置。

---

## 5. 初始化資料庫

```bash
cd /opt/config-manager
source venv/bin/activate
export FLASK_APP=run.py
flask db upgrade
flask hosts seed-templates   # 建立 Web / DB / General 預設主機類型模板
```

開發期可執行 `python run.py` 以 5000 port 啟動確認，開瀏覽器首次進入會自動導向 `/config-manager/auth/setup` 建立 Admin 帳號。

---

## 6. 佈署 WSGI（systemd + gunicorn）

```bash
source venv/bin/activate
pip install gunicorn
```

建立 `/etc/systemd/system/config-manager.service`：

```ini
[Unit]
Description=Config Manager (Flask + Gunicorn)
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/config-manager
Environment="PATH=/opt/config-manager/venv/bin"
ExecStart=/opt/config-manager/venv/bin/gunicorn \
    --workers 3 \
    --bind 127.0.0.1:8017 \
    --access-logfile /opt/config-manager/data/access.log \
    --error-logfile /opt/config-manager/data/error.log \
    "run:app"
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

啟動：

```bash
sudo chown -R www-data:www-data /opt/config-manager/data /opt/config-manager/backups
sudo systemctl daemon-reload
sudo systemctl enable --now config-manager
sudo systemctl status config-manager
```

---

## 7. nginx 反向代理

`/etc/nginx/sites-available/config-manager`：

```nginx
location /config-manager/ {
    proxy_pass         http://127.0.0.1:8017/config-manager/;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Real-IP         $remote_addr;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_set_header   X-Forwarded-Prefix /config-manager;
    proxy_read_timeout 300;
    client_max_body_size 20m;
}
```

啟用並測試：

```bash
sudo ln -s /etc/nginx/sites-available/config-manager /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

對外網址：`https://<DOMAIN>/config-manager/`

---

## 8. 排程 Cron（備份排程器）

編輯 `cron/crontab.example` 內的 `<PROJECT_PATH>` 與 `<VENV_PY>`，或直接以下列指令安裝：

```bash
# 以 www-data 身分執行（權限與 systemd 服務一致）
sudo crontab -u www-data -e
```

加入：

```cron
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
* * * * * cd /opt/config-manager && /opt/config-manager/venv/bin/python -m scheduler.runner >> /opt/config-manager/data/scheduler.log 2>&1
```

`scheduler.runner` 每分鐘觸發一次，但只執行 `next_run <= now` 的 Host/Device，實際備份頻率由各目標的 Cron 表達式決定。

測試：

```bash
sudo -u www-data bash -c 'cd /opt/config-manager && venv/bin/python -m scheduler.runner'
tail -f data/scheduler.log
```

---

## 9. 系統設定（Web UI）

以 Admin 登入後至「系統設定」：

- **SMTP**：配置告警信件寄送（失敗/部分失敗的 BackupRun 會自動寄發）
- **連線逾時**：SSH（Paramiko，預設 30s）、Netmiko（預設 60s）
- **密碼政策**：使用者密碼最短長度、字元類別、過期天數

> 備份路徑、分組、使用者授權、排程 cron_expr 等均於對應模組的 Web 頁面設定。

---

## 10. 升級流程

```bash
cd /opt/config-manager
source venv/bin/activate
git pull
pip install -r requirements.txt
flask db upgrade
sudo systemctl restart config-manager
```

---

## 11. 備援與還原

| 資產 | 位置 |
|---|---|
| 應用設定 / 金鑰 | `.env`（尤其 `CRYPTO_KEY`） |
| 資料庫 | `data/config_manager.db` |
| 備份檔案 | `BACKUP_BASE_PATH`（預設 `backups/hosts/`、`backups/devices/`） |
| 排程紀錄 | `data/scheduler.log` |

建議每日 `rsync`：

```bash
rsync -a --delete /opt/config-manager/data/ /opt/config-manager/backups/ /mnt/backup/config-manager/
cp /opt/config-manager/.env /mnt/backup/config-manager/env.backup
```

還原：複製 `.env`、`data/`、`backups/` 至新機後 `flask db upgrade` 即可。

---

## 12. 常見排錯

| 症狀 | 檢查 |
|---|---|
| 登入後頁面 404 | 確認 nginx `proxy_pass` 尾端 `/config-manager/` 斜線完整；`X-Forwarded-Prefix` 有帶上 |
| 登入後 CSRF 錯誤 | 多半為 `SECRET_KEY` 被重啟改寫；固定 `.env` 中 `SECRET_KEY` |
| 備份報 `InvalidToken` | `CRYPTO_KEY` 與寫入密碼時不一致；需還原舊金鑰或重新於 Web UI 編輯每台主機/設備密碼 |
| cron 不執行 | `sudo systemctl status cron`；確認 crontab 對應使用者（`crontab -u www-data -l`）；檢查 `data/scheduler.log` |
| SMTP 送不出 | 系統設定頁填妥 `SMTP_HOST/PORT/FROM/NOTIFY_EMAIL`；防火牆確認允許外連 587/465 |
