"""D9 · 术语一致率的测量（两种模式，都不改产品代码）。

**模式一 `--baseline`（零成本、随时可跑）**
扫库里已有的导读术语表，跨文献统计：同一个原文词被翻成了几种中文说法。
它回答的是"**没有记忆时**，术语到底有多不一致"——这是 D9 那条判据的**分母来源**。

**模式二 `--ab TASK`（要模型密钥）**
同一篇、同一份文本，只在"有没有注入用户固定的译名"上不同，跑两次导读：
A 无记忆、B 有记忆，看 B 是否**严格沿用**注入的译法。
⚠️ 它要真调模型（每家一次调用），没有可用密钥时**如实失败**，不许编数字。

用法（在仓库根）：

    python backend/scripts/measure_term_consistency.py --baseline
    python backend/scripts/measure_term_consistency.py --ab 6

⚠️ 口径三条（引用这个数时必须一起说）：
1. **一致率 ＝ 跨文献都出现的术语里、"中文说法完全一致"的那部分占比**；
   只统计**在 2 篇及以上**出现过的术语（只出现一次的词谈不上"一致"）；
2. 分母是**术语条数**，不是词频；同一篇里重复出现的词只算一条；
3. 这个数测的是**"同一个词在不同文献里说法是否统一"**，不是翻译准确率。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from glob import glob
from os.path import getmtime

BACKEND_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 控制台是 GBK 时，`⚠️` / `→` 这类字符会直接抛 UnicodeEncodeError（Windows 实测）
sys.stdout.reconfigure(encoding="utf-8")


def _db_path() -> str:
    hits = glob(str(BACKEND_DIR / "data" / "*.db"))
    if not hits:
        raise SystemExit("找不到数据库（backend/data/*.db）")
    return max(hits, key=getmtime)


def _rows() -> list[tuple[int, str, str, str]]:
    """(task_id, filename, terms_json, guide_json)，只取 status=ready 的理解层。"""
    conn = sqlite3.connect(_db_path())
    try:
        return list(
            conn.execute(
                "select t.id, t.filename, u.terms_json, u.guide_json "
                "from task_understanding u join tasks t on t.id = u.task_id "
                "where u.status = 'ready' order by t.id"
            )
        )
    finally:
        conn.close()


def _terms_of(terms_json: str | None, guide_json: str | None) -> list[dict]:
    """术语表可能落在两处（`terms_json` 或 `guide_json.terms`），都认。"""
    for raw in (terms_json, guide_json):
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        terms = data if isinstance(data, list) else data.get("terms")
        if isinstance(terms, list) and terms:
            return terms
    return []


def baseline() -> int:
    """术语一致率（无记忆基线）。

    ⚠️ **按"文件名"分组，不按 task_id**——这是踩出来的口径：
    库里同一份 PDF 往往被跑过好几次（同一个 `filename`、多个 task），
    按 task_id 分组会把"**同一篇重复运行的稳定性**"当成"跨文献一致性"报出去，
    那是把口径说过头了。所以两种分开报：

    - ① **同一文件内部**：不同次运行之间说法稳不稳（可复现性）；
    - ② **不同文件之间**：不同文献之间说法统不统一（这才是 D9 那条判据）。
    """
    per_doc: dict[int, tuple[str, list[dict]]] = {}
    for task_id, filename, terms_json, guide_json in _rows():
        per_doc[task_id] = (filename, _terms_of(terms_json, guide_json))

    # term -> [(filename, cn)]
    by_term: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for _task_id, (filename, terms) in per_doc.items():
        for item in terms:
            term = str(item.get("term") or "").strip().lower()
            cn = str(item.get("cn") or "").strip()
            if term and cn:
                by_term[term].append((filename, cn))

    files = sorted({fn for fn, _ in per_doc.values()})
    print(f"文献（status=ready）：{len(per_doc)} 次运行 / {len(files)} 个不同文件")
    print(f"术语（去重）：{len(by_term)} 条")
    print()

    rerun_terms = {
        t: v for t, v in by_term.items() if len({fn for fn, _ in v}) == 1 and len(v) > 1
    }
    rerun_conflicts = {
        t: v for t, v in rerun_terms.items() if len({cn for _, cn in v}) > 1
    }
    cross_terms = {t: v for t, v in by_term.items() if len({fn for fn, _ in v}) > 1}
    cross_conflicts = {
        t: v for t, v in cross_terms.items() if len({cn for _, cn in v}) > 1
    }

    def rate(shared: dict, conflicts: dict) -> str:
        if not shared:
            return "没有样本（不编一个数）"
        ok = len(shared) - len(conflicts)
        return f"{ok}/{len(shared)} ＝ {ok / len(shared):.0%}"

    print("① **同一文件、多次运行**之间（可复现性）")
    print(
        f"   共现 {len(rerun_terms)} 条，说法不一致 {len(rerun_conflicts)} 条"
        f" → 一致率 {rate(rerun_terms, rerun_conflicts)}"
    )
    for term, pairs in sorted(rerun_conflicts.items()):
        detail = "；".join(f"«{fn}»→{cn}" for fn, cn in pairs)
        print(f"     {term}: {detail}")
    print()

    print("② **不同文件**之间（跨文献一致率 —— D9 那条判据）")
    print(
        f"   共现 {len(cross_terms)} 条，说法不一致 {len(cross_conflicts)} 条"
        f" → 一致率 {rate(cross_terms, cross_conflicts)}"
    )
    for term, pairs in sorted(cross_conflicts.items()):
        detail = "；".join(f"«{fn}»→{cn}" for fn, cn in pairs)
        print(f"     {term}: {detail}")
    print()
    print(
        "口径（引用时必须一起说）：分母是**术语条数**不是词频；"
        "只统计在 2 篇及以上出现过的术语；"
        "这测的是「说法是否统一」，**不是翻译准确率**；"
        "⚠️ 单复数/标点未归一"
        "（`vendor champion` 与 `vendor champions` 会被当成两个词）。"
    )
    return 0


def ab_with_prefs(task_id: int, prefs: dict[str, str]) -> int:
    """有/无记忆对照的**真跑**（只在显式给了 `--pref` 时走这里）。"""
    from app.llm import extract_understanding
    from app.memory import enrich

    conn = sqlite3.connect(_db_path())
    try:
        rows = conn.execute(
            "select block_id, coalesce(translated, text) from task_blocks "
            "where task_id = ? order by id",
            (task_id,),
        ).fetchall()
    finally:
        conn.close()
    items = [(bid, text) for bid, text in rows if text]
    if not items:
        raise SystemExit(f"task {task_id} 没有可用文本")

    corpus = "\n".join(text for _, text in items)
    hint = enrich(prefs, None, corpus)
    if not hint:
        print(
            "⚠️ 注入内容是空的：这些偏好**一条都没在这篇里出现**（判据见 app/memory.py）"
        )
    else:
        print("会拼进 system 提示词的那一段：")
        print(hint)
    print()

    def one(label: str, memory_hint: str) -> int:
        print(f"—— {label} ——")
        result = extract_understanding(items, memory_hint=memory_hint)
        got = {
            str(item.get("term") or "").strip().lower(): str(
                item.get("cn") or ""
            ).strip()
            for item in (result.get("terms") or [])
        }
        hit = 0
        for term, want in prefs.items():
            have = got.get(term.lower())
            ok = have == want
            hit += 1 if ok else 0
            flag = "✅" if ok else ("（没出现）" if have is None else "❌")
            print(f"    {flag} {term}: 期望「{want}」实际「{have}」")
        print(f"    → 沿用 {hit}/{len(prefs)}")
        print()
        return hit

    without = one("A · 无记忆", "")
    with_mem = one("B · 有记忆", hint)
    print(
        f"对照：无记忆沿用 {without}/{len(prefs)}，有记忆沿用 {with_mem}/{len(prefs)}"
    )
    print(
        "⚠️ 单篇单次对照，只能说明「注入有没有被沿用」，不足以当统计结论；"
        "要下结论得多次重复并报分布。"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="D9 术语一致率测量")
    parser.add_argument(
        "--baseline", action="store_true", help="跨文献一致率（零成本）"
    )
    parser.add_argument(
        "--ab", type=int, metavar="TASK", help="有/无记忆对照（要模型密钥）"
    )
    parser.add_argument(
        "--pref",
        action="append",
        default=[],
        metavar="原文=译法",
        help="要注入的偏好，可重复；`--ab` 时必填",
    )
    args = parser.parse_args()

    if args.baseline:
        return baseline()
    if args.ab:
        prefs: dict[str, str] = {}
        for raw in args.pref:
            if "=" not in raw:
                raise SystemExit(f"--pref 要写成 '原文=译法'，收到：{raw}")
            term, _, cn = raw.partition("=")
            prefs[term.strip()] = cn.strip()
        if not prefs:
            # ⚠️ 不让脚本自己"发明"标准再拿它证明自己：偏好必须由人给
            raise SystemExit(
                "`--ab` 要用 `--pref '原文词=译法'` 显式给出要注入的偏好（可重复）；"
                "先看基线可以单跑 `--baseline`。"
            )
        return ab_with_prefs(args.ab, prefs)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
