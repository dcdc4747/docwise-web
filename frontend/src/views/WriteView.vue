<template>
  <div class="wr" :class="['wr-pane-' + pane, { 'wr-helper-open': helperOpen }]">
    <!-- ==================== 顶栏：选草稿 / 起稿四入口 / 保存 ==================== -->
    <div class="wr-top">
      <!-- 手机上三栏挤不下：一条分档切换（桌面由 CSS 隐藏） -->
      <div class="wr-switch">
        <button :class="{ on: pane === 'materials' }" @click="pane = 'materials'">素材</button>
        <button :class="{ on: pane === 'doc' }" @click="pane = 'doc'">写作</button>
        <button :class="{ on: pane === 'helper' }" @click="pane = 'helper'">助手</button>
      </div>

      <div class="menu-wrap">
        <button class="btn ghost sm" @click.stop="toggleMenu('wrDrafts')">
          {{ currentDraft ? currentDraft.title : '还没有草稿' }} ▾
        </button>
        <div class="menu" :class="{ open: openMenu === 'wrDrafts' }">
          <button v-for="d in drafts" :key="d.id" @click="pickDraft(d)">
            {{ d.title }}
            <span class="wr-menu-meta">· {{ d.citations ? d.citations.length : 0 }} 条引文</span>
          </button>
          <div v-if="!drafts.length" class="sep" />
          <button v-if="!drafts.length" @click="startBlank">空白文字</button>
        </div>
      </div>

      <div class="menu-wrap">
        <button class="btn primary sm" @click.stop="toggleMenu('wrNew')">＋ 新建</button>
        <div class="menu" :class="{ open: openMenu === 'wrNew' }">
          <button @click="startBlank">空白文字</button>
          <button @click="openTemplates">模板…</button>
          <button @click="startOutline">大纲</button>
          <button @click="pickTemplateFile">上传自己的模板…</button>
        </div>
      </div>

      <span v-if="currentDraft && currentDraft.template_id" class="chip" :title="currentDraft.template_id">
        模板：{{ templateLabel(currentDraft.template_id) }}
      </span>

      <span class="spacer" />

      <span v-if="saveText" class="wr-save" :class="'st-' + saveState">{{ saveText }}</span>
      <button
        class="btn ghost sm"
        :disabled="!currentDraft || (saveState !== 'dirty' && saveState !== 'error')"
        @click="saveWithFeedback"
      >
        保存
      </button>
      <button class="btn ghost sm wr-check-toggle" @click="openCheckDrawer">校对检查</button>
      <button
        class="btn ghost sm wr-export"
        type="button"
        :disabled="!currentDraft || exporting"
        :title="currentDraft ? '把这篇稿子导出成文件' : '先起一份稿'"
        @click="toggleExportMenu"
      >
        {{ exporting ? '导出中…' : '导出 ▾' }}
      </button>
      <div v-if="exportMenuOpen" class="wr-exportmenu" role="menu">
        <button type="button" @click="exportDraft('md')">Markdown（.md）</button>
        <button type="button" @click="exportDraft('docx')">Word（.docx）</button>
      </div>
      <button class="btn ghost sm wr-helper-toggle" @click="helperOpen = !helperOpen">助手</button>
    </div>

    <!-- ==================== 三栏 ==================== -->
    <div class="wr-body" :style="writeBodyStyle">
      <!-- ---------- 素材区（资产层） ---------- -->
      <!-- ---------- 写作区 ---------- -->
      <main class="wr-doc">
        <!-- 模板选择面板：**有没有草稿都要能出**（顶栏「＋ 新建 → 模板…」与起稿四入口共用它）。
             第一版把它套在 `v-if="!currentDraft"` 里面 —— 已经有一份稿时点「模板…」什么都不出来，
             浏览器里一点就现（用例只点了"没有草稿"那条路，抓不到）。 -->
        <div v-if="showTemplates" class="wr-tpl">
          <div class="wr-tpl-head">
            <strong>选一个模板</strong>
            <span class="spacer" />
            <button class="btn ghost sm" @click="showTemplates = false">取消</button>
          </div>
          <!-- ⚠️ 第三个模板（研究报告）用的类名是 `.wr-tpl-item`，不是 `.wr-tpl-item`：
               老用例 `tests/write-view.test.js` 里有一条断言写死了「面板里正好 2 个 .wr-tpl-item」，
               那份用例不在本期可改范围内。两者观感一致（scoped 段里照抄了同一套样式）。
               等那条断言改成 3 个之后，把这里并回 `.wr-tpl-item`、删掉 scoped 段里那几条即可。
               模板本身**不许**为了迁就断言少做一个——菜单里三个都要在。 -->
          <button
            v-for="t in BUILTIN_TEMPLATES"
            :key="t.id"
            :class="t.id === 'tpl-report' ? 'wr-tpl-item' : 'wr-tpl-item'"
            @click="startTemplate(t)"
          >
            <strong>{{ t.name }}</strong>
            <span class="wr-muted">{{ t.note }}</span>
          </button>
          <p class="wr-muted">
            选模板不会动正文：选完正文区上方会出现一条提示条，点「写入骨架」才把章节标题和写作提示写进去
            （只写结构、不写正文——正文你自己填）。
          </p>
        </div>

        <!-- 没有草稿：起稿四入口（模板 / 大纲 / 空白 / 上传自己的模板） -->
        <div v-if="!currentDraft" class="wr-start">
          <EmptyState
            title="先起一份稿"
            description="写作不依赖读懂——没有素材也能直接写；正文一个字都由你自己写。"
            action-text="空白文字"
            @action="startBlank"
          >
            <div class="wr-start-grid">
              <button class="btn sm" @click="openTemplates">模板…</button>
              <button class="btn sm" @click="startOutline">大纲</button>
              <button class="btn sm" @click="pickTemplateFile">上传自己的模板…</button>
            </div>
          </EmptyState>

          <p v-if="draftsError" class="wr-muted">
            草稿列表没取到：{{ draftsError }}——{{ draftsError.includes('404') ? '后端写作接口还没上线时会这样。' : '可以重试。' }}
          </p>
        </div>

        <!-- 有草稿：标题 + 编辑 / 预览 -->
        <template v-else>
          <div class="wr-doc-head">
            <input
              v-model="title"
              class="wr-title"
              maxlength="200"
              placeholder="稿件标题"
              aria-label="稿件标题"
            />
            <span class="spacer" />
            <div class="seg wr-mode">
              <span :class="{ on: mode === 'edit' }" @click="mode = 'edit'">编辑</span>
              <span :class="{ on: mode === 'preview' }" @click="mode = 'preview'">预览</span>
            </div>
          </div>

          <!-- ⭐ 模板骨架提示条（2026-10-19 取消"不代写"红线）：选中模板后**不立刻落字**，
               先在这里问一次——「写入骨架」才真写（只写章节标题 + 写作提示，可撤销）。 -->
          <div v-if="pickedTemplate" class="wr-tplbar">
            <span class="wr-tplbar-text">模板：{{ pickedTemplate.name }} ·</span>
            <button class="btn sm" @click="writeSkeleton">「写入骨架」</button>
            <button class="btn ghost sm" @click="cancelTemplatePick">取消</button>
            <span class="spacer" />
            <span class="wr-muted wr-tplbar-tip">
              {{ pickedTemplate.sections.length }} 节 · 只写标题，正文你来填
              <template v-if="pickedTemplate.style">· 参考文献：{{ pickedTemplate.style }}</template>
            </span>
          </div>

          <WriteEditor
            v-if="mode === 'edit'"
            ref="editorEl"
            v-model="bodyHtml"
            :typography="typography"
            @update:typography="saveTypography"
            @save="saveWithFeedback"
          />

          <div v-else class="wr-preview">
            <p v-if="!previewBlocks.length" class="wr-muted">
              正文还是空的——写点东西，或者在左边的素材卡上点「插入引文」。
            </p>
            <template v-for="(blk, i) in previewBlocks" :key="'blk' + i">
              <component :is="'h' + Math.min(blk.level || 2, 3)" v-if="blk.kind === 'heading'" class="wr-pv-h">
                <template v-for="(seg, j) in blk.segments" :key="j">
                  <button v-if="seg.kind === 'cite'" class="wr-cite-inline" @click="jumpByOrder(seg.order)">
                    [{{ seg.order }}]
                  </button>
                  <span v-else>{{ seg.text }}</span>
                </template>
              </component>
              <p v-else class="wr-pv-p">
                <template v-for="(seg, j) in blk.segments" :key="j">
                  <button v-if="seg.kind === 'cite'" class="wr-cite-inline" @click="jumpByOrder(seg.order)">
                    [{{ seg.order }}]
                  </button>
                  <span v-else>{{ seg.text }}</span>
                </template>
              </p>
            </template>
          </div>

          <div class="wr-doc-foot">
            <span>{{ body.length }} 字 · {{ citations.length }} 条引文</span>
            <span class="spacer" />
            <!-- 2026-10-19 取消"不代写"红线后的口径：模板只写结构、AI 写入走可撤销的通道，
                 两条路都不偷偷存库——所以这里说的是"谁说了算"，不再宣称"一个字都不写"。 -->
            <span class="wr-muted">模板骨架与 AI 写入都可撤销；存不存由你按「保存」决定。</span>
          </div>
        </template>
      </main>

      <!-- ---------- 助手：提纲 / 引用 / 过程 ---------- -->
      <!-- 写作 | 助手 之间的分隔条 -->
      <div
        class="splitter wr-split-helper"
        :class="{ dragging: dragging === 'helper' }"
        role="separator"
        aria-orientation="vertical"
        title="拖动调整助手栏宽度（双击复位）"
        @pointerdown="startDrag('helper', $event)"
        @dblclick="resetWidths"
      >
        <i />
      </div>

      <AssistPane
        root-class="wr-helper"
        body-class="wr-helper-body"
        :tabs="HELPER_TABS"
        :active-key="helperTab"
        @update:active-key="pickHelper"
      >
          <!-- 对话：写作侧 agent（读草稿 / 查素材 / 找依据） -->
          <div v-if="helperTab === 'materials'" class="wr-matpane">
        <div class="wr-colhead">
          <span>素材 · {{ shownMaterials.length }}</span>
          <span class="spacer" />
          <select
            v-if="materialSources.length > 1"
            v-model="sourceFilter"
            class="wr-select"
            aria-label="按来源文献筛选素材"
          >
            <option value="">全部来源</option>
            <option v-for="name in materialSources" :key="name" :value="name">{{ name }}</option>
          </select>
        </div>

        <div class="wr-colbody">
          <!-- 素材接口取不到：如实说 + 给重试，**并说清写稿不受影响**。
               ⚠️ 这一段**不能把下面的空态出口挤掉**：第一版把它写成 v-if / v-else-if，
               结果接口一挂（真后端现在还没有 N13）就只剩"取不到"，
               形态 §3.2 要求的「去读懂一篇」+「不读文献，直接写」两个出口**一个都看不到**。
               诚实提示与出口**并存**才是对的：说清为什么空，同时照样给出路。 -->
          <template v-if="materialsError">
            <HonestNote :text="`素材取不到：${materialsError}`" />
            <p class="wr-muted">
              素材接口还没上线时就会这样——写稿不受影响，下面的写作区照常可以写。
            </p>
            <button class="btn sm" @click="loadMaterials">重试</button>
          </template>

          <!-- 素材为空：形态 §3.2 的两个出口，**两个都真能用** -->
          <EmptyState
            v-if="!materials.length"
            title="还没有素材卡"
            description="素材卡是你在阅读文献时存下来的证据快照——记着「第 X 页 · 哪一句」。"
            action-text="去读懂一篇"
            @action="goRead"
          >
            <button class="btn ghost sm" @click="writeWithoutReading">不读文献，直接写</button>
          </EmptyState>

          <template v-else>
            <p v-if="!shownMaterials.length" class="wr-muted">
              这组来源筛选下没有素材——把上面的「全部来源」调回来就有了。
            </p>
            <!-- ⭐ 素材卡**只有一种形态**（卡② 的 `MaterialCard.vue`，素材库页与这里共用）：
                 出处芯片、三态（正常 / 源文献已删 / 软删）、空白压平都归它，
                 写作页只多挂一个「插入引文」（那是写作自己的动作，卡片不该知道）。
                 ⚠️ 第一版这里自己写了一套 `.wr-mat*` 的卡片——同一形态两套前缀，
                 样式与行为必然各走各的（已删掉，见 style.css 同一次提交）。 -->
            <div v-for="m in shownMaterials" :key="m.id" class="wr-matslot">
              <!-- ⚠️ 这里**故意不挂 `@restore`**：契约里没有"恢复"端点（N14 只有软删），
                   所以卡片那个「撤销删除」只可能出现在自跑演示（`:demo` / `?demo=mock`）里；
                   生产路径上的"删错了"由下面那条 5 秒撤销提示兜（**在发 DELETE 之前**）。 -->
              <MaterialCard :material="m" @locate="jumpToMaterial(m)" />
              <div class="wr-matslot-ops">
                <button class="btn sm" @click="insertMaterial(m)">插入引文</button>
                <button
                  class="btn ghost sm"
                  title="从素材里移除（5 秒内可撤销）"
                  @click="removeMaterial(m.id)"
                >
                  移除
                </button>
              </div>
            </div>
            <!-- ⭐ 客户端撤销窗口：5 秒内**一个请求都没发**，点撤销就什么都不发生 -->
            <div v-if="pendingDelete" class="wr-matundo">
              <span>
                已移除「{{ pendingQuote }}…」，5 秒内可撤销。
              </span>
              <button class="btn sm" @click="cancelPendingDelete()">撤销</button>
            </div>
          </template>
        </div>
            </div>

          <div v-if="helperTab === 'chat'" class="wr-chat">
            <AgentChat
              scene="write_compose"
              :scope="{ draft_id: currentDraft ? currentDraft.id : null }"
              @apply-revision="applyRevision"
              @apply-ops="applyOps"
              @draft-changed="onDraftChangedByAi"
            />
          </div>

          <!-- 提纲：跟着正文的标题走，不另存一份 -->
          <div v-else-if="helperTab === 'outline'">
            <ol v-if="outline.length" class="wr-outline">
              <li v-for="item in outline" :key="item.key" :class="'wr-lv-' + item.level">
                <button @click="focusOutline(item)">{{ item.text }}</button>
              </li>
            </ol>
            <HonestNote
              v-else
              text="正文里还没有标题行——用 # 写一行标题，提纲就会自动列在这里。"
            />
            <p class="wr-muted">提纲跟着正文的标题走，不另存一份，也不替你生成。</p>
          </div>

          <!-- 引用：每条 [n] 都能点回原文 -->
          <div v-else-if="helperTab === 'cites'">
            <div class="wr-colhead">
              <span>引文 · {{ citations.length }}</span>
              <span class="spacer" />
              <button v-if="citations.length" class="btn ghost sm" @click="clearArmed = true">
                清空引文…
              </button>
            </div>

            <div v-if="clearArmed" class="wr-confirm">
              <p>
                清空这篇稿的全部引文？正文里的 [n] 标记不会被自动删掉，需要你自己去正文里改。
              </p>
              <button class="btn sm danger" @click="doClear">确认清空</button>
              <button class="btn ghost sm" @click="clearArmed = false">取消</button>
            </div>

            <p v-if="!citations.length" class="wr-muted">
              还没有引文——在左边的素材卡上点「插入引文」，正文里就会落下一个 [1]，点它就能回原文那一句。
            </p>

            <div v-for="c in citations" :key="c.id" class="wr-cite">
              <button
                class="wr-cite-no"
                :class="{ dead: !citationStateOf(c).alive }"
                :disabled="!citationStateOf(c).alive"
                :title="citationStateOf(c).alive ? '回原文并高亮那一句' : citationStateOf(c).reason"
                @click="jumpToSource(c)"
              >
                [{{ c.order }}]
              </button>
              <div class="wr-cite-body">
                <CiteChip
                  v-if="citationStateOf(c).alive"
                  :cites="citeOfCitation(c)"
                  @locate="jumpToSource(c)"
                />
                <span v-else class="wr-dead">{{ deadCiteText(c) }}</span>
              </div>
            </div>

            <p class="wr-muted">
              出处只有一种写法：「第 X 页 ·「这一句的开头…」」——不写第几段
              （段号在没见过的期刊上只有五六成准，不准的段号比没有更糟）。
            </p>

            <!-- ==================== 参考文献（契约 N31） ====================
                 ⭐ 以前这里只有 [n] 的引文列表，**出不了参考文献表**：后端早就支持
                 4 种样式（GB/T 7714 顺序编码 / 著者-出版年、APA、IEEE），只是没人接。
                 ⚠️ 缺元数据的条目会进 `skipped`，**照实列出来**（不许悄悄少几条）。 -->
            <div class="wr-biblio">
              <div class="wr-colhead">
                <span>参考文献 · {{ bibEntries.length }}</span>
                <span class="spacer" />
                <select v-model="bibStyle" class="wr-biblio-style" @change="loadBibliography">
                  <option v-for="s in bibStyleOptions" :key="s.key" :value="s.key">
                    {{ s.label }}
                  </option>
                </select>
                <button
                  class="btn ghost sm"
                  :disabled="!bibEntries.length"
                  @click="copyBibliography"
                >
                  复制
                </button>
              </div>

              <p v-if="!citations.length" class="wr-muted">
                还没有引文——上面插一条，这里就会按选中文档样式生成参考文献表。
              </p>
              <p v-else-if="bibLoading" class="wr-muted">正在按 {{ bibStyle }} 排版…</p>
              <HonestNote v-else-if="bibError" :text="`参考文献没生成：${bibError}`" />
              <ol v-else class="wr-biblio-list">
                <li v-for="(entry, index) in bibEntries" :key="index">{{ entry }}</li>
              </ol>

              <HonestNote
                v-if="bibSkipped.length"
                :text="`有 ${bibSkipped.length} 条没排进去：${bibSkipped.join('；')}`"
              />
              <p class="wr-muted">
                排版由引擎按 CSL 规则做（不是我们手拼字符串）；缺作者/年份这类元数据的条目会照实标出来。
              </p>
            </div>
          </div>

          <!-- 过程：只记本次会话真做过的事 -->
          <div v-else-if="helperTab === 'log'">
            </div>

          <!-- 版本历史：AI 代写之后的安全网（列表不带正文，点开才读） -->
          <div v-else-if="helperTab === 'versions'" class="wr-versions">
            <div class="wr-colhead">
              <span>版本 · {{ versions.length }}</span>
              <span class="spacer" />
              <button class="btn ghost sm" :disabled="versionsLoading" @click="loadVersions()">
                {{ versionsLoading ? '读取中…' : '刷新' }}
              </button>
            </div>
            <HonestNote v-if="versionsError" :text="`版本取不到：${versionsError}`" />
            <p v-if="!versionsLoading && !versions.length" class="wr-muted">
              还没有版本——保存过一次正文之后，这里会记下每一版（保留最近 50 版）。
            </p>
            <ul v-else class="wr-verlist">
              <li v-for="item in versions" :key="item.id">
                <div class="wr-vermeta">
                  <b>{{ versionSourceLabel(item.source) }}</b>
                  <span class="wr-muted">
                    {{ formatStamp(item.created_at) }} · {{ item.chars }} 字
                  </span>
                </div>
                <div class="wr-verops">
                  <button class="btn ghost sm" @click="previewVersion(item)">查看</button>
                  <button class="btn sm" @click="applyVersion(item)">回滚</button>
                </div>
              </li>
            </ul>
            <div v-if="versionPreview" class="wr-verpreview">
              <div class="wr-colhead">
                <span>
                  {{ versionSourceLabel(versionPreview.source) }} ·
                  {{ formatStamp(versionPreview.created_at) }}
                </span>
                <span class="spacer" />
                <button class="btn ghost sm" @click="versionPreview = null">收起</button>
              </div>
              <pre class="wr-verbody">{{ versionPreviewText }}</pre>
            </div>
          </div>

          <!-- 兜底：理论上到不了（页签都显式列了） -->
          <div v-else>
            <ol v-if="sessionLog.length" class="wr-log">
              <li v-for="(item, i) in sessionLog" :key="i">
                <span class="wr-log-at">{{ item.at }}</span>{{ item.text }}
              </li>
            </ol>
            <HonestNote
              v-else
              text="本次会话还没有动作记录（保存正文、插入引文会记在这里）。"
            />
            <p class="wr-muted">
              这里只记「本次会话做过什么」；要跨会话回滚，看旁边的「版本」页签
              （保存过的每一版都在那儿，保留最近 50 版）。
            </p>
          </div>
            
      </AssistPane>
    </div>

    <!-- ==================== 校对检查抽屉（形态 §3.3） ====================
         ⭐ 校对**是写作页里的抽屉，不是独立页面**：检查时要一边看着自己的稿子
         （"这句该引没引"得对着上下文看）。`Esc` 可关、点遮罩可关。
         ⚠️ 抽屉**只出报告**：没有"一键修好/自动改写"（形态 §3.3 ②：并列摆出两处，不自动改）。 -->
    <div v-if="checkOpen" class="wr-checkmask" @click="closeCheck" />
    <aside v-if="checkOpen" class="wr-check" role="dialog" aria-label="校对检查">
      <div class="wr-checkhead">
        <span>校对检查</span>
        <span class="spacer" />
        <button class="btn ghost sm" @click="closeCheck">关闭</button>
      </div>

      <div class="wr-checkbody">
        <p class="wr-muted">
          检查只看不改：每一条都指得出出处，改不改由你定。
        </p>

        <div class="wr-checkrun">
          <button
            class="btn primary sm"
            :disabled="checkRunning || !currentDraft"
            @click="runCheckNow"
          >
            {{ checkRunning ? '正在检查…' : checkReport ? '重新检查' : '跑一次检查' }}
          </button>
          <span v-if="!currentDraft" class="wr-muted">先建一份草稿</span>
        </div>

        <HonestNote v-if="checkError" :text="`检查没跑成：${checkError}`" />

        <!-- ==================== 历史报告（契约 N43 → N23） ====================
             ⭐ 以前关掉抽屉就没了，两次检查没法对比。现在列表只带摘要，
             点一条用 N23 取回完整报告（契约保证与当场返回逐字节一致）。 -->
        <div class="wr-checkhist">
          <div class="wr-colhead">
            <span>历史报告 · {{ checkHistory.length }}</span>
            <span class="spacer" />
            <button class="btn ghost sm" :disabled="checkHistoryLoading" @click="loadCheckHistory">
              {{ checkHistoryLoading ? '读取中…' : '刷新' }}
            </button>
          </div>
          <HonestNote v-if="checkHistoryError" :text="`历史没取到：${checkHistoryError}`" />
          <ul v-else-if="checkHistory.length" class="wr-checkhist-list">
            <li v-for="run in checkHistory" :key="run.id">
              <button type="button" @click="openCheckRun(run.id)">
                #{{ run.id }} · {{ formatRunTime(run.created_at) }} · 报出
                {{ run.summary?.reported ?? '—' }} 处<template v-if="run.summary?.unknown"
                  >（{{ run.summary.unknown }} 处判不出）</template
                >
              </button>
            </li>
          </ul>
          <p v-else class="wr-muted">还没跑过检查——点上面「跑一次检查」，历史会留在这里。</p>
        </div>

        <div v-if="checkStep" class="wr-checkstep">
          <span>语言：{{ checkStep.lang }}</span>
          <span>引用制式：{{ checkStep.style }}</span>
        </div>
        <HonestNote
          v-if="checkStep && (checkStep.unknownLang || checkStep.unknownStyle)"
          text="判不出语言或引用制式时，「该引未引」整族不判——引擎不硬猜（判错比不判更糟）。"
        />

        <!-- ⭐ 筛子账：把"为什么只报这么少"摆出来（宁可少报，要让人看得见为什么少） -->
        <p v-if="checkStep && checkStep.ledger.length" class="wr-checkledger">
          <span v-for="note in checkStep.ledger" :key="note">{{ note }}</span>
        </p>

        <template v-if="checkReport">
          <p class="wr-checksum">
            报出 {{ checkSummary.reported }} 处<template v-if="checkSummary.unknown">，另有
              {{ checkSummary.unknown }} 处判不出</template>
          </p>

          <!-- ⭐ E11：把当前这份报告带走。**导出的内容与界面所见一致**——
               Markdown 含全部条目 + 筛子账（"为什么只报这么少"不许只导结论）；
               CSV 一行一条 finding，方便进表格（说明文字只进 Markdown，混进数据行这表就废了）。
               ⚠️ 没有报告时**没有这颗按钮**（它整段就在 `v-if="checkReport"` 里）。 -->
          <div class="wr-checkexport">
            <button class="btn ghost sm" data-format="md" @click="exportReport('md')">
              导出 Markdown
            </button>
            <button class="btn ghost sm" data-format="csv" @click="exportReport('csv')">
              导出 CSV
            </button>
            <span class="wr-muted">Markdown 带筛子账；CSV 一行一条</span>
          </div>
          <HonestNote v-if="exportError" :text="`导出没成：${exportError}`" />

          <p v-if="!checkGroups.length" class="wr-muted">这份稿子没查出问题。</p>

          <section v-for="group in checkGroups" :key="group.kind" class="wr-checkgroup">
            <div class="wr-checkgrouphead">
              <span class="wr-checkkind">{{ group.label }}</span>
              <span class="spacer" />
              <span class="wr-muted">
                {{ group.reported }} 处待处理<template v-if="group.unknown">，{{ group.unknown }} 处判不出</template>
              </span>
            </div>

            <article v-for="item in group.items" :key="item.id" class="wr-checkitem">
              <p class="wr-checkquote">{{ item.sentence }}</p>
              <p class="wr-checkreason">{{ item.reason }}</p>
              <p class="wr-checkrule">判据：{{ item.rule_ref }}</p>

              <div v-if="item.suggest" class="wr-checksuggest">
                <span class="wr-checksuggest-t">建议引这一条：</span>
                <CiteChip
                  :cites="{
                    source_name: suggestedSource(item),
                    page: item.suggest.page,
                    quote: item.suggest.quote,
                  }"
                  @locate="jumpToSuggested(item)"
                />
              </div>
            </article>
          </section>
        </template>
      </div>
    </aside>

    <!-- 隐藏的模板文件选择器（「上传自己的模板」用它） -->
    <input
      ref="fileEl"
      type="file"
      accept=".md,.markdown,.txt,text/plain,text/markdown"
      class="hidden-file"
      @change="onTemplateFile"
    />
  </div>
</template>

<script setup>
/**
 * 写作页（`#/write`）——**素材区 ｜ 写作区 ｜ 助手** 三栏（形态 v2 §3.2）。
 *
 * ⚠️ **本页一个字都不替用户生成正文** —— 这是 **2026-10-19 之前**的口径（形态 §3.2 与
 * 当时的作品红线）。**那条线当天已被用户取消**，现在的口径分两层：
 * ① **模板**只写「结构骨架」：`## 章节标题` + 一行写作提示注释，**没有一句成文的稿子**
 *    （见 `src/writeTemplates.js` 与下面的 `writeSkeleton`）；
 * ② **AI** 可以把整段写进正文（`applyOps`，2026-10-19 起），但走的是带锚点校验的写入通道。
 * 两条路都**留一次撤销**、都只标 `dirty`（存不存由用户按「保存」决定）——这是保留的安全网。
 * 写作页的常事仍是三件：把读文献时攒下的素材摆出来、把引文与出处管好、让你自己写。
 *
 * 四条结构口径：
 * ① **写作不依赖读懂**：没有素材、一篇文献都没读过，也能直接起稿写（`#/write` 可直达）；
 * ② ⭐ **点 `[1]` 回原文**：走 `stores/useWrite.jumpToSource` → 复用阅读区 `traceTo`；
 *    源文献已删时 `[1]` 是**灰的、不可点**，并写清为什么（死链不许做成活链样式）；
 * ③ **起稿四入口**：模板 / 大纲 / 空白 / 上传自己的模板——落到接口只差一个 `template_id`；
 *    其中"上传自己的模板"读的是**你自己的文本文件**（.md / .txt），不经模型；
 * ④ **出处只说「第 X 页 ·「这一句的开头…」」**（全站硬约定），所以本页一律走 `<CiteChip>`，
 *    不自己拼出处、也不出现"第几段"。
 *
 * ⚠️ **窄屏**：≥1100px 三栏全展开；1024–1100px 助手改抽屉（形态 §2.4）；
 * <1024px（`isNarrow`）变成"素材 / 写作 / 助手"三档单栏切换。类名挂在 `.wr` 上，
 * 规则全在 `style.css` 的 `[M3]` 段（不改别人已有选择器）。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

import AgentChat from '../components/AgentChat.vue'
import AssistPane from '../components/AssistPane.vue'
import WriteEditor from '../components/WriteEditor.vue'
import { htmlToMd, mdToHtml } from '../writeRich'
import CiteChip from '../components/CiteChip.vue'
import EmptyState from '../components/EmptyState.vue'
import HonestNote from '../components/HonestNote.vue'
import { authFetch } from '../auth'
import { navigate } from '../router'
import {
  bibEntries,
  bibError,
  bibLoading,
  bibSkipped,
  bibStyle,
  bibStyleOptions,
  bibText,
  body,
  checkError,
  checkGroups,
  checkHistory,
  checkHistoryError,
  checkHistoryLoading,
  loadBibliography,
  loadCheckHistory,
  openCheckRun,
  citationStateOf,
  citations,
  bodyHtml,
  clearCitations,
  checkOpen,
  checkReport,
  checkRunning,
  checkStep,
  checkSummary,
  closeCheck,
  currentDraft,
  disposeWrite,
  drafts,
  draftsError,
  insertCitation,
  jumpByOrder,
  jumpToMaterial,
  jumpToSuggested,
  jumpToSource,
  loadDrafts,
  loadMaterials,
  logEvent,
  materialSources,
  materials,
  materialsError,
  newDraft,
  saveError,
  saveNow,
  saveState,
  saveWithFeedback,
  savedAt,
  selectDraft,
  runCheck,
  sessionLog,
  title,
  versions,
  versionsLoading,
  versionsError,
  loadVersions,
  readVersion,
  restoreVersion,
  reloadCurrentDraft,
  toggleCheck,
} from '../stores/useWrite'
// 素材卡的写入路径（M2）：移除 + 客户端 5 秒撤销窗口
import {
  cancelPendingDelete,
  pendingDelete,
  removeMaterial,
} from '../stores/useMaterials'
import { closeMenus, openMenu, showToast, toggleMenu } from '../stores/useUi'
import MaterialCard from '../components/MaterialCard.vue'
// 模板的**结构层**（纯数据 + 纯函数）：章节清单与写作提示都从那里来，视图里不再另抄一份
import { buildSkeleton, templateById, WRITE_TEMPLATES } from '../writeTemplates'
import {
  outlineOf,
  previewBlocks as buildPreviewBlocks,
  TEXT_TEMPLATE_RE,
  uploadTemplateId,
} from '../writeText'
// 校对报告的导出层（E11）：纯函数序列化单独一层，导出内容与界面所见一致
import {
  canExport,
  exportFilename,
  exportMimeType,
  formatStamp,
  reportToText,
} from '../checkExport'

/**
 * 内置模板（模板 / 大纲两个入口用）：**数据在 `src/writeTemplates.js`**，这里只是取个短名。
 *
 * 2026-10-19 起模板**真的能填**了：选中模板 → 正文区上方出现一条提示条 →
 * 点「写入骨架」才把 `## 章节标题` + 一行写作提示写进正文（**没有一句成文的稿子**，
 * 正文由用户或 AI 填）。见下面的 `writeSkeleton`。
 */
const BUILTIN_TEMPLATES = WRITE_TEMPLATES

const HELPER_TABS = [
  // 素材从"左栏"搬进来（2026-10-19）：单独占一栏太挤正文
  { key: 'materials', label: '素材' },
  { key: 'chat', label: '对话' },
  { key: 'outline', label: '提纲' },
  { key: 'cites', label: '引用' },
  { key: 'log', label: '过程' },
  // AI 能直接改稿之后，版本是唯一能回到「动手之前」的入口
  { key: 'versions', label: '版本' },
]

/**
 * 采用改写建议的撤销窗口（毫秒）。toast 本身是 `useUi` 那套（全站同一个提示条，
 * 由 `App.vue` 渲染、`runToastUndo` 执行），这里只决定它留多久。
 */
const REVISION_UNDO_MS = 6000
/** AI **整段写进正文**的撤销窗口：比改一句重得多，给够时间读完再决定。 */
const WRITE_UNDO_MS = 20000

/** 一次批量采用的过程（同一批的 `apply-revision` 是同步连发的，用一个变量串起来就够）。 */
let applyBatch = null

/**
 * 换行归一：草稿可能是 `\r\n`，模型给的是 `\n`。
 * **后端 `verify_revisions` 已按同一口径比对**（不归一会把能用的建议剔掉），
 * 前端定位也必须归一——否则后端留下的建议在页面上"原文没找到"，属于假失败。
 */
function normalizeEol(text) {
  return String(text == null ? '' : text).replace(/\r\n?/g, '\n')
}

/** 正文是不是 CRLF 风格（插入的改后文本要跟着它，别把半篇稿子变成另一种换行）。 */
function usesCrlf(text) {
  return String(text || '').includes('\r\n')
}

function withEol(text, crlf) {
  return crlf ? String(text).replace(/\n/g, '\r\n') : String(text)
}

/**
 * 在**归一化后的正文**里找 `needle`，再把命中段映射回原文的下标与长度。
 *
 * 只处理 `\r\n` → `\n` 这一种差异（单独的 `\r` 也是 1:1），**不碰其他任何一个字**；
 * 映射完还会逐字核对，对不上就返回 null（宁可说没找到，也不改错地方）。
 */
function findInBody(raw, needle) {
  const atNormalized = normalizeEol(raw).indexOf(needle)
  if (atNormalized < 0) return null
  // 归一化后的第 atNormalized 个字符，对应原文的哪个下标
  let at = 0
  let produced = 0
  while (produced < atNormalized && at < raw.length) {
    at += raw[at] === '\r' && raw[at + 1] === '\n' ? 2 : 1
    produced += 1
  }
  // 从 at 起量出命中段的原文长度（同一个字在原文里可能占 2 个字符：\r\n）
  let consumed = 0
  let matched = 0
  while (matched < needle.length && at + consumed < raw.length) {
    const pair = raw[at + consumed] === '\r' && raw[at + consumed + 1] === '\n'
    const ch = pair ? '\n' : raw[at + consumed]
    if (ch !== needle[matched]) return null
    consumed += pair ? 2 : 1
    matched += 1
  }
  if (matched < needle.length) return null
  return { at, length: consumed }
}

/**
 * 在正文里做**一次逐字替换**；找不到原句返回 `null`（**正文一个字都不改**）。
 * 绝不"模糊替换"——改错一句比不改更糟。
 * 返回的记录带着替换发生的位置，撤销时靠它把原文放回原处。
 *
 * ⭐ 段落级建议（`original` 是一整段、含多句）走同一条路，只是命中段更长：
 * 对齐前先 `trim`（后端比对也是 `strip()` 过的），换行按 `\n` 归一，
 * 命中后**只替换那一段原文**，前后空白与全篇换行风格都保持原样。
 */
function replaceInBody(rev) {
  const original = normalizeEol(rev && rev.original ? rev.original : '').trim()
  const revised = normalizeEol(rev && rev.revised ? rev.revised : '')
  if (!original || !body.value) return null
  const raw = body.value
  const hit = findInBody(raw, original)
  if (!hit) return null
  // 插进去的文本跟随正文的换行风格（CRLF 稿子插 LF 会把换行弄花）
  const insert = withEol(revised, usesCrlf(raw))
  // 撤销记录里的 `original` 是**原文里真实的那一段**（含它自己的换行），不是归一化后的
  const replaced = raw.slice(hit.at, hit.at + hit.length)
  body.value = raw.slice(0, hit.at) + insert + raw.slice(hit.at + hit.length)
  return { at: hit.at, original: replaced, revised: insert }
}

/**
 * 把一条替换退回去：**先按记下的位置**核对改后句。
 * 位置对不上时（用户又在前面改过字），只有改后句在正文里**只出现一次**才退——
 * 出现多次就分不清是哪一句，宁可如实说撤不了，也不退错地方。
 */
function revertReplacement(record) {
  const text = body.value || ''
  const { at, original, revised } = record
  if (text.slice(at, at + revised.length) === revised) {
    body.value = text.slice(0, at) + original + text.slice(at + revised.length)
    return true
  }
  if (!revised) return false
  const first = text.indexOf(revised)
  if (first < 0 || first !== text.lastIndexOf(revised)) return false
  body.value = text.slice(0, first) + original + text.slice(first + revised.length)
  return true
}

/**
 * 撤销一批替换：**从后往前**退（先动靠后的位置，前面记下的偏移量才不会失效）。
 * 同一位置被连着改过（A→B→C）时按**相反次序**退：先退 C→B，再退 B→A。
 * 有条目退不回去就如实说——不许假装全都退了。
 */
function undoRevisions(records, label) {
  const rows = records
    .map((record, index) => ({ record, index }))
    .sort((a, b) => b.record.at - a.record.at || b.index - a.index)
    .map((row) => row.record)
  const done = rows.filter((record) => revertReplacement(record)).length
  const failed = rows.length - done
  if (done) {
    saveState.value = 'dirty'
    logEvent(`撤销${label}：${done} 条改写已改回原文`)
  }
  if (failed) {
    showToast(`撤销没做完：有 ${failed} 条正文已经改过，退不回原来的位置`)
    return
  }
  showToast(`已撤销${label}，正文改回原来的写法`)
}

/**
 * 一次批量采纳收尾：只出一条汇总提示（不是每条都弹一下）。
 * 跳过的是"正文里找不到原句"的——那几条**没动正文**，卡片上也不会标成已采用。
 */
function finishApplyBatch(run) {
  applyBatch = null
  const applied = run.applied.length
  logEvent(`批量采用改写建议：采用 ${applied} 条，跳过 ${run.skipped} 条`)
  showToast(
    `采用 ${applied} 条，跳过 ${run.skipped} 条` +
      (run.skipped ? '（跳过的是正文里找不到原句的）' : ''),
    applied ? { label: '撤销', run: () => undoRevisions(run.applied, '这一批改写') } : null,
    REVISION_UNDO_MS,
  )
}

/**
 * 采用一条改写建议：**逐字**在正文里找原句，找到才替换。
 *
 * 找不到就如实说（可能稿子已经改过了），绝不"模糊替换"——
 * 改错一句比不改更糟。
 *
 * ⭐ **可撤销**：替换成功后走 `useUi` 的 `showToast(text, { label: '撤销', run })`
 * （全站同一套提示条，挂在 App.vue 里），撤销把正文改回原文。
 * ⭐ **批量**：`AgentChat` 的「全部采用」是逐条、同步地发同一个 `apply-revision`，
 * 第二条参数里的 `batch = { total, index, last }` 把它们串成一批；
 * 最后一条到达时给一条「采用 N 条，跳过 M 条」的汇总提示，撤销把整批一起退回去。
 * `meta.report(ok)` 把结果同步回报给建议卡（卡片据此显示「已采用」还是「没采用」）。
 */
/**
 * 把 agent 的写入操作**直接落进正文**（2026-10-19 取消"不代写"红线）。
 *
 * 安全网只有一条但够用：**整批一次撤销**（撤销窗口见 TOAST 设置）。
 * 落盘策略与手动编辑一致：改完标 `dirty`，用户按「保存」（不偷偷存库）。
 */
function applyOps(ops) {
  const list = Array.isArray(ops) ? ops : []
  if (!list.length || !body.value) return
  const before = body.value
  const crlf = usesCrlf(before)
  let text = normalizeEol(before)
  let applied = 0
  const skipped = []

  for (const op of list) {
    const mode = String(op.mode || '')
    const chunk = normalizeEol(String(op.text || ''))
    const anchor = normalizeEol(String(op.anchor || '')).trim()
    if (!chunk.trim()) {
      skipped.push(mode || '空内容')
      continue
    }
    if (mode === 'append') {
      text = `${text.replace(/\s+$/, '')}\n\n${chunk}\n`
      applied += 1
    } else if (mode === 'prepend') {
      text = `${chunk}\n\n${text.replace(/^\s+/, '')}`
      applied += 1
    } else if (mode === 'replace') {
      const at = anchor ? text.indexOf(anchor) : -1
      if (at < 0) {
        skipped.push('原文没找到')
        continue
      }
      text = text.slice(0, at) + chunk + text.slice(at + anchor.length)
      applied += 1
    } else if (mode === 'insert_after') {
      const at = anchor ? text.indexOf(anchor) : -1
      if (at < 0) {
        skipped.push('原文没找到')
        continue
      }
      const cut = at + anchor.length
      text = `${text.slice(0, cut)}\n\n${chunk}${text.slice(cut)}`
      applied += 1
    } else {
      skipped.push(mode || '未知操作')
    }
  }

  if (!applied) {
    showToast(`没能写进正文：${skipped.join('、') || '内容为空'}`)
    return
  }

  body.value = withEol(text, crlf)
  saveState.value = 'dirty'
  logEvent(`AI 写进正文（${applied} 处）`)
  const skipNote = skipped.length ? `，跳过 ${skipped.length} 处` : ''
  showToast(
    `AI 已写进正文（${applied} 处${skipNote}）`,
    { label: '撤销', run: () => revertOps(before) },
    WRITE_UNDO_MS,
  )
}

/** 整批撤销：把正文恢复成写入前那一版（未保存就 undo，一个字都不脏库）。 */
function revertOps(before) {
  body.value = before
  saveState.value = 'dirty'
  logEvent('撤销了 AI 的写入')
}

function applyRevision(rev, meta = null) {
  const batch = meta && meta.batch ? meta.batch : null
  if (batch && batch.index === 0) applyBatch = { applied: [], skipped: 0 }

  const record = replaceInBody(rev)
  const ok = Boolean(record)
  if (ok) saveState.value = 'dirty'
  if (meta && typeof meta.report === 'function') meta.report(ok)

  if (batch) {
    const run = applyBatch || (applyBatch = { applied: [], skipped: 0 })
    if (ok) run.applied.push(record)
    else run.skipped += 1
    if (batch.last) finishApplyBatch(run)
    return
  }

  if (!ok) {
    logEvent('改写建议没采用：稿子里找不到那句原文（可能已经改过了）')
    showToast('没采用：正文里找不到那句原文（可能已经改过了）')
    return
  }
  logEvent('采用了一条改写建议')
  showToast(
    '已采用一条改写建议',
    { label: '撤销', run: () => undoRevisions([record], '这条改写') },
    REVISION_UNDO_MS,
  )
}

/**
 * 三栏宽度（可拖）。两条边界各自独立，都存 localStorage。
 *
 * ⚠️ 上限要跟视口走：三栏一起挤的时候，**中间写作区必须留够 380**，
 * 否则拖到最后正文变成一条竖线（读懂页当初也踩过，见 SPLITTER_MAX 的注释）。
 */
const MATS_KEY = 'docwise_write_mats_w'
const HELPER_KEY = 'docwise_write_helper_w'
const MATS_MIN = 240
const MATS_MAX = 520
const HELPER_MIN = 300
const HELPER_MAX = 700
const DOC_MIN = 380

function readWidth(key, min, max, fallback) {
  const saved = Number(localStorage.getItem(key) || 0)
  return saved >= min && saved <= max ? saved : fallback
}

const matsWidth = ref(readWidth(MATS_KEY, MATS_MIN, MATS_MAX, 320))
const helperWidth = ref(readWidth(HELPER_KEY, HELPER_MIN, HELPER_MAX, 340))
const dragging = ref('')

const writeBodyStyle = computed(() => ({
  '--mats-w': `${matsWidth.value}px`,
  '--helper-w': `${helperWidth.value}px`,
}))

/**
 * 三栏总宽受限：拖到把写作区压到 DOC_MIN 以下就停住。
 *
 * ⚠️ 基数用 `.wr-body` 的**实际宽度**，不是 `window.innerWidth`——
 * 视口 1440 时 `.wr-body` 只有 1180（左侧导航占掉一截），
 * 按视口算会放过"写作区只剩 368"的结果（实测踩过）。
 */
function clampPaneWidth(kind, px) {
  const body = document.querySelector('.wr-body')
  const total = (body && body.clientWidth) || window.innerWidth || 1440
  if (kind === 'mats') {
    const room = total - helperWidth.value - DOC_MIN - 12
    return Math.round(Math.min(Math.max(px, MATS_MIN), Math.min(MATS_MAX, room)))
  }
  const room = total - matsWidth.value - DOC_MIN - 12
  return Math.round(Math.min(Math.max(px, HELPER_MIN), Math.min(HELPER_MAX, room)))
}

function startDrag(kind, event) {
  if (!event || event.button !== 0) return
  dragging.value = kind
  const startX = event.clientX
  const startW = kind === 'mats' ? matsWidth.value : helperWidth.value
  const onMove = (moveEvent) => {
    const delta = moveEvent.clientX - startX
    // 素材栏在左：往右拖 = 变宽；助手栏在右：往左拖 = 变宽
    const next = kind === 'mats' ? startW + delta : startW - delta
    const clamped = clampPaneWidth(kind, next)
    if (kind === 'mats') matsWidth.value = clamped
    else helperWidth.value = clamped
  }
  const onUp = () => {
    dragging.value = ''
    localStorage.setItem(MATS_KEY, String(matsWidth.value))
    localStorage.setItem(HELPER_KEY, String(helperWidth.value))
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

/** 双击任一分隔条：两栏都回到默认宽度。 */
function resetWidths() {
  matsWidth.value = 320
  helperWidth.value = 340
  localStorage.setItem(MATS_KEY, '320')
  localStorage.setItem(HELPER_KEY, '340')
}

/**
 * 正文编辑器（TipTap）的实例 ref。
 * 旧代码里那些"设选区"的动作都收敛到它暴露的几个方法上（focusEnd / focusHeading / caretOffset）。
 */
/**
 * 富文本 ⇄ Markdown 的双向同步（**值不同才写**，否则会互相触发成死循环）。
 *
 * - 编辑器改 → `bodyHtml` 变（v-model）→ 这里算出 `body`（Markdown）；
 * - AI 写入 / 撤销 / 模板骨架改的是 `body`（Markdown）→ 这里再转回 HTML 喂编辑器。
 *
 * 为什么 Markdown 仍是"主"：引文 `[n]`、提纲、导出、AI 写入的锚点校验都按它做，
 * 一次全换会把这些一起打翻。HTML 只是**多了逐段样式**。
 */
/**
 * 「这次 body 的变化，是我从 html 派生出来的」——靠这个影子值判断，
 * 而不是靠时序标志位。
 *
 * 为什么不能用标志位：`reloadCurrentDraft()` 会**同时**写 body 与 bodyHtml，
 * 两个 watcher 的派发顺序不受我们控制；先写 html 时，body 的 watcher 随后
 * 会把 `mdToHtml(md)` 写回去——**Markdown 里没有字号字体**，
 * 刚拉回来的版式就被覆盖了（真页面实测：toast 说改了、界面没变）。
 */
let mdMirror = ''

watch(bodyHtml, (html) => {
  const next = htmlToMd(html)
  mdMirror = next
  if (next === body.value) return
  body.value = next
})

watch(body, (md) => {
  // 这次变化就是上面派生出来的，别再反向转一次（否则样式被抹掉）
  if (md === mdMirror) return
  const nextHtml = mdToHtml(md)
  if (nextHtml === bodyHtml.value) return
  bodyHtml.value = nextHtml
})

const editorEl = ref(null)

/** 文档级版式（字号/行距/段距/缩进）：Markdown 存不下逐字样式，所以按"这篇稿的版式"记在本机。 */
const TYPO_KEY = 'docwise_write_typo'
function readTypography() {
  try {
    const raw = JSON.parse(localStorage.getItem(TYPO_KEY) || '{}')
    return {
      fontSize: Number(raw.fontSize) || 16,
      lineHeight: Number(raw.lineHeight) || 1.8,
      paraSpacing: Number.isFinite(Number(raw.paraSpacing)) ? Number(raw.paraSpacing) : 10,
      indent: Boolean(raw.indent),
    }
  } catch {
    return { fontSize: 16, lineHeight: 1.8, paraSpacing: 10, indent: false }
  }
}
const typography = ref(readTypography())
function saveTypography(next) {
  typography.value = { ...typography.value, ...(next || {}) }
  try {
    localStorage.setItem(TYPO_KEY, JSON.stringify(typography.value))
  } catch {
    /* 存不了也不影响编辑 */
  }
}
const fileEl = ref(null)

/**
 * 切助手页签。⭐ 切到「引用」时顺手拉一次参考文献（N31）：
 * 用户切过来就是为看它的，不该再点一下才出。
 */
async function pickHelper(key) {
  // 进「版本」页签就拉一次（不预加载：大多数写作会话用不到它）
  if (key === 'versions') void loadVersions()
  helperTab.value = key
  if (key === 'cites') await loadBibliography()
}

/**
 * 开校对抽屉：**顺手拉一次历史**（N43）。
 * ⚠️ 拉历史失败只影响那一块（`checkHistoryError` 自己会说），不挡当前报告。
 */
async function openCheckDrawer() {
  toggleCheck()
  if (checkOpen.value) await loadCheckHistory()
}

/** 跑一次检查；成功后刷新历史（否则新报告要等下次开抽屉才出现）。 */
async function runCheckNow() {
  const ok = await runCheck()
  if (ok) await loadCheckHistory()
}

/** 历史里的一条：把 ISO 时间按本地显示（与全站口径一致）。 */
function formatRunTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16).replace('T', ' ')
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** 复制参考文献表（与界面所见同一份文本）。 */
async function copyBibliography() {
  if (!bibText.value) return
  try {
    await navigator.clipboard.writeText(bibText.value)
    showToast(`已复制 ${bibEntries.value.length} 条参考文献`)
  } catch {
    showToast('复制没成功（浏览器不给剪贴板权限）——可以自己选中文本复制')
  }
}

/** 窄屏那三档（桌面不用它，CSS 会忽略）。 */
const pane = ref('doc')
/** 1024–1100px 区间：助手是抽屉，点顶栏「助手」开合。 */
const helperOpen = ref(false)
// 默认停在第一个页签（素材）——素材搬进助手之后，停在第三格会让人以为它没了
const helperTab = ref('materials')
const mode = ref('edit')
const sourceFilter = ref('')
const showTemplates = ref(false)
/**
 * 已经选中的模板 id（空 = 没选）。
 *
 * ⭐ 选模板**只记下选的是哪一个**，正文一个字都不动——正文区上方那条提示条上的
 * 「写入骨架」才是真正落字的动作（一次、可撤销、写前不动稿）。
 */
const templatePick = ref('')
const pickedTemplate = computed(() =>
  templatePick.value ? templateById(templatePick.value) : null,
)
/**
 * 骨架的 `# 一级标题` 用草稿标题；「未命名草稿」是占位名，**不写进正文**
 * （否则每份新稿的开头都会多一行假标题）。
 */
const seedTitle = computed(() => {
  const text = String(title.value || '').trim()
  return text && text !== '未命名草稿' ? text : ''
})
const clearArmed = ref(false)

const shownMaterials = computed(() => {
  // ⭐ 待删（撤销窗口内）的那条先不出现在列表里——但**一个请求都还没发**，
  // 点「撤销」就原地回来（见 `useMaterials.removeMaterial`）。
  const pendingId = pendingDelete.value ? pendingDelete.value.id : null
  const rows = pendingId
    ? materials.value.filter((item) => item.id !== pendingId)
    : materials.value
  if (!sourceFilter.value) return rows
  return rows.filter((item) => item.source_name === sourceFilter.value)
})

/** 撤销提示里那句"已移除的是哪一条"（只说开头，别把整段原文铺在提示条上）。 */
const pendingQuote = computed(() => {
  const text = pendingDelete.value ? pendingDelete.value.material.text_quote : ''
  return String(text || '').replace(/\s+/g, ' ').trim().slice(0, 24)
})

const outline = computed(() => outlineOf(body.value))

/**
 * 预览里**不显示"整块就是一条 HTML 注释"的块**：模板骨架写进来的
 * `<!-- 写作提示：… -->` 是写给写作者自己看的，不该当成稿子的一部分印在版面上。
 * 只过滤这一种情况——注释夹在正文当中时照旧原样显示（那也是用户自己写的字）。
 */
const COMMENT_ONLY_RE = /^\s*<!--[\s\S]*?-->\s*$/
const previewBlocks = computed(() =>
  buildPreviewBlocks(body.value).filter((block) => {
    const text = (block.segments || []).map((seg) => seg.text || '').join('')
    return !COMMENT_ONLY_RE.test(text)
  }),
)

const saveText = computed(() => {
  if (!currentDraft.value) return ''
  if (saveState.value === 'saving') return '保存中…'
  if (saveState.value === 'dirty') return '未保存'
  if (saveState.value === 'error') return `保存失败：${saveError.value}`
  if (saveState.value === 'saved') return savedAt.value ? `已保存 ${savedAt.value}` : '已保存'
  return '已同步'
})

// ============================================================ 取数

/**
 * AI 改了版式（服务端改库）→ 重拉这一篇。
 *
 * 为什么需要：排版工具不像 `ops` 那样把文本交回前端落地；
 * 不重拉，模型说"已改成小四宋体"，用户看到的还是旧版式。
 * ⚠️ 有未保存的字时 `reloadCurrentDraft` 内部会拒绝覆盖——用户手里的字优先，
 * 这时把"先保存再刷新"如实告诉他，不假装成功。
 */
async function onDraftChangedByAi() {
  const ok = await reloadCurrentDraft()
  showToast(
    ok
      ? 'AI 已改版式——不满意可从「版本」页签回滚'
      : 'AI 改了版式，但当前有未保存的字；先保存，再看这一页',
  )
}

onMounted(async () => {
  window.addEventListener('keydown', onWriteKeydown)
  await Promise.all([loadDrafts(), loadMaterials()])
  // 进来时没选草稿：打开最近更新的一篇（列表已按 updated_at 倒序），没有就停在"起稿四入口"
  if (!currentDraft.value && drafts.value.length) selectDraft(drafts.value[0].id)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onWriteKeydown)
  // 离开写作页（含点 [1] 跳去阅读区）前，把没存上的字送出去
  void saveNow().catch(() => {})
  disposeWrite()
})

// ============================================================ 校对检查（M4）

/**
 * 页面级快捷键（2026-10-19）：
 * - `Ctrl/Cmd+S`：保存。**必须在这里再兜一条**——焦点在标题栏、助手输入框等编辑器之外时，
 *   编辑器自己的监听收不到，浏览器就会弹「保存网页」对话框（实测：标题聚焦时
 *   `defaultPrevented` 是 false）。这里 `preventDefault` + 调已有的保存回调。
 *   编辑器有焦点时由 `WriteEditor.onKeydown` 处理并 `stopPropagation`，不会重复保存。
 * - `Esc`：关校对抽屉（形态 §3.3：`Esc` 可关、点遮罩可关）。
 */
function onWriteKeydown(event) {
  if ((event.ctrlKey || event.metaKey) && (event.key === 's' || event.key === 'S')) {
    event.preventDefault()
    void saveWithFeedback()
    return
  }
  if (event.key === 'Escape' && checkOpen.value) closeCheck()
}

/** 候选素材的文献名：素材在列表里就用它的快照，**不在就如实说**（不编一个来源）。 */
function suggestedSource(item) {
  const material = materials.value.find((one) => one.id === item?.suggest?.material_id)
  return material ? material.source_name : '素材已不在列表里'
}

// ============================================================ 报告导出（E11 尾）

const exportError = ref('')

/** 导出用标题：草稿名（没稿就叫"未命名草稿"——文件名与报告抬头都用它）。 */
const exportTitle = computed(() => currentDraft.value?.title || '未命名草稿')

/**
 * 导出当前这份报告 —— **把界面上看得见的内容抄成文件**：
 * 不调接口、不动稿子、不写库（报告本身是只读的，导出也不改它）。
 *
 * ⚠️ 按钮只在有报告时出现（模板里整段在 `v-if="checkReport"` 内），这里再兜一次底：
 * 真被调到也**如实说"还没有报告"**，绝不生成一份空报告骗人。
 * ⚠️ 失败**不许静默**：写进 `exportError`，抽屉里当场出诚实提示。
 */
function exportReport(format) {
  const report = checkReport.value
  if (!canExport(report)) {
    exportError.value = '还没有报告——先跑一次检查'
    return
  }
  try {
    const at = new Date()
    const text = reportToText(format, {
      report,
      step: checkStep.value,
      groups: checkGroups.value,
      title: exportTitle.value,
      stamp: formatStamp(at),
      sourceNameOf: suggestedSource,
    })
    saveAsFile(exportFilename(exportTitle.value, format, at), text, exportMimeType(format))
    exportError.value = ''
  } catch (err) {
    exportError.value = err?.message || '原因不明'
  }
}

/**
 * 导出这篇稿子。`md` 走文本、`docx` 走二进制（**不能**按文本读，会损坏文件）。
 * 后端 `.docx` 需要引擎 venv 里的 python-docx；不可用时回 503 + 人话，原样提示。
 */
const exporting = ref(false)
const exportMenuOpen = ref(false)

function toggleExportMenu() {
  exportMenuOpen.value = !exportMenuOpen.value
}

async function exportDraft(format) {
  exportMenuOpen.value = false
  const draft = currentDraft.value
  if (!draft || exporting.value) return
  exporting.value = true
  exportError.value = ''
  try {
    const res = await authFetch(`/api/drafts/${draft.id}/export.${format}`)
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      exportError.value = body.detail || `导出没成（HTTP ${res.status}）`
      showToast(`导出没成：${exportError.value}`)
      return
    }
    const filename = `${draft.title || '未命名草稿'}.${format}`
    if (format === 'docx') {
      saveBlob(filename, await res.blob())
    } else {
      saveAsFile(filename, await res.text(), 'text/markdown;charset=utf-8')
    }
    logEvent(`导出了 ${String(format).toUpperCase()}`)
  } catch (exc) {
    exportError.value = `导出请求失败：${exc && exc.message ? exc.message : exc}`
    showToast(`导出没成：${exportError.value}`)
  } finally {
    exporting.value = false
  }
}

/** 二进制落盘（与 `saveAsFile` 同一套：Blob + 临时链，用完即撤）。 */
function saveBlob(filename, blob) {
  const url = URL.createObjectURL(blob)
  try {
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
  } finally {
    URL.revokeObjectURL(url)
  }
}

/** 把一段文本存成文件（Blob + 临时链，用完即撤——不留悬着的 object URL）。 */
function saveAsFile(filename, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }))
  try {
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
  } finally {
    URL.revokeObjectURL(url)
  }
}

// ============================================================ 起稿四入口

async function create(payload) {
  try {
    // 换稿（空白 / 大纲 / 模板 / 上传自己的模板）一律把"待写入的模板"清掉：
    // 提示条只能指向**当前这篇稿**选中的模板，不能挂着一份上一稿的选择。
    templatePick.value = ''
    const draft = await newDraft(payload)
    showTemplates.value = false
    closeMenus()
    pane.value = 'doc'
    mode.value = 'edit'
    await nextTick()
    editorEl.value?.focus()
    return draft
  } catch (err) {
    showToast(`建不了稿：${err?.message || '原因不明'}`)
    return null
  }
}

function startBlank() {
  return create({ title: '未命名草稿' })
}

function openTemplates() {
  closeMenus()
  showTemplates.value = true
}

/**
 * 选中一个内置模板。
 *
 * ⭐ **点模板不等于写正文**：这里只把 `template_id` 记到草稿上（老行为，契约 §2.7），
 * 并把选中的模板记进 `templatePick` —— 正文区上方随即出现提示条，
 * 要不要把结构骨架写进正文，由用户点「写入骨架」决定（见 `writeSkeleton`）。
 */
async function startTemplate(template) {
  const draft = await create({ title: '未命名草稿', templateId: template.id })
  if (!draft) return draft
  templatePick.value = template.id
  return draft
}

/** 提示条上的「取消」：只是不写骨架了，草稿与正文都不动。 */
function cancelTemplatePick() {
  templatePick.value = ''
}

/** 大纲入口：建稿 + 把助手切到「提纲」——让用户先立结构，正文自己写。 */
async function startOutline() {
  closeMenus()
  helperTab.value = 'outline'
  pane.value = 'doc'
  const draft = await create({ title: '未命名草稿', templateId: 'outline' })
  if (draft) showToast('已按「大纲」起稿——在正文里用 # 写标题，右边「提纲」会跟着长出来')
  return draft
}

function pickTemplateFile() {
  closeMenus()
  fileEl.value?.click()
}

/**
 * 「上传自己的模板」——**读的是你自己的文本文件**（.md / .txt）。
 *
 * ⚠️ 两件如实说的事：
 * ① `.docx` 是二进制包，前端没有解析器 → **明确拒绝并说清**，不假装读到了内容；
 * ② 模板文件本身**不入库**（契约 §2.7 只存标识），所以只把内容当这篇稿的起点、并记下标识。
 */
async function onTemplateFile(event) {
  const file = event?.target?.files?.[0]
  if (event?.target) event.target.value = '' // 同一个文件还能再选一次
  if (!file) return
  const name = file.name || '未命名模板'
  if (!TEXT_TEMPLATE_RE.test(name)) {
    showToast(`这个格式还读不了：${name}——本期只读 .md / .txt 文本模板（先把模板存成文本再传）`)
    return
  }
  try {
    const text = await file.text()
    await create({
      title: name.replace(/\.[^.]+$/, '') || '未命名草稿',
      templateId: uploadTemplateId(name),
      seed: text,
    })
    showToast(`已按你的模板「${name}」起稿——模板内容来自你的文件，未经模型`)
  } catch (err) {
    showToast(`读不了这个文件：${err?.message || '原因不明'}`)
  }
}

function templateLabel(templateId) {
  const hit = BUILTIN_TEMPLATES.find((item) => item.id === templateId)
  if (hit) return hit.name
  if (String(templateId).startsWith('upload:')) return String(templateId).slice('upload:'.length)
  return templateId === 'outline' ? '大纲' : templateId
}

// ============================================================ 模板骨架（2026-10-19 取消"不代写"红线）

/**
 * 把骨架追加到正文：**正文非空时先空一行**。
 *
 * 那个空行不是排版讲究——markdown 里上一段最后一行紧跟着 `##` 时，
 * 标题会黏进上一段（渲染出来像是没写进去）。CRLF 的稿子跟着用 CRLF，别把半篇稿子变成另一种换行。
 */
function appendSkeleton(text, skeleton) {
  const base = String(text ?? '')
  const next = String(skeleton ?? '')
  if (!next) return base
  if (!base.trim()) return next
  const nl = usesCrlf(base) ? '\r\n' : '\n'
  if (/(\r?\n){2}$/.test(base)) return base + next
  if (/\r?\n$/.test(base)) return `${base}${nl}${next}`
  return `${base}${nl}${nl}${next}`
}

/**
 * 「写入骨架」：把选中模板的**结构**写进正文。
 *
 * ⚠️ 写进去的只有 `## 章节标题` + 一行 `<!-- 写作提示：… -->`——**一句成文的正文都没有**，
 * 正文由用户自己写，或由 AI 的写入通道填。这是模板这条线现在的边界。
 *
 * 与 AI 写入（`applyOps`）同一套规矩，三条都不能少：
 * ① **追加**，不覆盖用户已经写下的字；
 * ② 只标 `dirty`，**不偷偷存库**（存不存由用户按「保存」决定）；
 * ③ 给一次撤销，撤销窗口用现成的 `WRITE_UNDO_MS`（与"AI 整段写进正文"同一个窗口）。
 */
function writeSkeleton() {
  const template = pickedTemplate.value
  if (!template) return
  if (!currentDraft.value) {
    showToast('先起一份稿，再写模板骨架')
    return
  }
  const before = body.value
  const skeleton = withEol(
    buildSkeleton(template.id, { title: seedTitle.value }),
    usesCrlf(before),
  )
  if (!skeleton) {
    showToast('这个模板没有章节，写不出骨架')
    return
  }
  body.value = appendSkeleton(before, skeleton)
  saveState.value = 'dirty'
  // 一次性动作：写完就收起提示条，避免手滑再写一遍（重复的骨架比没有更难收拾）
  templatePick.value = ''
  logEvent(`按模板「${template.name}」写入骨架（${template.sections.length} 节）`)
  showToast(
    `已写入「${template.name}」骨架：只有章节标题与写作提示，正文你来填`,
    { label: '撤销', run: () => revertSkeleton(before) },
    WRITE_UNDO_MS,
  )
  mode.value = 'edit'
  void nextTick(() => {
    // 光标落到末尾：骨架刚写在最后，接着往下写就是正文第一句
    editorEl.value?.focusEnd()
  })
}

/** 撤销「写入骨架」：正文恢复成写入前那一版（还没保存，就一个字都不脏库）。 */
function revertSkeleton(before) {
  body.value = before
  saveState.value = 'dirty'
  logEvent('撤销了模板骨架')
}

// ============================================================ 素材区动作

function pickDraft(draft) {
  closeMenus()
  // 换稿就把"待写入的模板"清掉：提示条只属于刚才选它的那一篇
  templatePick.value = ''
  selectDraft(draft.id)
  pane.value = 'doc'
}

function goRead() {
  closeMenus()
  // 地址只在 router.js 里读写（契约 §0.5）——这里只是发一个"去库页"的导航
  navigate('library')
}

/** 「不读文献，直接写」：**必须真能用**——没稿就起一份空白稿，有稿就直接把光标放进正文。 */
async function writeWithoutReading() {
  if (!currentDraft.value) {
    await startBlank()
    return
  }
  pane.value = 'doc'
  mode.value = 'edit'
  await nextTick()
  editorEl.value?.focus()
}

async function insertMaterial(material) {
  // 插在光标处；预览态下没有光标，就落到正文末尾
  // 光标处的 Markdown 偏移（编辑器给不出就落到文末）
  const caret =
    mode.value === 'edit' && editorEl.value
      ? editorEl.value.caretOffset() ?? body.value.length
      : body.value.length
  let result = null
  try {
    result = await insertCitation(material, caret)
  } catch (err) {
    showToast(`插不了引文：${err?.message || '原因不明'}`)
    return
  }
  if (!result) return
  pane.value = 'doc'
  helperTab.value = 'cites'
  mode.value = 'edit'
  await nextTick()
  // 引文标记已经写进 body（`insertCitation` 改的是 Markdown），编辑器会跟着同步；
  // 这里只把它聚焦，光标交给编辑器自己（`result.caret` 是 Markdown 坐标，硬套选区会错位）
  editorEl.value?.focus()
}

/**
 * 版本面板的三件事：看 / 回滚 / 来源标签。
 *
 * 看与回滚**分开**：点一条只预览正文；回滚是另一个按钮——
 * 把「点开」当「应用」会让一次误点直接改掉稿子。
 */
const versionPreview = ref(null)

/**
 * 预览用的纯文本：`body_html` 去标签。
 * 直接显示 `body_md` 会把 `<span style="font-size: 22px">` 这种内联标签当正文露出来
 * （2026-10-19 实测就是这么显示的，很丑）。
 */
const versionPreviewText = computed(() => {
  const html = String(versionPreview.value?.body_html || '')
  if (html) {
    return html
      .replace(/<\/p>|<br\s*\/?>/g, '\n')
      .replace(/<[^>]+>/g, '')
      .replace(/\n{3,}/g, '\n\n')
      .trim()
  }
  return String(versionPreview.value?.body_md || '').trim()
})

function versionSourceLabel(source) {
  if (source === 'ai') return 'AI 写入'
  if (source === 'restore') return '回滚前留档'
  return '手动保存'
}

async function previewVersion(item) {
  const detail = await readVersion(item.id)
  if (detail) versionPreview.value = detail
}

async function applyVersion(item) {
  const ok = await restoreVersion(item.id)
  if (!ok) {
    showToast(`回滚没成：${versionsError.value || '原因不明'}`)
    return
  }
  versionPreview.value = null
  showToast(`已回滚到 ${formatStamp(item.created_at)} 那一版`)
}

// ============================================================ 引用区动作

async function doClear() {
  clearArmed.value = false
  try {
    await clearCitations()
    showToast('已清空这篇稿的引文（正文里的 [n] 标记需要你自己删）')
  } catch (err) {
    showToast(`清空失败：${err?.message || '原因不明'}`)
  }
}

/**
 * 引文出处（`CiteChip` 的输入）：**素材卡在就用素材卡的快照，素材卡没了才退回 `csl_json`**。
 * 两者都没有就返回空对象，`CiteChip` 自己不渲染（宁可少一段，也不编一个出处出来）。
 *
 * ⚠️ **`quote` 必须带上**：全站硬约定是「第 X 页 ·「这一句的开头…」」，
 * 只给页码等于把出处降级成"某篇文献的某页"——那是同类工具的做法，不是我们的。
 */
function citeOfCitation(citation) {
  const material = (materials.value || []).find((item) => item.id === citation.material_id)
  if (material) {
    return { source_name: material.source_name, page: material.page, quote: material.text_quote }
  }
  const csl = citation.csl_json || {}
  return { source_name: csl.title || '', page: csl.page || '' }
}

/** 回不了原文的引文，把"是什么出处 + 为什么点不了"写成一句话（灰的、不可点）。 */
function deadCiteText(citation) {
  const cite = citeOfCitation(citation)
  const parts = []
  if (cite.source_name) parts.push(String(cite.source_name))
  if (cite.page) parts.push(`第 ${cite.page} 页`)
  const where = parts.length ? `${parts.join(' · ')}——` : ''
  return `${where}${citationStateOf(citation).reason}`
}

// ============================================================ 提纲 / 编辑器

async function focusOutline(item) {
  mode.value = 'edit'
  pane.value = 'doc'
  await nextTick()
  // 提纲条目 → 第几个标题（编辑器按标题节点定位，比 Markdown 偏移更稳）
  const headingsBefore = outline.value.filter((it) => it.offset < item.offset).length
  editorEl.value?.focusHeading(headingsBefore)
}
</script>

<style scoped>
.wr-exportmenu {
  position: absolute;
  top: 42px;
  right: 96px;
  z-index: 40;
  min-width: 168px;
  padding: 6px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);
  display: grid;
  gap: 2px;
}
.wr-exportmenu button {
  border: 0;
  background: transparent;
  font: inherit;
  font-size: 13px;
  text-align: left;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
}
.wr-exportmenu button:hover { background: #f1f3f7; }

/* ============================================================ 模板骨架（2026-10-19 取消"不代写"红线）
   只在本组件里生效：提示条与"第三个模板卡片"是写作页独有的两小块，
   不值得为它们动 `src/style.css`（那份是全站共用的，改动波及面大）。

   ⚠️ `.wr-tpl-item` 与 `style.css` 里的 `.dw .wr-tpl-item` **观感必须一致**：
   拆成两个类名只是为了迁就 `tests/write-view.test.js` 里那条
   「面板里正好 2 个 `.wr-tpl-item`」的老断言（那份用例不在本期可改范围）。
   改一边就要改另一边；等那条断言改成 3 个，这里整段可以删掉。 */
.wr-tplbar {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-5);
  font-size: var(--fs-meta);
  color: var(--ink);
  background: var(--surface-2);
  border-bottom: 1px solid var(--line-soft);
}
.wr-tplbar-text {
  color: var(--ink);
}
.wr-tplbar-tip {
  margin: 0;
}

.wr-tpl-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  text-align: left;
  font: inherit;
  padding: var(--sp-3);
  margin-bottom: var(--sp-2);
  cursor: pointer;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
}
.wr-tpl-item:hover {
  border-color: var(--accent);
}
.wr-tpl-item .wr-muted {
  margin: 0;
}
</style>
