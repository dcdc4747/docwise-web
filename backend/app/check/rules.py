"""收口检查的**规则表与词表**：规则是数据，执行器在 `engine.py`。

加一条规则 = 在 `RULES` 里插一行（外加它要用的词表）；
**不用改执行器、不用改界面** —— 报告按 `kind` 分组，前端跟着数据走。

口径出处（一条都不是自创的）：
`docs/产品形态说明_v2_20261014.md` §3.3、`docs/契约_接口_v1_20261014.md` §2.7。
"""

from __future__ import annotations

# 规则集版本：**报告里带着它**，所以以后改了规则，旧报告仍能说清"按第几版跑的"。
# ⚠️ 改了任何一条规则/词表，都要 +1（对应契约 §2.7 的 `ruleset_version`）。
RULESET_VERSION = 1

# ---------------------------------------------------------------- 词表
#
# ⚠️ 两个输入盲区（形态 §3.3 的 E1/E2）在这里正面处理：
# **E1 语言**：词表分中英两套，判出语言再选——英文稿不许"一句都报不出来还说自己支持"；
# **E2 引用制式**：判据核心是"无 `[n]` → 报"，但著者-出版年制的稿子全文没有 `[n]`，
#   会被全部误报 → 所以先判制式，判不出就归「无法判断」，**不硬猜**。

# ① 标记词：数据断言 / 他人观点两类（**只收这两类**）
MARKERS: dict[str, tuple[str, ...]] = {
    "zh": (
        "研究表明",
        "研究显示",
        "研究指出",
        "调查研究",
        "调查显示",
        "数据显示",
        "统计显示",
        "实验表明",
        "实验显示",
        "实验结果",
        "已有研究",
        "相关研究",
        "文献表明",
        "文献显示",
        "学者认为",
        "有学者",
        "普遍认为",
        "据报道",
    ),
    "en": (
        "studies have shown",
        "studies show",
        "research shows",
        "research indicates",
        "research has shown",
        "it has been shown",
        "evidence suggests",
        "studies suggest",
        "investigations have shown",
        "it is widely believed",
        "it is generally accepted",
        "according to",
    ),
}

# ② 模糊限定词：句内有它 → **不报**（作者本来就没把话说死）
HEDGES: dict[str, tuple[str, ...]] = {
    "zh": ("可能", "也许", "或许", "大概", "大约", "似乎", "据说", "普遍认为"),
    "en": (
        "may",
        "might",
        "possibly",
        "perhaps",
        "seems",
        "reportedly",
        "approximately",
        "around",
    ),
}

# ③ 自指词：命中词**前方**这个窗口内出现它 → **一律不报**
# （"本研究表明"是作者自己的工作，不该要求引用）
SELF_REFS: dict[str, tuple[str, ...]] = {
    "zh": ("我们", "本文", "本工作", "本研究", "本课题组", "笔者", "本团队"),
    "en": ("we", "our", "this study", "this work", "this paper", "the present study"),
}
SELF_REF_WINDOW = 8

# ④ 引用标注：顺序编码制与著者-出版年制各一条
NUMERIC_RE = r"\[\s*\d+(?:\s*[-,–—]\s*\d+)*\s*\]"
AUTHOR_YEAR_RE = r"[（(][^（()）]{1,24}[，,]\s*\d{4}[a-z]?[）)]"

# ⑤ CSL-JSON 的必填字段（**输入是我们插入引文时生成的 CSL-JSON**）
CSL_REQUIRED_FIELDS = ("type", "title")
CSL_AUTHOR_FIELDS = ("author", "editor")

# ---------------------------------------------------------------- 规则表
#
# `severity` 由执行器按上下文给（`report` / `unknown`）；
# 这里只声明"这条规则查什么"。
RULES: tuple[dict, ...] = (
    {
        "code": "R1",
        "kind": "missing_citation",
        "title": "该引未引",
        "rule_ref": "形态 §3.3 ① 标记词 + 无标注 + 无豁免",
        "enabled": True,
    },
    {
        "code": "R2",
        "kind": "missing_citation",
        "title": "正文引了 `[n]`，文献表里没有这一条",
        "rule_ref": "形态 §3.3 ③ 一一对应",
        "enabled": True,
    },
    {
        "code": "R3",
        "kind": "format",
        "title": "文献表有条目，正文从未引用",
        "rule_ref": "形态 §3.3 ③ 一一对应",
        "enabled": True,
    },
    {
        "code": "R4",
        "kind": "format",
        "title": "引文编号不连续",
        "rule_ref": "形态 §3.3 ③ 编号连续性",
        "enabled": True,
    },
    {
        "code": "R5",
        "kind": "format",
        "title": "条目字段不完整",
        "rule_ref": "形态 §3.3 ③ 字段完整性（输入是 CSL-JSON）",
        "enabled": True,
    },
    {
        "code": "R6",
        "kind": "term_inconsistent",
        "title": "术语一致性（并列摆出两处，不自动改）",
        # 形态 §3.3 ② 要的是"同一个术语两处写法不一致"。
        # 真做需要**术语表对齐**（我们手里有 terms_json），本轮先不做：
        # **宁可不做，也不做一个半准的**。
        "rule_ref": "形态 §3.3 ②（本轮未启用：需要术语表对齐）",
        "enabled": False,
    },
    {
        "code": "R7",
        "kind": "unknown",
        "title": "语言 / 引用制式判不出（如实说不判）",
        "rule_ref": "形态 §3.3 E1 语言 / E2 引用制式",
        "enabled": True,
    },
)

RULES_BY_CODE = {rule["code"]: rule for rule in RULES}

# 报告里按这个顺序分组（前端跟着这个序，别用 dict 插入序去猜）
KIND_ORDER = ("missing_citation", "term_inconsistent", "format", "unknown")
