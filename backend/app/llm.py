from __future__ import annotations

import json
import logging
import math
import re

import httpx

from .config import settings

logger = logging.getLogger(__name__)

_DEEPSEEK_URL = (settings.deepseek_base_url or "https://api.deepseek.com").rstrip("/")

# 导读的五个字段（也是"JSON 被截断时按字段抢救"的键顺序）
_GUIDE_KEYS = (
    "research_question",
    "method",
    "conclusion",
    "innovation",
    "contribution",
)

_SYSTEM_PROMPT = (
    "你是一个学术文献理解助手。给你一份文献的分段文字（可能是中文，也可能是外文），"
    "每段以 [block_id] 开头标记。"
    "请提取结构导读与术语表。只输出一个 JSON 对象，不要任何额外文字。JSON 结构：\n"
    "{\n"
    '  "research_question": {"text": "研究问题", "source_block_ids": ["b1"]},\n'
    '  "method": {"text": "研究方法", "source_block_ids": ["b5"]},\n'
    '  "conclusion": {"text": "主要结论", "source_block_ids": ["b9"]},\n'
    '  "innovation": {"text": "创新点", "source_block_ids": ["b3"]},\n'
    '  "contribution": {"text": "核心贡献", "source_block_ids": ["b9"]},\n'
    '  "terms": [{"term": "术语原文", "cn": "规范名称", "definition": "释义"}]\n'
    "}\n"
    "要点：source_block_ids 必须确实支撑该结论；导读忠实原文，用中文表述；"
    "terms 只取关键术语——原文是外文时给统一中文译名，原文是中文时给规范术语名与释义。\n"
    "**输出长度有上限**：五个字段每个 ≤120 字；terms ≤15 条，每条释义 ≤60 字。"
    "宁可少写几条，也必须把 JSON 写完整（截断的输出等于没有）。"
)

_QA_SYSTEM_PROMPT = (
    "你是一个学术文献问答助手。你会收到文献的分段文字，每段以 [block_id] 开头标记。"
    "请仅依据给定文本回答用户的问题，不要编造文本中没有的内容。"
    "只输出一个 JSON 对象，不要任何额外文字。JSON 结构：\n"
    '{"answer": "回答（中文，简洁准确）", "source_block_ids": ["b1", "b5"]}\n'
    "要点：source_block_ids 必须是确实支撑该回答的段标记；"
    "如果给定文本不足以回答，answer 里诚实说明文本中没有相关信息，"
    "source_block_ids 为空数组。"
)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.deepseek_api_key}"}


def _chat(
    messages: list[dict],
    max_tokens: int = 2000,
    temperature: float = 0.2,
) -> str:
    payload: dict = {
        "model": settings.deepseek_model or "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    resp = httpx.post(
        f"{_DEEPSEEK_URL}/chat/completions",
        headers=_headers(),
        json=payload,
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _unescape(raw: str) -> str:
    """把正则抓到的 JSON 字符串体还原成真实文本（走 json 自己的转义规则）。"""
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return raw


def _salvage_fields(candidate: str) -> dict:
    """JSON 被截断时的抢救：整体解析不了，但**单个字段完整**的话还能用。

    实测场景：一份 56 页中文文献的文字整篇喂进去后，模型把五个字段写完了、
    在 terms 中途被 max_tokens 截断——这时整体 json.loads 失败，五个字段其实都是好的。
    """
    out: dict = {}
    # 用字符串拼接而不是 % 格式化：模式里本来就有一堆 {}，可读性更好也更不容易写错
    body_pat = (
        r'[^{}]*?"text"\s*:\s*"((?:[^"\\]|\\.)*)"'
        r'[^{}]*?"source_block_ids"\s*:\s*\[([^\]]*)\]'
    )
    for key in _GUIDE_KEYS:
        pattern = r'"' + re.escape(key) + r'"\s*:\s*\{' + body_pat
        match = re.search(pattern, candidate, re.S)
        if not match:
            continue
        ids = [s.strip().strip('"') for s in match.group(2).split(",") if s.strip()]
        out[key] = {"text": _unescape(match.group(1)), "source_block_ids": ids}

    terms = [
        {
            "term": _unescape(m.group(1)),
            "cn": _unescape(m.group(2)),
            "definition": _unescape(m.group(3)),
        }
        for m in re.finditer(
            r'\{\s*"term"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"cn"\s*:\s*"((?:[^"\\]|\\.)*)"'
            r'\s*,\s*"definition"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}',
            candidate,
            re.S,
        )
    ]
    if terms:
        out["terms"] = terms
    return out


def _extract_json(text: str) -> dict:
    """健壮地从一个可能带 ``` 围栏/多余文字/被截断的响应里解析出 JSON 对象。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"响应中未找到 JSON：{text[:200]}")
    candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # 去掉对象/数组尾部的逗号再试一次
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", candidate))
        except json.JSONDecodeError as exc:
            salvaged = _salvage_fields(candidate)
            if salvaged:
                logger.warning(
                    "LLM 返回的 JSON 不完整（%s，响应 %s 字、%s 个字段可抢救）"
                    "——已按字段抢救，缺失部分按「暂无」处理",
                    exc,
                    len(text),
                    len(salvaged),
                )
                return salvaged
            logger.error(
                "LLM 返回的 JSON 无法解析也无法抢救：%s（响应 %s 字）", exc, len(text)
            )
            raise


def _sample_blocks(
    blocks: list[tuple[str, str]], max_chars: int
) -> tuple[list[tuple[str, str]], bool]:
    """整篇超预算时按"均匀抽样"压缩：等间隔取块，首尾必留。

    选均匀抽样而不是"只取前 N 段"：文档的结论/方法往往在末尾，截断式取样会让导读
    只看到开头（实测那篇中文文献开头恰好是审稿回复，噪声最大）。
    """
    total = sum(len(text or "") for _, text in blocks)
    if total <= max_chars or len(blocks) <= 1:
        return list(blocks), False
    keep_every = max(2, math.ceil(total / max_chars))
    selected = [item for index, item in enumerate(blocks) if index % keep_every == 0]
    if selected[-1] != blocks[-1]:
        selected.append(blocks[-1])
    return selected, True


def extract_understanding(blocks: list[tuple[str, str]]) -> dict:
    """从 (block_id, text) 列表抽取结构化导读 + 术语表，返回 dict。

    每个导字段为 {"text": str, "source_block_ids": [str]}，使"点结论→跳回原文块"可溯源。
    整篇超预算时按均匀抽样压缩（见 `_sample_blocks`），并在提示词里说明这是抽样。
    """
    selected, sampled = _sample_blocks(blocks, settings.docwise_understanding_max_chars)
    labeled = "\n\n".join(f"[{bid}] {txt}" for bid, txt in selected)
    note = ""
    if sampled:
        note = (
            f"（注意：这份文献很长，下面是从全篇**均匀抽样**出的 "
            f"{len(selected)}/{len(blocks)} 段；给出处时仍用这些段的 [block_id]）\n\n"
        )
        logger.info(
            "导读输入超预算：%s 段 → 抽样 %s 段（预算 %s 字）",
            len(blocks),
            len(selected),
            settings.docwise_understanding_max_chars,
        )
    user_msg = (
        "请分析下面这份文献的分段文字，输出导读与术语表 JSON"
        "（source_block_ids 用 [block_id]）：\n\n" + note + labeled
    )
    content = _chat(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=settings.docwise_understanding_max_tokens,
    )
    return _extract_json(content)


def answer_question(
    blocks: list[tuple[str, str]],
    question: str,
    focus_block_ids: list[str] | None = None,
) -> dict:
    """基于 (block_id, text) 片段回答论文问题，返回 {answer, source_block_ids}。

    回答必须按 block_id 引用出处；文本不足时由提示词要求 LLM 诚实说明。

    focus_block_ids：用户在阅读区**划词提问**时选中的段落（提问锚点）。
    锚点与出处是同一个坐标系——带上它，模型才知道问题里的"这句话 / 这段"指哪一段，
    回答的出处也才能回到同一段（这是本产品对外那句"每条结论点得回原文那一句"的支撑）。
    """
    labeled = "\n\n".join(f"[{bid}] {txt}" for bid, txt in blocks)
    focus = [str(item) for item in (focus_block_ids or []) if str(item)]
    focus_hint = ""
    if focus:
        # 关键：**把锚点那段的原文贴出来**，而不是只给块编号。
        # 实测（2026-09-14 真接口冒烟）：只给编号时，问"这一段在讲什么？"模型会回
        # "文本中没有提供具体问题内容，无法作答"——它认不出 [p0_b1] 就是"这一段"。
        anchored = [(bid, txt) for bid, txt in blocks if bid in set(focus)]
        quoted = "\n".join(f"[{bid}] {txt}" for bid, txt in anchored)
        focus_hint = (
            "\n\n【提问锚点】用户是在下面这一段（或几段）里划词提问的，"
            "问题里的「这句话 / 这段」指的就是它：\n"
            f"{quoted}\n"
            "请直接针对上面这段内容回答（即使问题很短、很含糊，也要按这段来答），"
            "并让出处包含该段的块标记；确实与它无关时再引用其他段落。"
        )
    user_msg = f"文献分段文字：\n\n{labeled}{focus_hint}\n\n问题：{question}"
    content = _chat(
        [
            {"role": "system", "content": _QA_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=1500,
        temperature=0.2,
    )
    data = _extract_json(content)
    return {
        "answer": str(data.get("answer") or ""),
        "source_block_ids": [str(x) for x in data.get("source_block_ids") or []],
    }
