"""用户模型的密钥：**只写不读**，落库时用 HMAC-CTR 流加密 + 完整性标签。

⚠️ 诚实声明：这是**用 stdlib 自研的可逆加密**（HMAC-SHA256 作 keystream），
不是经过审计的 KMS/HSM。它防的是"有人翻数据库文件直接看到明文 key"，
**不防**"拿到进程内存和 `DOCWISE_SECRET` 的人"。默认策略仍是**不落库**（见方案 §八）。

密钥来源：`DOCWISE_SECRET`（环境变量 / .env）。没有它 → 拒绝落库并明说原因，
而不是偷偷用个写死的常量（那等于没加密）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

_NONCE = 16
_TAG = 16


def _keystream(key: bytes, nonce: bytes, size: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < size:
        out.extend(
            hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        )
        counter += 1
    return bytes(out[:size])


def _key_of(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()


def encrypt(plain: str, secret: str) -> str:
    key = _key_of(secret)
    nonce = os.urandom(_NONCE)
    body = plain.encode("utf-8")
    stream = _keystream(key, nonce, len(body))
    cipher = bytes(a ^ b for a, b in zip(body, stream))
    tag = hmac.new(key, nonce + cipher, hashlib.sha256).digest()[:_TAG]
    return base64.urlsafe_b64encode(nonce + tag + cipher).decode("ascii")


def decrypt(blob: str, secret: str) -> str | None:
    """解不开就返回 None（换过 secret / 数据被改过），由上层当作"没配"。"""
    try:
        raw = base64.urlsafe_b64decode(blob.encode("ascii"))
    except Exception:  # noqa: BLE001
        return None
    if len(raw) < _NONCE + _TAG:
        return None
    nonce, tag, cipher = raw[:_NONCE], raw[_NONCE : _NONCE + _TAG], raw[_NONCE + _TAG :]
    key = _key_of(secret)
    expect = hmac.new(key, nonce + cipher, hashlib.sha256).digest()[:_TAG]
    if not hmac.compare_digest(tag, expect):
        return None
    stream = _keystream(key, nonce, len(cipher))
    return bytes(a ^ b for a, b in zip(cipher, stream)).decode("utf-8")


def hint(plain: str) -> str:
    """前端展示用的掩码：只留末四位。"""
    tail = plain[-4:] if len(plain) >= 4 else ""
    return f"…{tail}" if tail else ""
