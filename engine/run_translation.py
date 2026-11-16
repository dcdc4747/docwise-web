"""docengine 翻译 + 抽取段落块 + **块级译文** + 输出结果 JSON（供 docwise 后端子进程调用）。

用法：
    python run_translation.py --input <pdf> --output <dir> [--lang-in en] [--lang-out zh]
                             [--service deepseek] [--thread 2]

依赖环境变量（DeepSeek 翻译服务）：DEEPSEEK_API_KEY / DEEPSEEK_MODEL / DEEPSEEK_BASE_URL

⚠️ **本脚本钩的是引擎内部结构，引擎升级后必须重跑验证**（怎么验见文末"升级检查单"）。
实测兼容：**1.9.11 与 1.9.12**（升级到 1.9.12 时逐项对比过：离线 A/B 与端到端产物数字完全一致）。

为什么要有这个脚本（块级译文，2026-09-30 加）
--------------------------------------------
docengine 把译文排进 PDF 产物，但**不对外说"哪段原文译成了什么"**，于是 docwise 的
`task_blocks.translated` 一直是空的。后果很具体：

- 段落精读只能回退显示英文（界面挂着"暂无块级译文"的诚实提示）；
- 问答 / FTS 检索喂给模型的上下文其实是**英文原文**，模型在"现场翻译"；
- 术语定位只能命中原文。

**第一版做法（已废弃）**：用 PyMuPDF 抽块，再拿块文本去撞 docengine 录下的段落对照。
问题是两边**切法本来就不同**（docengine 按自己的版面模型切段、PyMuPDF 按文字块切），
实测 41 块只贴上 29 块，而且有错配（30 字的正文块被贴上 `"."`、`"L"`）——
靠调阈值是在猜。**错配比不配更糟**：用户会读到一段对不上原文的中文。

**现在的做法：直接取 docengine 自己的段落**。它的转换器在每一页里是这么干的：

    sstk = [段落文本, ...]                      # 按阅读顺序
    news = list(executor.map(worker, sstk))     # 逐段翻译，executor.map **保序**
    pstk[id] / sstk[id] / news[id] 一一对应      # pstk 还带几何

所以顺序、原文、译文三者本来就是对齐的，我们只要**把这份对齐取出来**：

1. `TranslateConverter.receive_layout` 每页调一次且按顺序 → 用它数页码；
2. `ThreadPoolExecutor.map` 的入参就是那一页按阅读顺序排好的段落列表 → 录下来；
3. `BaseTranslator.translate` 是所有翻译器的唯一漏斗（缓存命中也要过它）→ 录下
   「原文段落 → 译文」的精确对照。

于是块 = docengine 的段落（顺序天然正确、每块都有译文），**不需要任何模糊匹配**。

两个兜底：
- 只录到空结果时（docengine 内部结构变了、钩子失效），**退回**原来的 PyMuPDF 抽块路径
  （`translated` 留空），而不是产出 0 块——后端现在把"0 块"判为失败，静默失效会
  让所有翻译任务都失败，那更糟。
- 纯公式段（`{v0}` 这种）不成块：它不是可读文字。公式占位符在文本里也一并去掉
  （段落视图渲染不了公式，留着反而是乱码；前端的 PDF 定位是按"去空格"比对的，
  少一个占位符不影响命中）。

版面信号（2026-10-01 加）
------------------------
"外文文献分不出章节标题"的根子是**块上没有字号与坐标**：三条取字路各自把手里本就有
的量扔掉了。文字层那条已经接通（PR #67/#68），这里补引擎这条。

`receive_layout` 里有**两个同下标的栈**：`sstk`（段落文本）与 `pstk`（段落属性：
size / x0 / x1 / y0 / y1）。我们本来就只抓了文本，属性就在隔壁数组里。做法是：

- 在 `ThreadPoolExecutor.map` 挂钩时（那一刻 `executor.map(worker, sstk)` 正要跑，
  两栈都已建好、后面只有读没有写）**顺着调用栈读 `receive_layout` 那一帧的 `pstk`**；
- 属性用 **(页, 原文) 做键**存在 `ATTRS` 里，**不是**与 `sstk` 平行的数组——
  块列表是过滤后的（跳空串、跳纯公式、按 (页, 原文) 去重），平行数组一错位就全串了；
- 写进每块 `layout`，键与文字层那条路**完全一致**：`{unit_h, y0, page_h}`
  （`bold` 给不出：`pstk` 里没有加粗信息，留空；契约允许缺），
  `y0` 已翻成"距页顶"（pdfminer 的 y 是自下而上的，与文字层那条路对齐口径）；
- 三道路障任一不过就**整批不录**，块照常出（`layout` 键都不出现），分级器自动退回
  文字形状——**绝不因为录不到属性而失败**；
- ⚠️ `pstk[id].size` 是**段落内最大字号**（"标题 + 紧随正文"被并成一段时记的是标题字号），
  与文字层那条路的"span 字号中位数"不是同一个口径，已写进契约说明。

公式字体判据：外文标题为什么整段消失（2026-10-01，任务 A 的根因）
------------------------------------------------------------------
引擎默认的"公式字体"正则里有 `CM[^R]`——**CM 后面跟任何非 R 的字母都当公式字体**。
LaTeX 排的文献里这条会误伤**文本**字体：`CMBX*`（Computer Modern Bold Extended，就是章节
标题与论文题名）和 `CMTI*`（文本斜体）。被当公式的字符**不会进段落文本栈**，只留一个
`{vN}` 占位符；纯公式段又不成块 → **标题整段消失**（连题名都没了）。

实测化学 arXiv（17 页、37 条粗体标题候选）：

| | 内置判据 | 收窄判据（本脚本默认） |
|---|---|---|
| 块数 | 182 | **212** |
| 公式占位符 | 840 | **730** |
| 标题位置上有独立块 | **0/37** | **26/37**（其余是多行标题的续行，已并进同一块） |

修法用的是**引擎自己的开关** `vfont`（非空时完全替换内置那条），不是改人家的代码。
`--vfont ""` 可退回默认。**这条与"给块带版面信号"是两回事**：版面信号管"哪块是标题"，
这条管"标题的文本还在不在"。两个都做完，外文才真的分得出章节。

版面区域：模型框出来的类别（2026-10-01，任务 A 的第三层）
----------------------------------------------------------
`collect_regions()` 自己跑一次版面模型，把每页 `{cls, bbox, conf}` 写进 `result.json` 的
`regions`——**坐标口径写死一处**：origin 左上、y 向下、单位点（与块的 `layout` 一致，
实测抽 20 块框框几乎逐点重合）。后端**只按坐标贴标签、不切块**。

实测价值（真数字，两份外文）：

| | 化学 arXiv（212 块） | EBSCO（42 块） |
|---|---|---|
| 区域说 `title`、块也该是标题 | 21 条（与字号判据吻合，互相印证） | — |
| **只有区域才认得出来的真标题** | **9 条**（`II. ORIENTATION TRAJECTORY…`、`Appendix A~G:`） | **5~6 条**（含题名第二行） |
| 只有区域才认得出来的真表注 | **2 条**（`TABLE I.`/`TABLE II.` 罗马数字，文字规则只认阿拉伯数字） | 0 |
| 误报 | **0** | 1（杂志导语，大字号导言，当标题可接受） |

升级检查单（引擎换了版本就照这个跑一遍）
------------------------------------------
本脚本依赖引擎的这几处内部结构，**升级后必须逐条确认还在**：

1. `docengine.converter.TranslateConverter.receive_layout` 里仍然有**同下标的** `sstk` / `pstk`
   （段落文本栈与属性栈）——`pstk[i].size / x0 / x1 / y0 / y1` 是我们录几何的来源；
2. 那句 `executor.map(worker, sstk)` 还在（我们在 `ThreadPoolExecutor.map` 上挂钩）；
3. `docengine.high_level.translate()` 仍然接受 `vfont`（公式字体判据，见上）；
4. `docengine.doclayout.OnnxModel.load_available()` 与 `result.boxes/names` 的字段名不变；
5. `docengine.translator.BaseTranslator.translate` 仍是所有翻译器的唯一漏斗。

**跑法**（两条都不花钱、几分钟）：

    # ① 离线 A/B（身份翻译，一次 API 都不调）：块数/占位符/标题命中应与基线一致
    引擎python  temp/taskA_ab_offline.py a      # 期望 182 块 / 840 占位符 / 0-37
    引擎python  temp/taskA_ab_offline.py b      # 期望 212 块 / 730 占位符 / 26-37

    # ② 走应用真上传一份，比对任务详情：期望 212 块 / 212 带 layout / 212 有译文，
    #    类型 {title 1, body 169, heading 30, caption 12}，区域 17 页 430 个

**回滚**：`temp/engine_docengine_before_update.bundle`（升级前的完整 git 历史）+
`temp/engine_venv_freeze_before.txt`（当时的依赖清单）。引擎是**本地 editable 安装**，
`git checkout <旧提交>` 即回到旧版，不用重装依赖。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, Path(__file__).resolve().parent.as_posix())


def _sanitize_no_proxy() -> None:
    """把 NO_PROXY 里带方括号的 IPv6（`[::1]`）改成标准写法。

    必须在 `import docengine` **之前**做：`docengine/translator.py` 顶部就 `import ollama`，
    ollama 在导入期建 httpx 客户端，httpx 拿 NO_PROXY 的每一项建 `URLPattern`，
    `[::1]` 会被当成"端口 `:1]`"→ `InvalidURL`，**整脚本一行活没干就崩**。
    实测 2026-10-08：机器上装了代理工具、NO_PROXY 里有 `[::1]`，任何上传都失败。
    只动 `no_proxy` 这一族（代理地址本身的方括号是合法的，不能动）。
    """
    bracket = re.compile(r"^\[([0-9A-Fa-f:]+)\](:\d+)?$")
    for key in list(os.environ):
        if key.lower() != "no_proxy":
            continue
        parts = []
        for item in os.environ[key].split(","):
            item = item.strip()
            match = bracket.match(item)
            parts.append(f"{match.group(1)}{match.group(2) or ''}" if match else item)
        os.environ[key] = ",".join(parts)


_sanitize_no_proxy()

import numpy as np  # noqa: E402
import pymupdf  # noqa: E402
from docengine.converter import TranslateConverter  # noqa: E402
from docengine.doclayout import OnnxModel  # noqa: E402
from docengine.high_level import translate  # noqa: E402
from docengine.translator import BaseTranslator  # noqa: E402
from pdfminer.layout import LTPage  # noqa: E402

_VAR_RE = re.compile(r"\{\s*v[\d\s]+\}")
_VAR_ONLY_RE = re.compile(r"^\{\s*v[\d\s]+\}$")
_WS_RE = re.compile(r"\s+")

# ── 「公式字体」判据（2026-10-01，任务 A 的根因修复）──────────────────────────
# 引擎默认那条正则里有 `CM[^R]`——**CM 后面跟任何非 R 的字母都算公式字体**。LaTeX 文档里
# 这条会误伤两类**文本**字体：
#   · `CMBX*`（Computer Modern Bold Extended）＝**章节标题**、论文题名；
#   · `CMTI*`（Text Italic）＝正文里的斜体强调。
# 实测化学 arXiv（17 页）：37 条粗体标题**一条都没进块流**（`CMBX9` 976 字符、
# `CMBX10` 374、`CMBX12` 53、`CMTI9` 666 全被当公式）——文字被换成 `{vN}` 占位符，
# 纯公式段又不成块，于是**标题整段消失**（题名也没了）。这不是"块分级判不出来"，
# 是**文本在解析阶段就没了**。
#
# 修法：用引擎自己的开关 `vfont`（"自定义公式字体正则"，非空时**完全替换**内置那条），
# 把判据收窄成**数学字面白名单**——真正的数学字体是 CMMI/CMSY/CMEX/MSBM/CMMIB 这一族，
# CM 的文本字体（CMR/CMBX/CMTI）不该进去。
# 实测（同一份 PDF、离线身份翻译，A/B 只差这一个参数）：
#   块 182 → **212**｜公式占位符 840 → **730**｜标题位置上有独立块 **0/37 → 26/37**，
#   补上多行标题的续行后覆盖率更高；恢复出来的标题含 `I. INTRODUCTION` /
#   `VII. CONCLUSIONS AND PROSPECTS` / `ACKNOWLEDGMENTS` / `A. Geometrical measure`…
#   以及**论文题名**（原先整篇没有题名）。
# 想退回引擎默认：`--vfont ""`。
MATH_FONT_RE = (
    r"(CM(MI|SY|EX|MIB|BSY|MSY)|MSBM|MS\.M|XY|MT|BL|RM|EU|LA|RS|LINE|LCIRCLE|"
    r"TeX-|rsfs|txsy|wasy|stmary|.*Mono|.*Code|.*Ital|.*Sym|.*Math)"
)

# 页标识（LTPage.pageid）→ 0 起的页序。**不能拿 receive_layout 的调用次数当页码**：
# 实测（5 页的 PDF）它被调了 40 次——docengine 是**按版面区域**（整页 / 表格 / 公式）
# 逐个过转换器的，不是按页。pageid 能正确分组，且首次出现的顺序就是文档顺序。
PAGE_IDS: dict[object, int] = {}
CURRENT = {"page": 0}
# 页码 → [ 每次 submit 的段落列表（本身保序） ]
SUBMITTED: dict[int, list[list[str]]] = {}
# 原文段落 → 译文（精确键，键来自同一段字符串，不需要归一化）
PAIRS: dict[str, str] = {}
# 页 → 原文段落 → 版面量（见 record_layouts）。
# **属性绝不许存成与 sstk 平行的数组**：sstk 是"过滤前"的，块列表是"过滤后"的
# （跳过空串、跳过纯公式、按 (页, 原文) 去重），平行数组一错位，几何就贴到别的段上——
# **错配比不配更糟**（第一版拿 PyMuPDF 撞段落的教训）。用 (页, 原文) 做键才稳。
ATTRS: dict[int, dict[str, dict | None]] = {}
# 自报账：录到几批、因为哪一步没录上。数字进引擎日志，方便一眼看出钩子是不是失效了。
LAYOUT_STATS = {"recorded": 0, "missed": 0, "blocks_with_layout": 0}


def page_index(pageid: object) -> int:
    if pageid not in PAGE_IDS:
        PAGE_IDS[pageid] = len(PAGE_IDS)
    return PAGE_IDS[pageid]


def clean(text: str) -> str:
    """去掉公式占位符与多余空白。"""
    return _WS_RE.sub(" ", _VAR_RE.sub(" ", text or "")).strip()


def _layout_frame() -> dict | None:
    """在调用栈上找到 `receive_layout` 那一帧的局部变量。

    为什么要在栈上找：`sstk` / `pstk` 是 `receive_layout` 的**局部变量**，它俩唯一的
    交接点就是那句 `executor.map(worker, sstk)`——那时两栈都已建好（解析循环早就结束，
    后面只有读没有写）。我们在 `ThreadPoolExecutor.map` 上挂着钩，顺手把那一帧读了。
    """
    frame = sys._getframe(1)
    while frame is not None:
        if frame.f_code.co_name == "receive_layout":
            local = frame.f_locals
            if "pstk" in local and "sstk" in local:
                return local
        frame = frame.f_back
    return None


def _page_height(local: dict) -> float:
    """页高（pt）。

    **不能拿 `ltpage.height` 当默认**：`receive_layout` 不只为整页调用一次，
    **每个图表（figure）也会单独过一次**（实测 5 页被调 40 次），那时 `ltpage` 是那个
    figure、`height` 是图的高（converter 自己的注释也提醒过这一点）。
    版面数组的形状才是页高：docengine 把整页**按 72dpi** 渲染成图，再拿 pdfminer 的点坐标
    直接去索引它，所以 `shape[0]` 就是页高的点数。
    """
    layout = getattr(local.get("self"), "layout", None)
    pageid = getattr(local.get("ltpage"), "pageid", None)
    try:
        return float(layout[pageid].shape[0])
    except Exception:  # noqa: BLE001 - 换个来源再试，取不到就当没有
        pass
    ltpage = local.get("ltpage")
    if isinstance(ltpage, LTPage):
        try:
            return float(ltpage.height)
        except Exception:  # noqa: BLE001
            return 0.0
    return 0.0


def _merge_layout(page: int, source: str, layout: dict) -> None:
    """同页同一段文字只留一份；**两趟几何不一致就判它为 None**（宁缺勿错）。

    一页会被过好几遍（整页一次 + 每个图表一次），同一段在正常情况下几何逐位相同；
    真出现不一致（重排版、同名短段落在页面上出现两次），我们**没有依据判断哪一份对**，
    那就两份都不要。
    """
    bucket = ATTRS.setdefault(page, {})
    if source not in bucket:
        bucket[source] = layout
    elif bucket[source] != layout:
        bucket[source] = None


def record_layouts(page: int, sources: list[str], items: object) -> None:
    """录下这一批段落的几何——`pstk[id]` 与 `sstk[id]` **同下标**。

    三道"宁缺勿错"的关卡，任何一道不过就**整批不录**（块照常出，只是没有 layout）：

    ① `sstk is items`：确认这一帧的段落栈就是我们正要翻译的这一份（防串到别的 map 调用）；
    ② `len(pstk) == len(sstk)`：两栈同下标是这份几何成立的前提；
    ③ 页高取不到：宁可没有位置，也不给错位置。

    ⚠️ `pstk[id].size` 是**段落内最大字号**（更大的字会顶上去，见 converter 的
    `if child.size > pstk[-1].size`）——"标题 + 紧随正文"被并成一段时，这里记下来的是
    **标题**的字号。这与文字层那条路（span 字号的中位数）不是同一个口径，已在契约里注明；
    块分级那边靠"大 **且短**"这两条一起挡（整段正文都很长，过不了长度关）。
    """
    local = _layout_frame()
    if local is None or local.get("sstk") is not items or len(sources) == 0:
        LAYOUT_STATS["missed"] += 1
        return
    pstk = local["pstk"]
    if len(pstk) != len(sources):
        LAYOUT_STATS["missed"] += 1
        return
    page_h = _page_height(local)
    if page_h <= 0:
        LAYOUT_STATS["missed"] += 1
        return
    for index, source in enumerate(sources):
        try:
            item = pstk[index]
            unit_h = round(float(item.size), 1)
            if unit_h <= 0:
                continue
            # pdfminer 的 y 自下而上（y1 是段的**顶**），这里翻成"距页顶"，
            # 与文字层那条路（PyMuPDF 的 bbox[1]）同一个口径。
            # x0/x1/y1 也带上：**双栏页光靠 y 分不开左右栏**（实测两栏的行会在同一个 y 上），
            # 按坐标贴版面类别、以及后面的"标题前缀切分"都要用。
            _merge_layout(
                page,
                source,
                {
                    "unit_h": unit_h,
                    "y0": round(page_h - float(item.y1), 1),
                    "y1": round(page_h - float(item.y0), 1),
                    "x0": round(float(item.x0), 1),
                    "x1": round(float(item.x1), 1),
                    "page_h": round(page_h, 1),
                },
            )
        except (TypeError, ValueError):
            continue
    LAYOUT_STATS["recorded"] += 1


def install_hooks() -> None:
    """把 docengine 的三处内部状态接出来（都要在 translate() 之前装）。"""
    global original_layout, original_map, original_translate

    def receive_layout(self, ltpage):
        CURRENT["page"] = page_index(getattr(ltpage, "pageid", None))
        return original_layout(self, ltpage)

    def recording_map(self, fn, *iterables, **kwargs):
        items = iterables[0] if iterables else None
        if items is not None:
            listed = list(items)
            # sstk 全是 str；其它 map 调用（非字符串）不碰
            if listed and all(isinstance(item, str) for item in listed):
                SUBMITTED.setdefault(CURRENT["page"], []).append(listed)
                try:
                    record_layouts(CURRENT["page"], listed, items)
                except Exception as exc:  # noqa: BLE001
                    # **录不到版面就照常出块**：绝不因为缺属性而让整次转换失败。
                    # 钩的是别人的内部结构（局部变量 + 内部类），升级后失效是预期内的。
                    LAYOUT_STATS["missed"] += 1
                    print(f"版面属性未录到（照常出块）：{exc}", file=sys.stderr, flush=True)
        return original_map(self, fn, *iterables, **kwargs)

    def recording_translate(self, text, *args, **kwargs):
        out = original_translate(self, text, *args, **kwargs)
        if isinstance(text, str) and isinstance(out, str) and text.strip():
            PAIRS.setdefault(text, out)
        return out

    global original_layout, original_map, original_translate
    original_layout = TranslateConverter.receive_layout
    original_map = concurrent.futures.ThreadPoolExecutor.map
    original_translate = BaseTranslator.translate
    TranslateConverter.receive_layout = receive_layout
    concurrent.futures.ThreadPoolExecutor.map = recording_map
    BaseTranslator.translate = recording_translate


def blocks_from_recording() -> list[dict]:
    """用录下来的（页 → 段落顺序）+（原文 → 译文）+（页, 原文）→ 几何拼出块。

    块 id 沿用 `p{页}_b{全局序}`。同一页里同一段只留第一次：docengine 会把同一页过好几遍
    （整页 + 版面区域），不去重的话段落视图里同一段会出现两次。

    `layout` 是**有就给、没有就不给**（键都不出现）：录不到几何时块照常出，
    分级器会自动退回"只看文字形状"，与没有这个钩子之前的表现一致。
    """
    blocks: list[dict] = []
    seen: set[tuple[int, str]] = set()
    for page in sorted(SUBMITTED):
        for batch in SUBMITTED[page]:
            for source in batch:
                if not source.strip() or _VAR_ONLY_RE.match(source.strip()):
                    continue
                key = (page, source)
                if key in seen:
                    continue
                seen.add(key)
                text = clean(source)
                if not text:
                    continue
                hit = PAIRS.get(source)
                block = {
                    "block_id": f"p{page}_b{len(blocks)}",
                    "text": text,
                    "translated": clean(hit) if hit else None,
                }
                layout = ATTRS.get(page, {}).get(source)
                if layout:
                    block["layout"] = layout
                    LAYOUT_STATS["blocks_with_layout"] += 1
                blocks.append(block)
    return blocks


def blocks_from_pdf(pdf_path: str) -> list[dict]:
    """兜底路径：PyMuPDF 抽块（没有块级译文），与接入块级译文之前的行为一致。"""
    doc = pymupdf.open(pdf_path)
    blocks: list[dict] = []
    bid = 0
    for pno, page in enumerate(doc):
        for b in page.get_text("blocks") or []:
            text = (b[4] or "").strip()
            if text:
                blocks.append(
                    {"block_id": f"p{pno}_b{bid}", "text": text, "translated": None}
                )
                bid += 1
    doc.close()
    return blocks


def collect_regions(pdf_path: str, model) -> dict[str, list[dict]]:
    """自己跑一次版面模型，把每页的区域类别与矩形记下来（任务 A）。

    **坐标口径只有一种，写死在这里**：与原 PDF 的文字行、与块的 `layout` 一样——
    **origin 在左上、y 向下、单位是点**。依据：引擎按 72dpi 渲染整页（1px = 1pt），
    模型输出的 `xyxy` 就在这个坐标系里；引擎内部要把它翻成 pdfminer 的"自下而上"去索引
    版面数组，**我们不翻**——后端拿块自己的 `layout`（也是距页顶）直接比。
    实测核对：化学那份抽 20 块，块矩形与它落到的区域框几乎逐点重合
    （块 `x[54,299] y[52,108]` ↔ 区域 `x[54,299] y[53,110]`）。

    **只贴标签、不切块**：这里只回报"哪儿是什么区域"，怎么用由后端的块分级决定。
    """
    regions: dict[str, list[dict]] = {}
    with pymupdf.open(pdf_path) as doc:
        for pno in range(doc.page_count):
            page = doc.load_page(pno)
            pix = page.get_pixmap()
            image = np.frombuffer(pix.samples, np.uint8).reshape(
                pix.height, pix.width, 3
            )[:, :, ::-1]
            result = model.predict(image, imgsz=int(pix.height / 32) * 32)[0]
            rows: list[dict] = []
            for box in result.boxes:
                x0, y0, x1, y1 = (float(value) for value in box.xyxy.squeeze())
                rows.append(
                    {
                        "cls": str(result.names[int(box.cls)]),
                        "bbox": [
                            round(x0, 1),
                            round(y0, 1),
                            round(x1, 1),
                            round(y1, 1),
                        ],
                        "conf": round(float(box.conf), 3),
                    }
                )
            regions[str(pno)] = rows
    return regions


def _repo_scripts_dir() -> Path:
    """仓库里的 backend/scripts（取字与逐段翻译的脚本都在这儿）。

    本文件位于 `<仓库根>/engine/`，上一级就是仓库根。
    """
    return Path(__file__).resolve().parents[1] / "backend" / "scripts"


def _copy_as_mono(pdf_path: str, out_dir: Path) -> str | None:
    """扫描件的产物就是原稿本身：复制一份当 mono，用户下载到的还是原文件。"""
    source = Path(pdf_path)
    target = out_dir / f"{source.stem}_mono.pdf"
    try:
        shutil.copyfile(source, target)
        return str(target)
    except OSError as exc:
        print(f"复制原稿失败：{exc}", file=sys.stderr, flush=True)
        return None


def _ocr_and_translate(pdf_path: str, lang_in: str, lang_out: str) -> list[dict]:
    """扫描件这条路：本地 OCR 取字 →（跨语言时）逐段翻译。

    两个脚本都在 docwise 仓库里（中性化、可单测），这里按路径导入，
    不复制一份逻辑过来——口径只留一处。
    """
    scripts = _repo_scripts_dir()
    if not scripts.exists():
        print(f"找不到取字脚本目录：{scripts}", file=sys.stderr, flush=True)
        return []
    sys.path.insert(0, scripts.as_posix())
    try:
        import ocr_blocks
        import translate_blocks
    except ImportError as exc:
        print(f"导入取字/翻译模块失败：{exc}", file=sys.stderr, flush=True)
        return []

    bar = _make_ocr_bar(pdf_path)
    try:
        blocks, reason = ocr_blocks.ocr_blocks(
            Path(pdf_path), on_page=lambda _page: (bar.update(1) if bar else None)
        )
    except Exception as exc:  # noqa: BLE001 - 失败要如实回传，不能让父进程拿到半截结果
        print(f"OCR 取字失败：{exc}", file=sys.stderr, flush=True)
        return []
    finally:
        if bar is not None:
            bar.close()

    if not blocks:
        print(f"OCR 没取到字：{reason}", file=sys.stderr, flush=True)
        return []
    print(f"OCR 取到 {len(blocks)} 段", flush=True)

    if (lang_in or "").lower().strip() != (lang_out or "").lower().strip():
        translate_blocks.translate_blocks(
            blocks, source_lang=lang_in, target_lang=lang_out
        )
    return blocks


def _make_ocr_bar(pdf_path: str):
    """OCR 的进度条（父进程的 progress.py 解析的就是它）。页数数不出来就不画。"""
    try:
        import fitz  # PyMuPDF
        from tqdm import tqdm

        with fitz.open(pdf_path) as doc:
            total = doc.page_count
        return tqdm(total=total, desc="ocr", file=sys.stderr)
    except Exception:  # noqa: BLE001 - 只是进度显示，失败就不画
        return None


def collect_structure(pdf_path: str, blocks: list[dict]) -> dict | None:
    """调引擎侧结构脚本（与本文件同级）；拿不到 / 失败一律回 None —— 绝不抛。"""
    script = Path(__file__).with_name("structure_blocks.py")
    if not script.is_file():
        return None
    payload = json.dumps(
        {"blocks": [{"block_id": b.get("block_id"), "text": b.get("text")} for b in blocks or []]},
        ensure_ascii=False,
    )
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--pdf", str(pdf_path), "--blocks", "-"],
            input=payload.encode("utf-8"), capture_output=True, timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[structure] 调用失败：{exc}", flush=True)
        return None
    if proc.returncode != 0:
        print(f"[structure] 退出码 {proc.returncode}："
              f"{proc.stderr.decode('utf-8', 'replace')[:200]}", flush=True)
        return None
    try:
        data = json.loads(proc.stdout.decode("utf-8") or "{}")
    except Exception:  # noqa: BLE001
        return None
    return data if isinstance(data, dict) and data else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--lang-in", default="en")
    ap.add_argument("--lang-out", default="zh")
    ap.add_argument("--service", default="deepseek")
    ap.add_argument("--thread", type=int, default=2)
    # 公式字体判据（见文件头 MATH_FONT_RE）：传空串＝用引擎内置默认
    ap.add_argument("--vfont", default=MATH_FONT_RE)
    args = ap.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    mono = None
    dual = None
    blocks: list[dict] = []
    error = None
    # 取字方式：text-layer（docengine 的段落）/ ocr（扫描件走本地 OCR）。界面据此如实说明。
    mode = "text-layer"
    status = "failed"
    code = 1

    install_hooks()

    model = OnnxModel.load_available()
    try:
        res = translate(
            [args.input],
            output=out_dir.as_posix(),
            lang_in=args.lang_in,
            lang_out=args.lang_out,
            service=args.service,
            model=model,
            thread=args.thread,
            # 公式字体判据（空串＝引擎内置默认），见文件头 MATH_FONT_RE 的说明
            vfont=args.vfont,
        )
        mono, dual = res[0]
        status = "completed"
        code = 0
    except Exception as exc:  # noqa: BLE001 - 把失败如实回传
        error = str(exc)

    # 抽块失败也如实记录，不让整个脚本崩溃（保证 result.json 一定会写）
    regions: dict[str, list[dict]] = {}
    try:
        blocks = blocks_from_recording()
        filled = sum(1 for item in blocks if item.get("translated"))
        if blocks:
            print(
                f"块级译文：{filled}/{len(blocks)} 块有译文"
                f"（docengine 段落对照 {len(PAIRS)} 条，页 {len(SUBMITTED)} 页）",
                flush=True,
            )
            # 版面信号自报账：录到几批、几块真的带上了几何、几批没录上。
            # **没录上也照常出块**（只是分级退回文字形状），这里如实打出来便于发现钩子失效。
            print(
                f"版面信号：{LAYOUT_STATS['blocks_with_layout']}/{len(blocks)} 块带字号与位置"
                f"（录到 {LAYOUT_STATS['recorded']} 批，未录到 {LAYOUT_STATS['missed']} 批）",
                flush=True,
            )
            # 版面区域（任务 A）：**文字层这条路才跑**——扫描件那条路的块没有坐标，
            # 贴不上（等信息补上再接）。跑失败也不影响出块，只是少一层信号。
            try:
                regions = collect_regions(args.input, model)
                kinds: dict[str, int] = {}
                for rows in regions.values():
                    for row in rows:
                        kinds[row["cls"]] = kinds.get(row["cls"], 0) + 1
                print(
                    f"版面区域：{len(regions)} 页共 "
                    f"{sum(len(v) for v in regions.values())} 个｜{kinds}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 - 区域只是加分项，失败照常出块
                print(f"版面区域未取到（照常出块）：{exc}", file=sys.stderr, flush=True)
        else:
            # 没录到 docengine 的段落，最常见的原因只有一个：**这份 PDF 没有文字层**（扫描件），
            # docengine 也就没有段落可翻。改走"本地 OCR 取字 + 逐段翻译"这条路
            # （脚本来自 docwise 仓库的 backend/scripts，跑在同一个引擎环境里）。
            print("未录到 docengine 段落（多半是没有文字层的扫描件），改走本地 OCR", flush=True)
            blocks = _ocr_and_translate(args.input, args.lang_in, args.lang_out)
            if blocks:
                mode = "ocr"
                # 扫描件：产物只有原稿（没有重排版式的 PDF），双语稿留空
                mono = _copy_as_mono(args.input, out_dir)
                dual = None
                status = "completed"
                code = 0
            else:
                # OCR 也取不到字：退回 PyMuPDF 抽块（宁可没有译文，也不能没有块）
                print("OCR 也没取到字，退回 PyMuPDF 抽块", flush=True)
                blocks = blocks_from_pdf(args.input)
                print(f"兜底抽到 {len(blocks)} 块", flush=True)
    except Exception as exc:  # noqa: BLE001
        if error is None:
            error = f"抽取文字块失败: {exc}"
        status = "failed"
        code = 1

    result = {
        "mono": mono,
        "dual": dual,
        "blocks": blocks,
        "status": status,
        "mode": mode,
        "error": error,
        # 版面区域（任务 A）：每页 `[{cls, bbox, conf}]`，bbox 是**距页顶**的点坐标。
        # 取不到就是空字典（老产物的形状仍兼容：后端读到空就当没有）。
        "regions": regions,
    }
    # ⭐ 结构（卡⑥）：书签 → 标题层级；参考文献区 → 条目。拿不到就少这个键。
    structure = collect_structure(args.input, blocks)
    if structure:
        result["structure"] = structure

    out_json = out_dir / "result.json"
    out_json.write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )
    print(out_json)
    return code


if __name__ == "__main__":
    sys.exit(main())
