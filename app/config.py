import os
from dotenv import load_dotenv

load_dotenv()

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_DB = 'sqlite:///' + os.path.join(_BASE_DIR, 'data', 'sqlite.db')
_DEFAULT_BACKUP_PATH = os.path.join(_BASE_DIR, 'backups')


class Config:
    APPLICATION_ROOT = '/it-manager'
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', _DEFAULT_DB)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Fernet 加密金鑰（用於 SSH / 設備密碼加密儲存）
    CRYPTO_KEY = os.environ.get('CRYPTO_KEY', '')

    # 備份檔案儲存根目錄
    BACKUP_BASE_PATH = os.environ.get('BACKUP_BASE_PATH', _DEFAULT_BACKUP_PATH)

    # 顯示時區
    DISPLAY_TZ = os.environ.get('DISPLAY_TZ', 'Asia/Taipei')

    # 郵件模板附件上傳限制（email 任務使用）
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB
    ALLOWED_EXTENSIONS = {'pdf', 'xlsx', 'docx', 'csv', 'png', 'jpg'}
