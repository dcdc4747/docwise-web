"""结构解析脚本（引擎侧，**不进公开仓库**）：把 PDF 的结构变成后端 `tasks.structure` 的形状。

路线（依据 `docs/结构解析选型记录_20261015.md` §9.3，**这是唯一权威**）：

- ⭐ **标题层级来自 PDF 自带的书签目录**（`Document.get_toc()`）——**作者自己声明的层级**，
  书签的 `level` 直接用，**不猜编号**；判级仍归后端的 `blocktypes.py`，这里**不写第二套判级**。
  （§9.2 已实测："按编号深度判层级"在这批 PDF 上不成立：章节编号根本不在文字层里。）
- **参考文献区**优先用**书签里 `References` 那一项的页号**定位（§9.4 实测：只按"行首 `[n]`"
  锚定会从附录那一页起、吃进公式续行）；区内**以 `[n]` 为主时只留 `[n]` 开头的**条目，并清掉
  裸页码 / 公式续行这类碎片。
- ⚠️ **表格 / 公式不做**（§9.5：规则法实测不可用、模型法本机 `torch` 起不来）——
  **不许写空壳字段冒充已支持**。

冻结的输出形状（后端 `Task.structure` 与 `open_source._collect_result` 已经在等它）：

```json
{"headings": [{"block_id": "p1_b5", "level": 2, "text": "2.1. 技术接受模型"}],
 "references": {"count": 47, "entries": [{"index": 1, "text": "F. Hund, Z. Phys. 43, 805 (1927)."}]}}
```

- `level`：**引擎侧给的**（来自书签），后端不重算；
- `block_id`：**能对上就給**（C3 目录跳转要它定位），**对不上就是 `null`**（不许猜）；
- `references.count` / `entries`：**解析器原始产出**，后端不合并不去重。

CLI：

    python structure_blocks.py --pdf <x.pdf> --blocks <blocks.json|-> [--no-references] [--out <x.json>]

`--blocks` 是该 PDF **已抽好的块列表**（`[{"block_id": "...", "text": "..."}]`，也接受
`{"blocks": [...]}` 包一层；`-` 表示从 stdin 读）。

退出码（**照卡⑥ 的验收③**）：

- **0**：成功。⚠️ **"没有结构"也算成功**（少字段即可）——后端已按"缺失即 NULL"接好，
  所以**文件不存在 / 不是 PDF / 没有书签 / `--blocks` 指向不存在的文件 / 坏 JSON /
  `blocks` 是垃圾**，一律 **退出码 0 + `{}` 或只剩能拿到的那些键**，**绝不让异常逃出去**；
- **2**：命令行参数本身有问题（缺 `--pdf`、`--blocks`、未知参数）——stderr 给人话；
- **3**：真内部错误（例如 `--out` 的目录建不出来）。

⚠️ Windows 编码坑（本项目真踩过）：重定向时 `stdin`/`stdout`/`stderr` 默认按**控制台代码页
（实测 gbk）**走 → 中文 JSON 会被写成 GBK 字节、甚至解出孤立代理字符直接崩。所以三个流
在 `main()` 开头**一起钉死 UTF-8**，读 `--blocks` 文件也显式 `encoding="utf-8"`（并容忍 BOM）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

# 只依赖 PyMuPDF（引擎 venv 里已有）+ 标准库；**不依赖模型、不装 torch**。
import fitz  # noqa: E402  (PyMuPDF 的导入名一直是 fitz)

REQUIRED_KEYS = ("headings", "references")

# 参考文献区的标题（书签里那一项的名字，中英都要认）
_REF_TITLE_RE = re.compile(r"(reference|bibliograph|参考文献|引用文献)", re.IGNORECASE)
# 条目：行首 `[12]`
_ENTRY_RE = re.compile(r"^\s*\[(\d{1,4})\]\s*(.*)$")
# 裸页码 / 纯数字碎片
_BARE_NUMBER_RE = re.compile(r"^[\s\d.,;:()\[\]|/\\-]*$")
# 公式续行碎片：以运算符为主、几乎没有词
_FORMULAISH_RE = re.compile(r"[=≈≠≤≥±∂∑∫√^_{}<>]")
# 归一化时丢掉的标点（标题匹配用）
_PUNCT_RE = re.compile(r"[\s.,;:!?、，。：；！？·•—–\-_/\\()\[\]{}「」『』《》\"'’“”]+")


# ============================================================ 工具

def _log(message: str) -> None:
    """人话写 stderr；**不影响退出码**。"""
    print(f"[structure] {message}", file=sys.stderr, flush=True)


def _norm(text: str | None) -> str:
    """标题匹配用的归一化：NFKC → casefold → 去掉空白与常见标点。

    为什么这么宽：书签标题与块文本常有排版差异（连字符、全半角、大小写、多余空格），
    实测 `I. INTRODUCTION` 这类在文字层里是 `INTRODUCTION`（§9.2）。但**只做形状归一，
    不做同义替换**——对不上就 `null`，不猜。
    """
    if not text:
        return ""
    flat = unicodedata.normalize("NFKC", str(text)).casefold()
    return _PUNCT_RE.sub("", flat)


def _iter_blocks(raw: object) -> list[dict]:
    """把 `--blocks` 的输入收敛成 `[{"block_id","text"}]`；**坏形状一律当空**（不抛）。"""
    if isinstance(raw, dict):
        raw = raw.get("blocks")
    if not isinstance(raw, list):
        _log("blocks 不是列表，按空处理")
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        block_id = item.get("block_id") or item.get("id")
        text = item.get("text") or item.get("translated")
        if isinstance(block_id, str) and isinstance(text, str):
            out.append({"block_id": block_id, "text": text})
    return out


def _read_blocks(spec: str | None) -> list[dict]:
    """读块列表；`-` 表示 stdin。任何读不到/解析不了的情况都回空列表（退出码仍 0）。"""
    if not spec:
        return []
    try:
        if spec == "-":
            # 容错：stdin 可能带 BOM
            raw_text = sys.stdin.read().lstrip("\ufeff")
        else:
            path = Path(spec)
            if not path.is_file():
                _log(f"blocks 文件不存在：{path}（按空处理）")
                return []
            raw_text = path.read_text(encoding="utf-8").lstrip("\ufeff")
        return _iter_blocks(json.loads(raw_text))
    except json.JSONDecodeError as exc:
        _log(f"blocks 不是合法 JSON：{exc}（按空处理）")
    except OSError as exc:
        _log(f"读 blocks 失败：{exc}（按空处理）")
    return []


# ============================================================ 标题层级（书签）

def _match_block_id(title: str, blocks: list[dict]) -> str | None:
    """把书签标题对到块编号上：**先全等、再双向包含、最后"实词都在"**。对不上回 `None`。

    三级规则（都是**形状**判据，不做同义替换，**绝不猜**）：

    1. **全等**：归一化后一模一样；
    2. **双向包含**（两侧都 ≥4 字）：书签比块长、或块比书签长（书签常带编号、块常带后缀）；
    3. **实词都在**（≥2 个长度 ≥4 的实词，且**都落在同一块**里）——收的是排版差异：
       实测化学那篇 `Dependence on the projection K` ↔ 块 `VI. DEPENDENCE ON THE PROJECTION`
       （罗马数字粘在块首、`K` 丢在正文里）、`Wigner D-matrix` ↔ 块 `1. Wigner -matrix`
       （`D` 被当公式字体丢了）。这类**同一块里词都在**的，判为命中；
       命中取**归一化后最短的那个块**（最短＝最具体，避免长正文块把所有词都"含"进去）。

    对不上就是 `None`——例如 `Abstract` / `References`：**实测块里根本没有这两个词**
    （不是写法差异），所以这两条**如实为 null**，不硬凑。
    """
    want = _norm(title)
    if not want:
        return None
    normed: list[tuple[str, str]] = []
    for block in blocks:
        got = _norm(block["text"])
        if not got:
            continue
        if got == want:
            return block["block_id"]
        normed.append((got, block["block_id"]))

    if len(want) >= 4:
        for got, block_id in normed:
            if want in got or (len(got) >= 4 and got in want):
                return block_id

    flat = unicodedata.normalize("NFKC", str(title or "")).casefold()
    words = [w for w in re.split(r"[^\w]+", flat) if len(w) >= 4]
    if len(words) >= 2:
        candidates = [
            (len(got), block_id)
            for got, block_id in normed
            if all(w in got for w in words)
        ]
        if candidates:
            candidates.sort()
            return candidates[0][1]
    return None


def _headings(doc: "fitz.Document", blocks: list[dict]) -> list[dict]:
    """书签 → `[{block_id, level, text}]`。书签层级直接用，**后端不重算**。"""
    try:
        toc = doc.get_toc(simple=True)
    except Exception as exc:  # noqa: BLE001 - 拿不到就当没有
        _log(f"读书签失败：{exc}")
        return []
    out: list[dict] = []
    for row in toc or []:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        level, title = row[0], row[1]
        try:
            level_int = int(level)
        except (TypeError, ValueError):
            continue
        text = str(title or "").strip()
        if not text or level_int < 1:
            continue
        out.append(
            {
                "block_id": _match_block_id(text, blocks),
                "level": level_int,
                "text": text,
            }
        )
    return out


# ============================================================ 参考文献

def _ref_start_page(doc: "fitz.Document") -> int | None:
    """参考文献区的起始页（0 基）：**优先书签里那一项**（§9.4 的实测口径）。"""
    try:
        toc = doc.get_toc(simple=True)
    except Exception:  # noqa: BLE001
        toc = []
    for row in toc or []:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        if _REF_TITLE_RE.search(str(row[1] or "")):
            try:
                page = int(row[2])
            except (TypeError, ValueError):
                continue
            if page >= 1:
                return min(page - 1, max(doc.page_count - 1, 0))
    # 退路：在文字层里找一节标题行（**只是退路**；书签那条才是实测可用的）
    for pno in range(doc.page_count):
        try:
            text = doc[pno].get_text("text") or ""
        except Exception:  # noqa: BLE001
            continue
        for line in text.splitlines()[:40]:
            stripped = line.strip()
            if 0 < len(stripped) <= 40 and _REF_TITLE_RE.search(stripped):
                return pno
    return None


def _looks_like_fragment(line: str) -> bool:
    """碎片判据（§9.4 的"裸页码 / 公式续行"）：纯数字、或几乎只有运算符与符号。"""
    stripped = line.strip()
    if not stripped:
        return True
    if _BARE_NUMBER_RE.match(stripped):
        return True
    letters = sum(1 for ch in stripped if ch.isalpha())
    if letters <= 2 and _FORMULAISH_RE.search(stripped):
        return True
    return False


def _references(doc: "fitz.Document") -> dict | None:
    """参考文献区 → `{count, entries}`；定位不到就回 `None`（少字段，不编）。"""
    start = _ref_start_page(doc)
    if start is None:
        _log("书签与文字层都没找到参考文献区（references 少字段）")
        return None

    lines: list[str] = []
    for pno in range(start, doc.page_count):
        try:
            lines.extend((doc[pno].get_text("text") or "").splitlines())
        except Exception:  # noqa: BLE001
            continue

    entries: list[dict] = []
    for line in lines:
        match = _ENTRY_RE.match(line)
        if match:
            entries.append({"index": int(match.group(1)), "text": match.group(2).strip()})
            continue
        # 续行：接到上一条（但碎片不许进）
        if entries and not _looks_like_fragment(line):
            tail = entries[-1]["text"]
            if tail and not tail.endswith(("。", ".")) or len(line) < 60:
                merged = f"{tail} {line.strip()}".strip()
                if len(merged) <= 1000:  # 防某条把整页都吃进去
                    entries[-1]["text"] = merged

    # 碎片过滤：太短 / 没有词 / 纯页码
    kept: list[dict] = []
    seen: set[str] = set()
    for entry in entries:
        text = re.sub(r"\s{2,}", " ", entry["text"]).strip()
        if len(text) < 12:
            continue
        if not any(ch.isalpha() for ch in text):
            continue
        key = _norm(text)
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append({"index": entry["index"], "text": text})

    if not kept:
        _log("参考文献区里没留下像样的条目（references 少字段）")
        return None
    return {"count": len(kept), "entries": kept}


# ============================================================ 主流程

def build_structure(pdf_spec: str | None, blocks_spec: str | None, *, with_references: bool) -> dict:
    """产出结构字典；**任何拿不到的部分就少那个键**，绝不抛异常。"""
    blocks = _read_blocks(blocks_spec)
    if not pdf_spec:
        return {}
    path = Path(pdf_spec)
    if not path.is_file():
        _log(f"PDF 不存在：{path}（少字段）")
        return {}
    try:
        doc = fitz.open(str(path))
    except Exception as exc:  # noqa: BLE001 - 不是 PDF / 打不开都算"没有结构"
        _log(f"打不开 PDF：{exc}（少字段）")
        return {}
    try:
        headings = _headings(doc, blocks)
        result: dict = {}
        if headings:
            result["headings"] = headings
        else:
            _log("这份 PDF 没有书签目录（headings 少字段）")
        if with_references:
            references = _references(doc)
            if references:
                result["references"] = references
        return result
    finally:
        try:
            doc.close()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    # ⚠️ 见模块文档：Windows 上重定向时三个流默认按控制台代码页（gbk）走，必须钉死 UTF-8。
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="PDF 结构解析（书签 → 标题层级；参考文献区 → 条目）"
    )
    parser.add_argument("--pdf", help="源 PDF 路径（只读，绝不修改）")
    parser.add_argument("--blocks", help="已抽好的块列表（JSON 文件路径，或 - 表示 stdin）")
    parser.add_argument("--no-references", action="store_true", help="跳过参考文献解析")
    parser.add_argument("--out", help="结果写到这个文件（默认 stdout）")
    try:
        args = parser.parse_args()
    except SystemExit as exc:  # argparse 的参数错误 → 统一退出码 2
        return 2 if exc.code not in (0,) else 0

    if not args.pdf:
        _log("缺 --pdf（用 --help 看用法）")
        return 2

    structure = build_structure(
        args.pdf, args.blocks, with_references=not args.no_references
    )

    text = json.dumps(structure, ensure_ascii=False)
    if args.out:
        try:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(text, encoding="utf-8")
        except OSError as exc:
            _log(f"写 --out 失败：{exc}")
            return 3
    print(text, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
