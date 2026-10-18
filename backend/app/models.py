from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .engine.base import BlockState
from .timeutil import utc_now


class Task(Base):
    """任务卡：每个翻译任务的进度与状态。"""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 归属：登录用户（老库里为空，启动时按 DOCWISE_LEGACY_OWNER 归属）
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    original_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_lang: Mapped[str] = mapped_column(String(16), default="en")
    target_lang: Mapped[str] = mapped_column(String(16), default="zh")
    tier: Mapped[str] = mapped_column(String(16), default="fast")
    translated_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    dual_translated_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default="pending", index=True
    )  # pending / in_progress / completed / failed / cancelled
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    # 这批字是怎么来的：None / "text-layer"（PDF 文字层）/ "ocr"（扫描件走 OCR）。
    # 界面据此如实说明"字是认出来的、可能有个别错字"——扫描件不能和文字层混为一谈。
    text_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 诚实进度（F 批）：阶段 + 引擎自报的预计剩余秒数；进度只增不减
    stage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    eta_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 形体（阅读位置记忆）：上次读到第几页（1 起数）；没读过就是 NULL，
    # 界面据此决定显示「继续读 · 上次读到第 N 页」还是「开始阅读」——不假装记得。
    last_read_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 版面区域（2026-10-01，任务 A）：引擎自己跑一次版面模型，把每页的
    # `{页码: [{cls, bbox, conf}]}` 原样带回来（bbox 是**距页顶**的点坐标，
    # 与块 layout 同一口径）。
    # 与 `task_blocks.layout` 一样**只存原始量、不存判定结果**：判定规则将来改了，
    # 老任务不用重跑引擎就跟着受益。缺失（老任务 / OCR 扫描件）就是 NULL。
    regions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 文档结构（2026-10-15，M6 / C1）：引擎侧结构解析器给什么就存什么——
    # `{"headings": [{"block_id", "level", "text"}],
    #   "references": {"count", "entries"}}`。
    # 与 `regions` 一样**只存原始量、不存判定结果**：判定/分级仍归 `blocktypes.py`，
    # 后端不重算层级、不推断、不补默认值。缺失（老任务、引擎那条路还没接）就是 NULL。
    # 形状与规矩见 docs/契约_数据模型_v1_20261014.md §1.2。
    structure: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 演示库策展（2026-10-08）：`archived_at` 非空 = 这篇不在库里显示，**数据不删**。
    # 为什么用"藏"而不是"删"：演示时要的只是"列表里都是像样的文献"，
    # 而早期任务（2026-09-30 之前传的）本来就没有块级译文、也没有版面信号，
    # 摆在一起会让人以为产品就这样；删掉又不可逆、还要清磁盘产物。
    # 只影响列表接口（`GET /api/tasks`）；详情/下载/问答照旧可用，便于随时恢复。
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 回收站（2026-10-18）：非空 = 已删除（软删）。
    # 与 `archived_at` 的区别：归档是"藏起来但还在库里"，删除是"用户不要了"——
    # 但**先放回收站**，文件和子表都留着，恢复＝把这个字段清空；
    # 只有「彻底删除」才真删（子表 + 磁盘产物）。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    # 阅读状态（2026-10-14，B1）：todo（待读）/ reading（在读）/ done（已读）。
    # 为什么是 `tasks` 的列、不是关联表：**状态是文献自己的属性（跟文献走），
    # 集合是人的组织（跟人走）**——"标签可以迁移，但收藏集不能"。
    # 默认 `todo` 是一个决定：刚上传的文献，用户的默认意图就是"待读"，
    # 它直接喂「待读 N」这个入口。
    # ⚠️ 它与 `kind='status'` 的标签**不互为镜像、不做同步**（否则又是"改了 A 没改 B"）；
    # 也与块级曝光埋点不是一回事——前者是用户的状态，后者是进视口就记的分母。
    # 定义在**最后一列**：老库靠 ALTER 补列只能追加到末尾，两边顺序才对得上。
    reading_status: Mapped[str] = mapped_column(
        String(16), default="todo", nullable=False, server_default="todo", index=True
    )


class TaskHistory(Base):
    """历史记录：任务生命周期中的关键动作。"""

    __tablename__ = "task_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TaskBlock(Base):
    """单个文本块的翻译状态。失败必须可见，禁止静默截断。"""

    __tablename__ = "task_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    block_id: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[BlockState] = mapped_column(
        Enum(
            BlockState,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        default=BlockState.SUCCESS,
        index=True,
    )
    translated: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 版面信号（2026-09-30 起的契约）：`{"unit_h":…, "bold":…, "y0":…, "page_h":…}`。
    # **存原始信号、不存判定结果**——分级规则将来还会改，规则改了所有有信号的块一起受益；
    # 老任务这里是 NULL，分级器自动退回"只看文字形状"。
    # 字段含义见 scripts/extract_blocks.py。
    layout: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class TaskUnderstanding(Base):
    """论文导读/术语表的惰性计算结果（按需生成、缓存；失败可降级为"暂无"）。"""

    __tablename__ = "task_understanding"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id"), index=True, unique=True
    )
    guide_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="pending"
    )  # pending / ready / failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class User(Base):
    """账号：密码只存哈希（scrypt + 每人独立盐），绝不存明文。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")  # user / admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuthSession(Base):
    """登录会话：只存令牌的 sha256，可随时吊销（退出 / 踢设备）。"""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)


class AuthTicket(Base):
    """临时票据：给"带不了请求头"的三种请求用（进度推送 / PDF 预览 / 下载）。

    绑定 用户 + 任务 + 用途，60 秒内有效；**不一次性消费**——否则同一页面多次
    取 URL 会互相把票据用掉，表现为"有时能打开、有时打不开"。
    """

    __tablename__ = "auth_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    scope: Mapped[str] = mapped_column(String(16))  # files / events
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Collection(Base):
    """集合（可嵌套：`parent_id` 自指）。

    ⭐ 语义定死（照抄 Zotero，不发明第三种）：**子集合的文献不算在父集合里**——
    集合只含**直接成员**，计数＝直接成员数。展示层要给"含子集合共 N"，只能用
    括号辅数（`doc_count_deep`），**不改这里的语义**。
    ⚠️ 成环（把集合移进自己的后代）必须由**服务端**挡（`parent_id` 链上走一遍），
    返回 400——不许只靠前端。
    """

    __tablename__ = "collections"
    # 同一父下不许重名；不同父下可以同名
    __table_args__ = (UniqueConstraint("user_id", "parent_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    # null = 顶层集合
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("collections.id"), nullable=True, index=True
    )
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class TaskCollection(Base):
    """文献 ↔ 集合（多对多）。一篇文献可属多个集合。

    ⚠️ **别在这张表上盖更多东西**（权限 / 排序 / 备注一律不加）：埋点 2 要验证
    "多挂率 < 10% → 退化为 `tasks` 上的单选字段"，届时这张表要能一刀切掉。
    """

    __tablename__ = "task_collections"
    __table_args__ = (UniqueConstraint("task_id", "collection_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Tag(Base):
    """标签，分三类：主题 / 方法 / 状态（`kind`）。

    状态类最有价值——它驱动"我今天该干什么"。
    ⚠️ 与 `tasks.reading_status` 的关系要拎清：`reading_status` 是驱动
    「待读 / 在读 / 已读」三个入口的那一份数据（有索引、可高效筛）；`kind='status'`
    的标签是**用户自己额外打的**状态标签。两者**不互为镜像、不做同步**。
    """

    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("user_id", "kind", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))  # topic / method / status
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class TaskTag(Base):
    """文献 ↔ 标签。"""

    __tablename__ = "task_tags"
    __table_args__ = (UniqueConstraint("task_id", "tag_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class SmartCollection(Base):
    """智能集合＝已保存的搜索规则（**规则即数据**）。

    为什么把筛选规则做成一行数据、而不是几个 `if`：判据**不是文献有多少篇，而是
    规则有多少条、规则是不是数据**——筛选逻辑写在代码里时，加一条规则＝改代码＋
    测试；规则是数据时，加一条规则＝插一行表。**硬编码分支超过 2 处就回本**，
    而我们有待读 / 在读 / 已读三条，已经过线。
    本期只做**预置规则**（`builtin`，迁移时种下），不做用户自定义查询构建器：
    预置扩张同样走"插一行表"，**上限约 8–10 条**；超过说明该上"把当前筛选存为
    智能集合"那一档了。
    `query` 形状（冻结）：`{"all": [{"field": …, "op": …, "value": …}]}`，
    `field ∈ {reading_status, tag, collection, native, text_source}`、
    `op ∈ {eq, in, not_in}`。
    """

    __tablename__ = "smart_collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    query: Mapped[dict] = mapped_column(JSON)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Material(Base):
    """素材卡（**快照，不是活引用**）。

    ⭐⭐ 这张表的全部意义就在四个"创建时拷贝"的列：`text_quote` /
    `translated_quote` / `page` / `source_name`。判据是"**删掉源任务后素材卡仍显示
    出处**"——所以**不许 JOIN `tasks` 取 `source_name` / `page`**，那就退回活引用了。
    ⚠️ `task_id` 只用于"回跳原文"，源文献被删后置 null，**不级联删素材**；界面此时
    必须如实说"源文献已删除，仅存快照"，**不许做成死链装活链**。
    """

    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    block_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text_quote: Mapped[str] = mapped_column(Text)
    translated_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    page: Mapped[int] = mapped_column(Integer)
    source_name: Mapped[str] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )


class Draft(Base):
    """草稿（本期只存当前稿，**不建版本历史表**——需要时再加，别预建）。"""

    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body_md: Mapped[str] = mapped_column(Text, default="")
    # 期刊 / 学位论文模板标识：**本期只存标识，不做模板渲染**
    template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )


class Citation(Base):
    """引文：**插入时就生成并落库 CSL-JSON**。

    ⭐ `csl_json` 是 M4 格式检查的**唯一输入**（不接 Word、不做版面分析）；
    格式为 CSL-JSON 1.0.2 单条 item。
    ⭐ "点 `[1]` 回原文高亮"靠 `material_id` → `materials.task_id` / `block_id`；
    源文献已删（`task_id` 为 null）时如实说"源文献已删"。
    """

    __tablename__ = "citations"
    __table_args__ = (UniqueConstraint("draft_id", "order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), index=True)
    order: Mapped[int] = mapped_column(Integer)  # 文内引用编号
    csl_json: Mapped[dict] = mapped_column(JSON)
    anchor: Mapped[dict] = mapped_column(JSON)  # {block_id?, offset}：文内插入位置
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class CheckRun(Base):
    """收口检查的一次运行（契约 §2.7 / N22–N23）。

    **只存"一次运行 + 它出的那份报告"**，报告整体放 `report`（JSON）：
    报告的形状是契约冻的 `CheckReport`，为它拆成几张表反而不好回放。

    ⚠️ **不建"逐条处置"的表**：那是下一版的功能，契约 §5 明写**别预建**
    （与"草稿只存当前稿、不建版本历史表"同一个理由）。
    ⚠️ `ruleset_version` **单独存一列**（不只躺在 JSON 里）：以后翻旧报告、
    或者按版本统计"哪版规则准"，都要能直接筛。
    """

    __tablename__ = "check_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    draft_id: Mapped[int | None] = mapped_column(
        ForeignKey("drafts.id"), index=True, nullable=True
    )
    lang: Mapped[str] = mapped_column(String(16))
    citation_style: Mapped[str] = mapped_column(String(16))
    ruleset_version: Mapped[int] = mapped_column(Integer)
    report: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class MemoryEvent(Base):
    """L0 环节台账（**M2 写 / M5 读 / M7 吃** 三方共用的地基）。

    ⭐⭐ 它是"AI 使用台账"与"处理过程一屏"的**唯一真源**：`/api/memory-events`（N17）
    与 `/api/me/ledger`（N26）**同源**，**不许做两份台账**。
    ⚠️ `actor` 就是"数据流向"的证据：取字与扫描件 OCR 是真本地 → `local`；
    外文翻译、扫描件逐段翻译、导读 / 问答三条路发往云端模型 API → `api`。
    ⚠️ 口径红线：**不能讲"数据不出本机"**，只能讲"服务自持 + 文献存本地"。
    ⚠️ 写入方是**服务端**（前端只 GET），不许在前端手工埋点。
    """

    __tablename__ = "memory_events"
    __table_args__ = (
        Index("ix_memory_events_user_layer_created", "user_id", "layer", "created_at"),
        Index("ix_memory_events_task_id", "task_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    layer: Mapped[str] = mapped_column(String(8))  # L0 / L1 / L2（本期只写 L0）
    stage: Mapped[str] = mapped_column(
        String(32)
    )  # extract / translate / ocr / understanding / ask / cite / edit …
    actor: Mapped[str] = mapped_column(String(16))  # local / api / user
    tool: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 中性名
    summary: Mapped[str] = mapped_column(String(500))  # 人话一句，直接上台账界面
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class BlockEdit(Base):
    """埋点 1（分子）：译文修改。**M5 的逐条 diff 依赖它**。

    ⭐ 它是个人中心"哪些被人改过（可逐条看 diff）"的数据源——埋点先布、M5 才有数据；
    数据就位前那一区显示"暂无人改记录"（沿用诚实机制，不硬编）。
    ⭐ 附带收益：它是"**人改留痕**"的证据（哪些句是 AI 译的、哪些被学生改过），
    同时喂合规与材料。
    `text_hash` 存**原文哈希**而不是原文本身：省空间且够用。
    """

    __tablename__ = "block_edits"
    __table_args__ = (
        Index("ix_block_edits_task_id_block_id", "task_id", "block_id"),
        Index("ix_block_edits_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    block_id: Mapped[str] = mapped_column(String(64))
    text_hash: Mapped[str] = mapped_column(String(64))
    before: Mapped[str] = mapped_column(Text)  # 模型译文
    after: Mapped[str] = mapped_column(Text)  # 用户译文
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class BlockExposure(Base):
    """埋点 1（分母）：块曝光。同一 session 同一块只记一次（唯一约束即幂等）。

    ⚠️⚠️ 分期口径：**修改率 ＝ 被改块数 / 被曝光块数**，**不是 / 总块数**——
    一篇 212 块的文献只精读 80 块时，用 212 会把真实的 18% 稀释成 7%，
    直接改变"建 / 砍记忆"的结论。
    ⚠️ 生效前提：**观测期 ≥14 天且曝光块数 ≥500** 才允许判"建 / 砍"。
    ⚠️ 引用这个数字**必须带前提**："修改率是在提供了编辑入口的条件下测的"
    （入口本身会抬高修改率，观察者效应）。
    """

    __tablename__ = "block_exposures"
    __table_args__ = (UniqueConstraint("user_id", "task_id", "block_id", "session_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    block_id: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[str] = mapped_column(String(64))  # 前端一次打开阅读页一个
    entered_at: Mapped[datetime] = mapped_column(DateTime)
    left_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class MemoryItem(Base):
    """记忆条目（M7）：跨文献的**用法偏好**。

    ⚠️ **这张表不是台账**。台账是 `memory_events`（L0 环节流水："几点几分做了什么"）；
    记忆是**结论**（"这个人习惯把 `chiral` 叫手性"）。两者**不是一回事**，别混。
    ⚠️ 它也**不是素材卡**（数据模型 §4 那条）——素材是"从文献里取出的证据"，
    记忆是"这个人的说法与偏好"。

    `kind` 两种：
    - `term` —— 术语/译名偏好：`source` = 原文里的词，`target` = 这个人习惯的译法；
    - `cite` —— 引用习惯：`source` = 固定串 `default`，`target` = 习惯的引文格式。

    ⭐ **`hits` 是"这条记忆被真正用上过几次"**（注入到请求里算一次）。
    它的用处只有一个：让用户看得出**哪条真在起作用**——没被用过的条目是最该删的。
    界面上**如实显示**，不许当成"聪明度"吹。

    ⚠️ **源文献删了，记忆不删**：记忆挂在**用户**身上，不挂在任务上（所以没有 task_id）。
    ⚠️ **必须能改能删**（形态 §六）：用户改一条就覆盖 `target`；
    `enabled=false` 是"先别用，但别丢"。**系统不许背着人改**——
    只有用户自己（或他明确点头的动作）能写这张表。
    """

    __tablename__ = "memory_items"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "kind", "source", name="uq_memory_items_user_kind_source"
        ),
        Index("ix_memory_items_user_id_kind", "user_id", "kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # term / cite
    source: Mapped[str] = mapped_column(String(255))
    target: Mapped[str] = mapped_column(Text)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )


class UserPrefs(Base):
    """个人偏好（F 卡）：**一个人一行**，整包存 JSON。

    ⚠️ **为什么是 JSON 一列、而不是四列**：偏好是"键值一堆"，且**会继续长**
    （默认读法 / 默认档位 / 字号 / 动效 / 引文格式…）。加一个偏好就要改一次表结构、
    再写一次迁移脚本——那是拿 DDL 换一行配置，不值。
    代价是数据库层面查不了"谁的 defaultView 是 dual"，但**没有任何查询需要那么做**
    （唯一用法是"取这个人的偏好"和"整包写回"）。

    ⚠️ **它不是 `memory_items`**：那张是"用户的说法与习惯"、按条存、可增删；
    这张是**界面偏好**，一个用户一份、整包覆盖。

    ⚠️ **换设备要跟得上**（这张卡存在的理由）：偏好以前只在本机 `localStorage`，
    换台电脑就没了。现在**服务端是权威**，`localStorage` 降级成**缓存**——
    阅读页要**同步**读偏好（等不了网络往返），所以缓存必须留。
    """

    __tablename__ = "user_prefs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, index=True
    )
    # JSON 文本，形状如 `{"defaultView":"blocks","tier":"medium",...}`
    payload: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )
