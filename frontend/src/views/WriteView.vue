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
      <button class="btn ghost sm wr-helper-toggle" @click="helperOpen = !helperOpen">助手</button>
    </div>

    <!-- ==================== 三栏 ==================== -->
    <div class="wr-body">
      <!-- ---------- 素材区（资产层） ---------- -->
      <aside class="wr-materials">
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
      </aside>

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
          <button v-for="t in BUILTIN_TEMPLATES" :key="t.id" class="wr-tpl-item" @click="startTemplate(t)">
            <strong>{{ t.name }}</strong>
            <span class="wr-muted">{{ t.note }}</span>
          </button>
          <p class="wr-muted">
            ⚠️ 本期模板只把标识记在草稿上，不做版式渲染（契约 §2.7）——
            它不会替你写一个字，章节结构仍然由你自己搭。
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

          <textarea
            v-if="mode === 'edit'"
            ref="bodyEl"
            v-model="body"
            class="wr-editor"
            placeholder="正文由你来写……（用 # 写标题；从素材卡插入的引文就是 [1] 这样的编号）"
            aria-label="稿件正文"
            @keydown="onEditorKeydown"
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
            <!-- 红线写进界面：不代写正文（四家同类工具也都不写，我们照写清楚） -->
            <span class="wr-muted">写作页不代写正文——这里只帮你管素材、引文与出处。</span>
          </div>
        </template>
      </main>

      <!-- ---------- 助手：提纲 / 引用 / 过程 ---------- -->
      <aside class="wr-helper">
        <div class="tabs">
          <button
            v-for="tab in HELPER_TABS"
            :key="tab.key"
            :class="{ on: helperTab === tab.key }"
            @click="pickHelper(tab.key)"
          >
            {{ tab.label }}
          </button>
        </div>

        <div class="wr-helper-body">
          <!-- 对话：写作侧 agent（读草稿 / 查素材 / 找依据） -->
          <div v-if="helperTab === 'chat'" class="wr-chat">
            <AgentChat
              scene="write_compose"
              :scope="{ draft_id: currentDraft ? currentDraft.id : null }"
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
              跨会话的版本历史本期不做——草稿只存当前稿（契约 §5），
              所以这里只记「本次会话做过什么」，不假装有历史。
            </p>
          </div>
        </div>
      </aside>
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
 * ⚠️ **本页一个字都不替用户生成正文**。页面上没有任何"生成/续写/润色"入口，
 * 连注释里也不许出现——这是形态 §3.2 与作品红线共同要求的那条线。
 * 写作页只做三件事：把读文献时攒下的素材摆出来、把引文与出处管好、让你自己写。
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
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'

import AgentChat from '../components/AgentChat.vue'
import CiteChip from '../components/CiteChip.vue'
import EmptyState from '../components/EmptyState.vue'
import HonestNote from '../components/HonestNote.vue'
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
 * 内置模板（模板 / 大纲两个入口用）。
 *
 * ⚠️ **只给名字和章节清单，不给正文**：本期 template_id 只存标识、不做版式渲染（契约 §2.7），
 * 所以这里连"预填的骨架"都不写——**预填就等于替用户开了个头**，而这条线我们守死。
 */
const BUILTIN_TEMPLATES = [
  { id: 'tpl-journal', name: '期刊论文', note: '题名 · 摘要 · 引言 · 方法 · 结果 · 讨论 · 参考文献' },
  { id: 'tpl-thesis', name: '学位论文', note: '绪论 · 相关工作 · 方法 · 实验 · 结论' },
]

const HELPER_TABS = [
  { key: 'chat', label: '对话' },
  { key: 'outline', label: '提纲' },
  { key: 'cites', label: '引用' },
  { key: 'log', label: '过程' },
]

const bodyEl = ref(null)
const fileEl = ref(null)

/**
 * 切助手页签。⭐ 切到「引用」时顺手拉一次参考文献（N31）：
 * 用户切过来就是为看它的，不该再点一下才出。
 */
async function pickHelper(key) {
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
const helperTab = ref('outline')
const mode = ref('edit')
const sourceFilter = ref('')
const showTemplates = ref(false)
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
const previewBlocks = computed(() => buildPreviewBlocks(body.value))

const saveText = computed(() => {
  if (!currentDraft.value) return ''
  if (saveState.value === 'saving') return '保存中…'
  if (saveState.value === 'dirty') return '未保存'
  if (saveState.value === 'error') return `保存失败：${saveError.value}`
  if (saveState.value === 'saved') return savedAt.value ? `已保存 ${savedAt.value}` : '已保存'
  return '已同步'
})

// ============================================================ 取数

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

/** `Esc` 关抽屉（形态 §3.3：`Esc` 可关、点遮罩可关）。 */
function onWriteKeydown(event) {
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
    const draft = await newDraft(payload)
    showTemplates.value = false
    closeMenus()
    pane.value = 'doc'
    mode.value = 'edit'
    await nextTick()
    bodyEl.value?.focus()
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

function startTemplate(template) {
  return create({ title: '未命名草稿', templateId: template.id })
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

// ============================================================ 素材区动作

function pickDraft(draft) {
  closeMenus()
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
  bodyEl.value?.focus()
}

async function insertMaterial(material) {
  // 插在光标处；预览态下没有光标，就落到正文末尾
  const caret =
    mode.value === 'edit' && bodyEl.value ? bodyEl.value.selectionStart : body.value.length
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
  if (bodyEl.value) {
    bodyEl.value.focus()
    bodyEl.value.setSelectionRange(result.caret, result.caret)
  }
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
  const el = bodyEl.value
  if (!el) return
  el.focus()
  // 把光标放到那一行开头：浏览器会把它滚进视野，不用自己算像素
  el.setSelectionRange(item.offset, item.offset)
}

function onEditorKeydown(event) {
  if ((event.ctrlKey || event.metaKey) && (event.key === 's' || event.key === 'S')) {
    event.preventDefault()
    void saveWithFeedback()
  }
}
</script>
