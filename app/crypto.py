"""
Fernet 加解密工具 — 用於加密儲存於 DB 的 SSH / 網路設備密碼。

金鑰來源：app.config['CRYPTO_KEY']（Fernet 產生的 32 byte url-safe base64 字串）。
產生方式：python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

禁止明文儲存密碼至 DB，所有寫入密碼欄位前必須呼叫 encrypt()，讀取後呼叫 decrypt()。
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _get_fernet() -> Fernet:
    key = current_app.config.get('CRYPTO_KEY', '')
    if not key:
        raise RuntimeError(
            'CRYPTO_KEY 未設定。請在 .env 設定，產生方式：\n'
            '  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    if isinstance(key, str):
        key = key.encode('utf-8')
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """加密明文字串，回傳 base64 密文（可直接存 DB 字串欄位）。"""
    if plaintext is None or plaintext == '':
        return ''
    token = _get_fernet().encrypt(plaintext.encode('utf-8'))
    return token.decode('utf-8')


def decrypt(ciphertext: str) -> str:
    """解密密文字串，回傳明文。密文損毀時拋出 InvalidToken。"""
    if ciphertext is None or ciphertext == '':
        return ''
    return _get_fernet().decrypt(ciphertext.encode('utf-8')).decode('utf-8')


def safe_decrypt(ciphertext: str, default: str = '') -> str:
    """解密失敗時回傳 default（用於資料可能損毀的情境）。"""
    try:
        return decrypt(ciphertext)
    except (InvalidToken, ValueError):
        return default
