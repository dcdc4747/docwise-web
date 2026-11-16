# 参考文献样式：第三方数据与许可

这个目录（`csl/`）里放的是 **CSL 样式与语言包**，它们**不是我们写的、也不是我们授权的**第三方数据。
随仓库分发时**必须保留本说明**：CSL 采用 CC BY-SA 3.0，要求署名并保留样式文件内的作者/贡献者元数据。

## 1. citeproc-py（渲染引擎）

- 版本：**0.11.1**（装在引擎 venv 里，**不是**后端那 6 个运行时依赖之一）
- 许可：**BSD-2-Clause-Views**（宽松；"Views" 那一条的大意是：**不得暗示原作者为我们的产品背书**）
- 上游：https://github.com/brechtm/citeproc-py
- ⚠️ 上游**自述只通过 citeproc 测试套件约 60%**（缺 disambiguation / collapsing / display 等），
  所以我们的口径是：**只做渲染，不做"样式合规判分"**——`run_bibliography.py` 里不输出任何
  "合规/不合规"结论，渲染成什么样就是什么样。

## 2. CSL 样式与语言包（数据）

- 来源：`citation-style-language/styles` 与 `citation-style-language/locales`（GitHub）
- 许可：**CC BY-SA 3.0**（署名—相同方式共享）。⭐ **署名义务**：CSL 项目 README 明确要求
  **使用了 CSL 样式的软件要提到 CSL 项目并链接 https://citationstyles.org/**；
  且**再分发时要保留样式元数据里的作者/贡献者信息**（本目录的 `.csl` 文件**原样保留**，未做任何改动）。
- 本目录现有文件（**原样、未改**）：`apa.csl`｜`ieee.csl`｜`gb-t-7714-2015-numeric.csl`｜
  `gb-t-7714-2015-author-date.csl`｜`locales-zh-CN.xml`｜`locales-en-US.xml`
- ⚠️ `vancouver.csl` **已删除**：CSL 仓库该路径返回 404（文件名不对），取到的是 0 字节空文件——
  **空样式文件比没有更危险**（会让"文件存在"的检查通过、渲染时炸）。

## 3. 我们自己的脚本

`run_bibliography.py`（本目录上一级）是我们写的薄封装，**不携带任何样式数据**；
它把 CSL-JSON 喂给 citeproc-py、把结果按 JSON 交给后端。它同时钉死了三个流的 UTF-8——
Windows 上重定向时 stdin/stdout 默认按控制台代码页（实测 gbk）走，**中文条目会被写成 GBK 字节、
甚至因孤立代理字符直接抛 `UnicodeEncodeError`**（实测踩过）。

## 4. 对外说明要带的一句

如果作品说明/答辩 PPT 里提到"支持按期刊样式生成参考文献"，请一并说明：
**样式数据来自 Citation Style Language 项目（CC BY-SA 3.0），渲染由 citeproc-py（BSD-2-Clause-Views）完成。**
