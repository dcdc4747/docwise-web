"""参考文献格式化（引擎侧脚本，随仓库内置）。

为什么要单独一个脚本：CSL 样式文件是 **CC BY-SA 3.0** 的数据资产，与代码分开存放
（见同目录 `csl/`，署名要求写在该目录的 `NOTICE.md` 里）。本脚本只做渲染：
把 CSL-JSON 喂给 citeproc-py，按样式输出纯文本条目。

用法：

    python run_bibliography.py --style apa [--locale zh-CN] [--csl-dir <dir>]
    python run_bibliography.py --list-styles

stdin ：JSON `{"items": [<CSL-JSON 单条>, ...]}`（就是我们落库的那份 `csl_json`）
stdout：JSON `{"style","locale","entries":[纯文本...],"item_texts":{id: 纯文本},
               "count", "skipped":[id...]}`
退出码：0 成功；2 输入或样式有问题（stderr 有人话）；3 引擎内部错误。

口径（照项目规矩）：

- ⭐ **只做渲染，不做"样式合规判分"**：citeproc-py 官方自述只过 citeproc 测试套件约 60%
  （缺 disambiguation / collapsing / display 等），所以这里**不输出任何"合规/不合规"结论**，
  渲染成什么样就是什么样。
- ⭐ **不编字段**：条目缺作者/年份时 citeproc 渲染出什么就是什么，我们**不补占位串**；
  连条目都解析不了的，只把 id 放进 `skipped`，不假装渲染成功。
- ⭐ `entries` 的顺序**由样式决定**（数字制按引用顺序、著者年制按字母序），所以它**不带 id**；
  需要 id 对齐的用 `item_texts`（**逐条单独渲染**，因此**没有跨条目消歧**——这一点如实写在
  字段名旁边，别让调用方以为它和 `entries` 是同一份东西）。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

# 样式 key → 文件名（只收仓库里真取到的那几种；取不到的**不假装支持**）
STYLES: dict[str, str] = {
    "apa": "apa.csl",
    "ieee": "ieee.csl",
    "gb-t-7714-2015-numeric": "gb-t-7714-2015-numeric.csl",
    "gb-t-7714-2015-author-date": "gb-t-7714-2015-author-date.csl",
}
DEFAULT_CSL_DIR = pathlib.Path(__file__).resolve().parent / "csl"


def _fail(code: int, message: str) -> int:
    print(message, file=sys.stderr)
    return code


def _render(items: list[dict], style, formatter) -> list[str]:
    """把一批条目渲染成纯文本列表（顺序由样式决定）。"""
    from citeproc import Citation, CitationItem, CitationStylesBibliography
    from citeproc.source.json import CiteProcJSON

    source = CiteProcJSON(items)
    bibliography = CitationStylesBibliography(style, source, formatter)
    for item in items:
        bibliography.register(Citation([CitationItem(str(item["id"]))]))
    return [str(entry) for entry in bibliography.bibliography()]


def main() -> int:
    # ⚠️ Windows 上这三个流重定向时全按**控制台代码页**走（实测是 gbk）：
    #    stdin 会把后端喂进来的 **UTF-8 JSON 当 GBK 解**（解出孤立代理字符，
    #    渲染时直接 `UnicodeEncodeError: '\udca0' ... surrogates not allowed`），
    #    stdout 会把中文写成 GBK 字节。所以这里把**三个流**一起钉死 UTF-8。
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="按 CSL 样式渲染参考文献")
    parser.add_argument("--style", help="样式 key，见 --list-styles")
    parser.add_argument("--locale", default=None, help="如 zh-CN；不给就用样式自带默认")
    parser.add_argument("--csl-dir", default=str(DEFAULT_CSL_DIR))
    parser.add_argument("--list-styles", action="store_true")
    args = parser.parse_args()

    if args.list_styles:
        print(json.dumps({"styles": sorted(STYLES), "csl_dir": args.csl_dir}, ensure_ascii=False))
        return 0

    if not args.style:
        return _fail(2, "缺少 --style（用 --list-styles 看支持的样式）")
    if args.style not in STYLES:
        return _fail(
            2,
            f"不支持的样式 {args.style!r}；支持：{'、'.join(sorted(STYLES))}",
        )

    style_file = pathlib.Path(args.csl_dir) / STYLES[args.style]
    if not style_file.exists():
        return _fail(2, f"样式文件不在：{style_file}（CSL 样式数据在引擎侧 csl/ 目录）")

    try:
        # 容忍开头 BOM：调用方可能把文件直接管进来（Windows 编辑器爱写 BOM）
        raw = json.loads(sys.stdin.read().lstrip("\ufeff"))
    except json.JSONDecodeError as exc:
        return _fail(2, f"stdin 不是合法 JSON：{exc}")
    items = [item for item in (raw.get("items") or []) if isinstance(item, dict) and item.get("id")]
    if not items:
        # 没条目不是错误：如实回一份空表（前端据此显示"还没有引文"）
        print(json.dumps({"style": args.style, "locale": args.locale, "entries": [],
                          "item_texts": {}, "count": 0, "skipped": []}, ensure_ascii=False))
        return 0

    try:
        from citeproc import CitationStylesStyle, formatter
    except ImportError as exc:  # pragma: no cover - 引擎环境缺依赖时如实报
        return _fail(3, f"引擎环境缺 citeproc-py：{exc}")

    try:
        style = CitationStylesStyle(str(style_file), locale=args.locale, validate=False)
    except Exception as exc:  # noqa: BLE001 - 引擎侧异常一律如实回传
        return _fail(2, f"样式加载失败（{args.style}）：{exc}")

    # ① 整批渲染：这一份**带跨条目消歧**，但顺序由样式决定（数字制按引用序、著者年制按字母序）
    try:
        entries = _render(items, style, formatter.plain)
    except Exception as exc:  # noqa: BLE001
        return _fail(3, f"渲染失败：{exc}")

    # ② 逐条渲染：**为了 id 对齐**（前端要把某条素材的出处显示出来），因此**没有跨条目消歧**
    item_texts: dict[str, str] = {}
    skipped: list[str] = []
    for item in items:
        try:
            rendered = _render([item], style, formatter.plain)
        except Exception:  # noqa: BLE001 - 单条坏不该带塌整批
            skipped.append(str(item["id"]))
            continue
        if rendered:
            item_texts[str(item["id"])] = rendered[0]

    print(
        json.dumps(
            {
                "style": args.style,
                "locale": args.locale,
                "entries": entries,
                "item_texts": item_texts,
                "count": len(entries),
                "skipped": skipped,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
