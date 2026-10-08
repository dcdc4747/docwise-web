"""出网环境口径的测试（`app/netenv.py`）。

这个坑一天里咬了两次，所以测试要钉两层：
① 纯函数行为（去方括号、别动代理地址的方括号、幂等）；
② **真的拿 httpx 建一次客户端**——原来 `NO_PROXY` 带 `[::1]` 时它会直接抛
   `ValueError: invalid literal for int() with base 10: ':1]'`（实测 2026-10-08）：
   受害者一是翻译引擎（导入期就崩 → 任何上传都失败），二是后端自己的 DeepSeek 客户端
   （提问直接 HTTP 500）。只测字符串不够——这个 bug 的本质是"httpx 会不会炸"。
"""

from __future__ import annotations

import os

import httpx

from app.netenv import sanitize_proxy_env


def test_sanitize_strips_brackets_from_ipv6_entries() -> None:
    env = {
        "NO_PROXY": "127.0.0.1,localhost,::1,[::1]",
        "no_proxy": "[2001:db8::1]:8080,example.com",
        # 代理地址里的方括号是**合法且必要**的，不许动
        "HTTP_PROXY": "http://[::1]:7897",
        "HTTPS_PROXY": "socks5://127.0.0.1:7897",
    }
    changed = sanitize_proxy_env(env)

    assert env["NO_PROXY"] == "127.0.0.1,localhost,::1,::1"
    assert env["no_proxy"] == "2001:db8::1:8080,example.com"
    assert env["HTTP_PROXY"] == "http://[::1]:7897"
    assert env["HTTPS_PROXY"] == "socks5://127.0.0.1:7897"
    assert sorted(changed) == ["NO_PROXY", "no_proxy"]


def test_sanitize_is_idempotent_and_ignores_plain_values() -> None:
    env = {"PATH": "/usr/bin", "NO_PROXY": "127.0.0.1,localhost,::1"}
    assert sanitize_proxy_env(env) == []
    assert env["NO_PROXY"] == "127.0.0.1,localhost,::1"
    assert env["PATH"] == "/usr/bin"


def test_httpx_client_survives_the_sanitized_env(monkeypatch) -> None:
    """洗完环境后，httpx 能正常建客户端（这是"提问不再 500"的机制层证据）。"""
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost,::1,[::1]")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7897")
    sanitize_proxy_env()  # 不传 env = 洗当前进程的 os.environ

    assert "[::1]" not in os.environ["NO_PROXY"]
    with httpx.Client(timeout=1) as client:  # 原来这一行就会抛 ValueError
        assert client is not None
