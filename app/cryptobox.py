# -*- coding: utf-8 -*-
"""cryptobox.py — 접근코드 기반 대칭 암호화(발행/라이트 공용)."""
import base64, hashlib
from cryptography.fernet import Fernet, InvalidToken

_SALT = b"jinhak-analyzer-v1"


def _key(passphrase):
    dk = hashlib.pbkdf2_hmac("sha256", (passphrase or "").encode("utf-8"),
                             _SALT, 200_000, 32)
    return base64.urlsafe_b64encode(dk)


def encrypt(data: bytes, passphrase: str) -> bytes:
    return Fernet(_key(passphrase)).encrypt(data)


def decrypt(token: bytes, passphrase: str):
    """성공 시 bytes, 실패(코드 틀림) 시 None."""
    try:
        return Fernet(_key(passphrase)).decrypt(token)
    except (InvalidToken, Exception):
        return None
