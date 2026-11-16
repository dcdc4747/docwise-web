# 第三方组件声明

> **本目录是整个仓库里唯一保留上游信息的地方。** 其余源码已按要求改为中性命名，
> 不再出现上游项目名、仓库地址或作者信息。
>
> 保留本文件不是可选项：下面两个组件使用 **AGPL-3.0**，该许可证要求在分发时
> 保留许可证全文与版权声明（见同目录 `LICENSE-AGPL-3.0.txt`）。

## 1. 翻译核心

| 项 | 内容 |
|---|---|
| 上游名称 | PDFMathTranslate（命令行工具名 `pdf2zh`） |
| 版本 | 1.9.12 |
| 上游地址 | https://github.com/Byaidu/PDFMathTranslate |
| 许可证 | AGPL-3.0 |
| 版权 | Copyright (c) Byaidu 及贡献者 |

## 2. 版面分析与排版

| 项 | 内容 |
|---|---|
| 上游名称 | BabelDOC |
| 版本 | 0.2.33 |
| 上游地址 | https://github.com/funstory-ai/BabelDOC |
| 许可证 | AGPL-3.0 |
| 版权 | Copyright (c) funstory.ai / awwaawwa 及贡献者 |

## 修改说明

按 AGPL-3.0 第 5 条“显著标注修改”的要求，本项目于 **2026-11-16** 对上述代码做了以下修改：

1. **包与目录重命名**：`pdf2zh` → `docengine`，`babeldoc` → `doclayout_engine`，并相应改写全部导入。
2. **删除未使用模块**：图形界面、Web 后端、MCP 服务、命令行入口，以及内部未启用的内核模块；一并删除上游的开发工具目录。
3. **移除页脚署名**：`typesetting.add_watermark` 改为空实现，翻译产物中不再写入第三方署名文字。
4. **缓存目录改为中性名**：`~/.cache/docengine`、`~/.cache/doclayout_engine`。
5. **资源下载**：移除 GitHub 直连上游，仅保留模型与字体的镜像地址（下载路径本身无法改名，否则无法取到文件）。
6. **文案中性化**：日志、注释与提示中的上游名称改为“排版翻译引擎”。

## 3. 参考文献样式数据（`engine/csl/`）

| 项 | 内容 |
|---|---|
| 来源 | Citation Style Language 项目（`citation-style-language/styles` 与 `locales`） |
| 文件 | `apa.csl`、`ieee.csl`、`gb-t-7714-2015-numeric.csl`、`gb-t-7714-2015-author-date.csl`、`locales-zh-CN.xml`、`locales-en-US.xml`（**原样保留，未修改**） |
| 许可证 | **CC BY-SA 3.0** |
| 署名要求 | 使用 CSL 样式的软件需提及 CSL 项目并链接 https://citationstyles.org/ ；再分发需保留样式文件内的作者/贡献者元数据 |

详见 `engine/csl/NOTICE.md`（该文件随样式数据一起分发，勿删）。

## 4. 参考文献渲染库

| 项 | 内容 |
|---|---|
| 组件 | citeproc-py 0.11.1 |
| 上游 | https://github.com/brechtm/citeproc-py |
| 许可证 | BSD-2-Clause-Views（宽松；不得暗示原作者为本项目背书） |

## 许可义务

- 上述组件仍受 **AGPL-3.0** 约束；本仓库对它们的修改同样按 AGPL-3.0 提供。
- 分发本仓库、或基于本仓库提供网络服务时，需保留本声明与许可证全文，并提供对应源代码。
- 本仓库其余部分（后端、前端、文档）的许可证见仓库根目录 `LICENSE`。
