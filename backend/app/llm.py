from __future__ import annotations

import json
import re

import httpx

from .config import settings

_DEEPSEEK_URL = (settings.deepseek_base_url or "https://api.deepseek.com").rstrip("/")

_SYSTEM_PROMPT = (
    "你是一个学术文献理解助手。给你一篇论文的分段文字，每段以 [block_id] 开头标记。"
    "请提取结构导读与术语表。只输出一个 JSON 对象，不要任何额外文字。JSON 结构：\n"
    "{\n"
    '  "research_question": {"text": "研究问题", "source_block_ids": ["b1"]},\n'
    '  "method": {"text": "研究方法", "source_block_ids": ["b5"]},\n'
    '  "conclusion": {"text": "主要结论", "source_block_ids": ["b9"]},\n'
    '  "innovation": {"text": "创新点", "source_block_ids": ["b3"]},\n'
    '  "contribution": {"text": "核心贡献", "source_block_ids": ["b9"]},\n'
    '  "terms": [{"term": "英文术语", "cn": "中文译名", "definition": "释义"}]\n'
    "}\n"
    "要点：source_block_ids 必须确实支撑该结论；导读忠实原文；"
    "terms 只取关键术语并给统一中文译名。"
)

_QA_SYSTEM_PROMPT = (
    "你是一个学术论文问答助手。你会收到论文的分段文字，每段以 [block_id] 开头标记。"
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


def _extract_json(text: str) -> dict:
    """健壮地从一个可能带 ``` 围栏/多余文字的响应里解析出 JSON 对象。"""
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
        return json.loads(re.sub(r",\s*([}\]])", r"\1", candidate))


def extract_understanding(blocks: list[tuple[str, str]]) -> dict:
    """从 (block_id, text) 列表抽取结构化导读 + 术语表，返回 dict。

    每个导字段为 {"text": str, "source_block_ids": [str]}，使"点结论→跳回原文块"可溯源。
    """
    labeled = "\n\n".join(f"[{bid}] {txt}" for bid, txt in blocks)
    user_msg = (
        "请分析下面这篇论文的分段文字，输出导读与术语表 JSON"
        "（source_block_ids 用 [block_id]）：\n\n"
        f"{labeled}"
    )
    content = _chat(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]
    )
    return _extract_json(content)


def answer_question(blocks: list[tuple[str, str]], question: str) -> dict:
    """基于 (block_id, text) 片段回答论文问题，返回 {answer, source_block_ids}。

    回答必须按 block_id 引用出处；文本不足时由提示词要求 LLM 诚实说明。
    """
    labeled = "\n\n".join(f"[{bid}] {txt}" for bid, txt in blocks)
    user_msg = f"论文分段文字：\n\n{labeled}\n\n问题：{question}"
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
