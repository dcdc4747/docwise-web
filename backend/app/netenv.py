"""出网环境的口径：**把 `NO_PROXY` 里带方括号的 IPv6 洗掉**。

为什么需要（2026-10-08 实测，一天里踩了两次同样的坑）：

`httpx` 会拿 `NO_PROXY` 的**每一项**去构造 `URLPattern`，而 `[::1]` 这种带方括号的写法
会被它当成"端口 `:1]`"→ 抛 `InvalidURL: Invalid port: ':1]'` / `ValueError`。
机器上装了代理工具时，`NO_PROXY` 里带 `[::1]` 很常见。两个受害者：

1. **翻译引擎子进程**：`pdf2zh/translator.py` 顶部 `import ollama`，ollama 在**导入期**
   就建 httpx 客户端 → **引擎一行代码没跑就崩，任何上传都失败**
   （`app/engine/open_source.py` 在起子进程前调用本模块）；
2. **后端自己**：`app/llm.py` 用 `httpx.post` 调 DeepSeek → 提问直接 **HTTP 500**
   （`app/llm.py` 在导入时调用本模块，早于任何请求）。

只动 `no_proxy` 这一族：`HTTP_PROXY` / `HTTPS_PROXY` 的值本身可能是
`http://[::1]:7897`，那种方括号**合法且必要**，动不得。NO_PROXY 里的 IPv6 按标准本来
就不带方括号，所以去掉是等价改写。Windows 上大小写不敏感、`NO_PROXY` 与 `no_proxy`
可能同时存在（实测 `env:` 枚举会报"相同键重复"），所以按**大小写不敏感**匹配。
"""

from __future__ import annotations

import os
import re
from collections.abc import MutableMapping

# NO_PROXY 里带方括号的 IPv6 项（`[::1]` / `[2001:db8::1]:8080`）
_BRACKETED_IPV6_RE = re.compile(r"^\[([0-9A-Fa-f:]+)\](:\d+)?$")


def sanitize_proxy_env(
    env: MutableMapping[str, str] | None = None,
) -> list[str]:
    """就地把 `no_proxy` 里带方括号的 IPv6 改成标准写法；返回被改动的键名。

    幂等：再跑一次没有方括号可去，返回空列表。传 `env` 时改那一份（子进程环境），
    不传就是当前进程的 `os.environ`。
    """
    target: MutableMapping[str, str] = os.environ if env is None else env
    changed: list[str] = []
    for key in list(target):
        if key.lower() != "no_proxy":
            continue
        raw = target[key]
        items = []
        for item in raw.split(","):
            item = item.strip()
            match = _BRACKETED_IPV6_RE.match(item)
            items.append(f"{match.group(1)}{match.group(2) or ''}" if match else item)
        new = ",".join(items)
        if new != raw:
            target[key] = new
            changed.append(key)
    return changed
