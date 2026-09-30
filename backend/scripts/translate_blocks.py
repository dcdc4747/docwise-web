"""逐段翻译脚本：给一批已经取好字的段落补上译文（扫描件这条路要用）。

为什么单独一个脚本：扫描件没有文字层，翻译引擎（需要文字层才能排版）用不了，
所以"扫描版外文文献"只能走 **OCR 取字 → 逐段翻译**：拿不到重排版式的 PDF，
但段落视图能读到中文、问答与检索也有中文上下文。这里只做"把段落译成目标语言"这件事，
取字由 `ocr_blocks.py` 负责，两者拼起来才是完整的一条路。

三条纪律：

1. **批量送、编号回**：一批若干段，提示词要求"逐段译、保持编号、只输出 JSON"，
   回来按编号贴回原段——不做位置对齐（位置对齐会错位，错位比漏译更糟）。
2. **不编**：某批失败或某段没回来，那段就留空并打印出来；**绝不用原文/机翻占位**，
   界面会如实显示"这段没有译文"。
3. **温度 0**：翻译要可复现，不要创作。

用法（独立跑，把译文写回已有的 result.json）：
    python translate_blocks.py --result <result.json> [--lang-in en] [--lang-out zh]
依赖环境变量：DEEPSEEK_API_KEY / DEEPSEEK_MODEL / DEEPSEEK_BASE_URL
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-v4-flash"
# 一批送多少段：太小费往返，太大容易触发输出截断（截断=整批白跑）
BATCH_SIZE = 8
# 单批超时（秒）
TIMEOUT = 120
# 单段最长字符数：超长的先截断再送（宁可少译一点，也别让整批失败）
MAX_CHARS = 4000

SYSTEM_PROMPT = (
    "你是学术文献翻译。用户给你若干编号段落，逐段译成目标语言。"
    "只输出 JSON 数组，每项形如 {\"i\": 编号, \"t\": 译文}，"
    "不要解释、不要加代码块标记。"
    "必须一段对一段：不合并、不拆分、不跳过、不调整顺序。"
    "术语按学术惯例译，保持客观文体；数字、公式、引用标记原样保留。"
)


def build_messages(
    batch: list[tuple[int, str]], target_lang: str
) -> list[dict[str, str]]:
    """构造一次请求的消息（纯函数，可单测）。"""
    lines = []
    for index, text in batch:
        # 单段过长先截断：宁可少译一点，也别让整批因为输出被截断而白跑
        lines.append(f"[{index}] {text[:MAX_CHARS]}")
    user = (
        f"目标语言：{target_lang}\n"
        f"共 {len(batch)} 段，编号从 {batch[0][0]} 到 {batch[-1][0]}。\n\n"
        + "\n\n".join(lines)
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def parse_translations(raw: str, expected: list[int]) -> dict[int, str]:
    """从模型回复里取出 {编号: 译文}（纯函数，可单测）。

    容错：允许代码块包裹、允许外层是对象（取其中的数组）、允许 i/t 写成 index/text。
    只认 expected 里的编号——模型多给的、编号编出来的一律丢掉。
    """
    if not raw:
        return {}
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\[.*\])", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
            except json.JSONDecodeError:
                return {}
    if isinstance(data, dict):
        for key in ("translations", "items", "data", "result"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        return {}

    wanted = set(expected)
    out: dict[int, str] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        index = item.get("i", item.get("index", item.get("id")))
        translation = item.get("t", item.get("text", item.get("translation")))
        try:
            index = int(index)
        except (TypeError, ValueError):
            continue
        if index in wanted and isinstance(translation, str) and translation.strip():
            out[index] = translation.strip()
    return out


def _chat(
    messages: list[dict[str, str]],
    *,
    api_key: str,
    model: str,
    base_url: str,
    timeout: int = TIMEOUT,
) -> str:
    payload = json.dumps(
        {"model": model, "messages": messages, "temperature": 0, "stream": False}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"] or ""


def translate_blocks(
    blocks: list[dict],
    *,
    source_lang: str,
    target_lang: str,
    batch_size: int = BATCH_SIZE,
    on_batch=None,
) -> tuple[int, list[str]]:
    """给 `blocks` 就地补 `translated`。返回 `(译出多少段, 失败原因列表)`。

    `blocks` 是 `[{"block_id", "text", ...}]`；**没译出来的段保持 translated=None**，
    调用方与界面据此如实显示"这段没有译文"，绝不填占位。
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return 0, ["未配置 DEEPSEEK_API_KEY，无法翻译（扫描件走的是逐段翻译这条路）"]
    model = os.environ.get("DEEPSEEK_MODEL") or DEFAULT_MODEL
    base_url = os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL

    targets = [
        (index, item["text"])
        for index, item in enumerate(blocks)
        if (item.get("text") or "").strip()
        and not (item.get("translated") or "").strip()
    ]
    if not targets:
        return 0, []

    done = 0
    problems: list[str] = []
    total_batches = (len(targets) + batch_size - 1) // batch_size
    for start in range(0, len(targets), batch_size):
        batch = targets[start : start + batch_size]
        indices = [index for index, _ in batch]
        label = f"第 {start // batch_size + 1}/{total_batches} 批（{len(batch)} 段）"
        try:
            raw = _chat(
                build_messages(batch, target_lang),
                api_key=api_key,
                model=model,
                base_url=base_url,
            )
            got = parse_translations(raw, indices)
        except Exception as exc:  # noqa: BLE001 - 单批失败不该毁掉整篇
            problems.append(f"{label} 失败：{exc}")
            got = {}
        for index, translation in got.items():
            blocks[index]["translated"] = translation
        missing = [index for index in indices if index not in got]
        if missing:
            problems.append(f"{label} 有 {len(missing)} 段没译出来")
        done += len(got)
        if on_batch is not None:
            on_batch(start // batch_size + 1, total_batches)

    print(
        f"[translate] 逐段翻译：{done}/{len(targets)} 段译出"
        + (f"，问题 {len(problems)} 条" if problems else ""),
        flush=True,
    )
    for problem in problems:
        print(f"[translate] {problem}", file=sys.stderr, flush=True)
    return done, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="给 result.json 里的段落补译文")
    parser.add_argument("--result", required=True, help="result.json 路径")
    parser.add_argument("--lang-in", default="en")
    parser.add_argument("--lang-out", default="zh")
    args = parser.parse_args(argv)

    path = Path(args.result)
    payload = json.loads(path.read_text(encoding="utf-8"))
    blocks = payload.get("blocks") or []
    if not blocks:
        print("[translate] result.json 里没有块，没什么可译的", file=sys.stderr)
        return 1

    done, problems = translate_blocks(
        blocks, source_lang=args.lang_in, target_lang=args.lang_out
    )
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(
        f"[translate] 写回 {path}：{done} 段有译文，{len(problems)} 条问题",
        flush=True,
    )
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
