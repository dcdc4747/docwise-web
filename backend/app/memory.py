"""记忆的**服务层**（M7）：读取启用中的偏好，并把它变成「请求前注入」的那一段。

两件事分开写，是为了各自能单测：

1. `resolve_active(db, user_id)` —— 取出这个人**启用中**的偏好（术语 + 引用格式），
   并把取到的条目 `hits += 1`（"这条真被用上过几次"的账）；
2. `enrich(terms, cite, corpus)` —— 把偏好变成提示词里的一段约束。

⚠️ **它就是任务卡 D8 里那个 `_enrich()`**：卡上写的是"记忆 L1 + `_enrich()` 请求前注入"，
所以这里沿用卡上的名字（`enrich` / `_enrich` 同一个东西，见文件末尾的别名）。

⚠️ **三条护栏**（都是"别让记忆把正经事弄坏"）：

- **只注入这篇里真的出现过的术语**：不出现的塞进去纯属浪费预算，还会干扰模型。
  判据是**子串命中**（大小写不敏感）——宁可少注入一条，也不塞一条不相关的。
- **有上限**：最多 `MAX_TERMS` 条（默认 40）。记忆是会长大的，提示词预算是有限的。
- ⚠️ **绝不改出处口径**：记忆只影响**用词与格式**，
  `source_block_ids` 仍必须确实支撑结论（提示词里明确写这一句，
  否则模型会以为"有记忆就不用给出处了"）。
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MemoryItem

logger = logging.getLogger(__name__)

# 一次注入最多带多少条术语（记忆会长大，提示词预算是有限的）
MAX_TERMS = 40

# 引用格式标识 → 给模型看的人话
_CITE_LABELS = {
    "author-year": "作者-年份（如 Smith, 2020）",
    "numeric": "数字编号（如 [1] [2]）",
    "footnote": "脚注编号",
}


def resolve_active(db: Session, user_id: int) -> dict:
    """取出这个人**启用中**的偏好 → `{"terms": {原文: 译法}, "cite": str|None}`。

    ⚠️ 取到就 `hits += 1`：调用这个函数**意味着"要拿去用了"**，所以计数在读取处。
    计数写失败**不影响返回值**——不能因为记不上账就把偏好丢了。
    """
    rows = db.scalars(
        select(MemoryItem).where(
            MemoryItem.user_id == user_id, MemoryItem.enabled.is_(True)
        )
    ).all()

    terms: dict[str, str] = {}
    cite: str | None = None
    for row in rows:
        if row.kind == "term":
            terms[row.source] = row.target
        elif row.kind == "cite":
            cite = row.target
        row.hits = (row.hits or 0) + 1

    if rows:
        try:
            db.commit()
        except Exception:  # noqa: BLE001 - 计数只是账，不该阻断注入
            db.rollback()
            logger.exception("记忆命中计数失败：user=%s", user_id)
    return {"terms": terms, "cite": cite}


def enrich(
    terms: dict[str, str] | None = None,
    cite: str | None = None,
    corpus: str = "",
) -> str:
    """把偏好变成要拼到系统提示词后面的一段话（**没有可注入的就返回空串**）。

    `corpus` 是这一趟真正要发给模型的文本：**只注入在这段文本里出现过的术语**。

    ⚠️ **判据是"原文词**或**译法"任一对上**——这条是踩出来的，别改成只比原文：
    库里记的是**原文词**（`chiral`），而问答/导读发给模型的正文是**中文译文**
    （"手性分子"）。只比原文词的话，外文文献那条路**几乎永远匹配不上**，
    这个注入就等于没接（第一版就是这么错的，集成用例当场红）。
    反过来，中文文献或未译文本里出现的是原文词，所以两头都要看。
    """
    lines: list[str] = []

    if terms:
        low = corpus.lower()
        hit = [
            (src, dst)
            for src, dst in terms.items()
            if (src and src.lower() in low) or (dst and dst.lower() in low)
        ]
        if hit:
            pairs = "；".join(f"{src} → {dst}" for src, dst in hit[:MAX_TERMS])
            lines.append(f"【术语偏好】用户已固定以下译名，**必须沿用**：{pairs}")

    if cite:
        label = _CITE_LABELS.get(cite, cite)
        lines.append(f"【引用格式偏好】{label}（标识 `{cite}`）")

    if not lines:
        return ""

    lines.append(
        "（以上只是**用词与格式**的偏好："
        "`source_block_ids` 仍必须确实支撑结论，**不因为有偏好而放宽出处要求**。）"
    )
    return "\n\n" + "\n".join(lines)


# 任务卡 D8 里点名的那个名字，留一个别名，免得看文档的人找不到
_enrich = enrich
