<template>
  <!-- 桌面工具条：< 1024px 整条不渲染（手机端的顶栏是 .ptop，原型就是这么分开的）；
       手机要用的下载 / 更多 跟着搬到 .ptop 上，功能一个不少 -->
  <div v-if="!isNarrow" class="reader-top">
    <button class="btn ghost sm" @click="backToLibrary">← 我的论文</button>
    <span class="fname">{{ currentTask.filename }}</span>
    <!-- 档位只读；想换档请在「更多」菜单里以其他档位重新翻译（会新建任务） -->
    <span class="chip" title="上传时选定；想换档请在「更多」里以其他档位重新翻译（会新建任务）">
      {{ currentTask.native ? '中文文献 · 不翻译' : tierTextMap[currentTask.tier] || currentTask.tier }}
    </span>
    <div class="menu-wrap">
      <span class="chip" role="button" tabindex="0" @click.stop="toggleMenu('mode')">
        {{ docModeLabel }} ▾
      </span>
      <div class="menu" :class="{ open: openMenu === 'mode' }">
        <button v-for="item in docModeOptions" :key="item.value" @click="setDocMode(item.value)">
          {{ item.label }}
        </button>
      </div>
    </div>
    <span class="spacer" />
    <!-- 1024–1099 档：右栏改抽屉，这里是它唯一的开关（其余宽度下 CSS 把它藏起来）。
         图标随开合变（收起时「拉出来」、展开时「推回去」），文案也跟着变，别让人猜。 -->
    <button
      class="btn ghost sm btn-ic assist-toggle"
      :class="{ on: assistDrawerOpen }"
      :aria-expanded="assistDrawerOpen ? 'true' : 'false'"
      title="助手：问答 / 导读 / 术语"
      @click="toggleAssistDrawer"
    >
      <Icon :name="assistDrawerOpen ? 'chev-double-right' : 'chev-double-left'" class="sm" />
      {{ assistDrawerOpen ? '收起助手' : '助手' }}
    </button>
    <button class="btn ghost sm btn-ic" @click="toggleSearch"><Icon name="search" class="sm" /> 搜索</button>
    <span v-if="pageChipText" class="chip">{{ pageChipText }}</span>
    <!-- 下载入口只有一个，命名统一为「下载译稿」，两项在里面选 -->
    <div class="menu-wrap">
      <button class="btn ghost sm btn-ic" title="下载译稿" @click.stop="toggleMenu('dl')">
        <Icon name="download" class="sm" /> 下载译稿 ▾
      </button>
      <div class="menu" :class="{ open: openMenu === 'dl' }">
        <button v-for="item in downloadOptions" :key="item.key" @click="runDownload(item)">
          {{ item.label }}
        </button>
      </div>
    </div>
    <!-- 单层级、6 项、任意两项不共享动词 -->
    <div class="menu-wrap">
      <button class="btn ghost sm" title="更多" @click.stop="toggleMenu('more')">
        <Icon name="more" class="sm" />
      </button>
      <div class="menu" :class="{ open: openMenu === 'more' }">
        <button @click="openPanel('info', currentTask)">文档信息</button>
        <button :disabled="!canRetryCurrent" @click="retryCurrent">重试翻译（本档）</button>
        <button @click="openPanel('retier', currentTask)">换档位重译…</button>
        <button @click="openPanel('blocks', currentTask)">详情</button>
        <button @click="openPanel('feedback', currentTask)">问题反馈…</button>
        <div class="sep" />
        <button class="danger" @click="openDeletePanel">删除…</button>
      </div>
    </div>
  </div>

  <!-- 极细进度条：永远在；不确定时画流动条纹（桌面；手机端用它自己的 .progress-line） -->
  <div v-if="!isNarrow" class="thin-bar" :class="{ striped: thinBar.striped }">
    <i :style="{ width: thinBar.width }" />
  </div>

  <!-- 空的时候必须真的是空的：原型靠 .note-line:not(:empty) 决定要不要那条分隔线 -->
  <div v-if="!isNarrow" class="note-line">
    <div v-if="searchOpen" class="search-row">
      <input
        v-model="searchTerm"
        class="search-input"
        placeholder="在这篇文献的正文里找…"
        @keydown.enter="runSearch"
      />
      <button class="btn sm" @click="runSearch">查找</button>
      <button class="btn ghost sm" @click="toggleSearch">关闭</button>
    </div>
    <template v-else-if="noteLineText">{{ noteLineText }}</template>
  </div>

  <div class="reader-body" :style="readerBodyStyle">
    <!-- 左栏 · 段落精读（自己的 DOM，出处锚点才成立） -->
    <div
      v-if="!isNarrow && docMode === 'paragraph'"
      ref="docPaneEl"
      class="doc-pane"
      @scroll="onPaneScroll"
    >
      <div v-if="scannedNotice" class="card doc-note">
        这份文献是扫描件：文字由本地 OCR 识别，可能有个别错字；出处与引用都按识别结果给出。
      </div>
      <div v-if="noBlockTranslationNotice" class="card doc-note">
        这篇文献暂无「块级」译文（译文在 PDF 产物里，段落视图拿不到），下面显示的是原文；
        问答与检索同样基于原文。
      </div>
      <div v-if="showOutline" class="toc">
        <button class="toc-head" @click="outlineOpen = !outlineOpen">
          <span>目录 · {{ tocItems.length }} 节</span>
          <i>{{ outlineOpen ? '收起' : '展开' }}</i>
        </button>
        <ol v-if="outlineOpen" class="toc-list">
          <li
            v-for="(item, index) in tocItems"
            :key="item.blockId || 'x' + index"
            :style="{ '--toc-depth': item.depth || 0 }"
          >
            <button
              v-if="item.blockId"
              class="toc-item"
              :class="'toc-' + item.type"
              @click="goOutline(item)"
            >
              <span class="toc-text">{{ item.text }}</span>
              <span class="toc-page">{{
                item.page === null || item.page === undefined ? '' : `第 ${item.page + 1} 页`
              }}</span>
            </button>
            <!-- ⚠️ `block_id` 为 null：这一条**确实在作者声明的目录里**，所以照实显示；
                 但它对不上正文块、**点了没处去** → **不可点**（不是 button、没有 hover），
                 「死链不许做成活链样式」是本仓硬规矩。 -->
            <span
              v-else
              class="toc-item toc-item-static"
              :class="'toc-' + item.type"
              title="这一条对不上正文块，暂不能跳转"
            >
              <span class="toc-text">{{ item.text }}</span>
            </span>
          </li>
        </ol>
      </div>
      <div v-if="!docPages.length" class="card doc-note">{{ docEmptyText }}</div>
      <template v-else>
        <div
          v-for="(page, pageIndex) in docPages"
          :key="page.key"
          :ref="(el) => setPageEl(page.page, el)"
          class="page"
          :data-page-key="page.key"
          @mouseup="onDocMouseUp($event, $event.currentTarget)"
        >
          <h3>{{ pageIndex === 0 ? docTitle : page.label }}</h3>
          <div v-if="pageIndex === 0" class="authors">{{ docMetaLine }}</div>
          <div class="cols">
            <p
              v-for="row in page.rows"
              :key="row.block.block_id"
              :id="row.block.block_id"
              :ref="(el) => setBlockEl(row.block.block_id, el)"
              :data-block-id="row.block.block_id"
              :title="'原文块 ' + row.block.block_id"
              :class="{
                anchor: flashId === row.block.block_id,
                flash: flashId === row.block.block_id,
                sel: pickedBlockId === row.block.block_id,
                ['pg-' + (row.block.type || 'body')]: true,
              }"
              @click="onBlockClick(row, $event)"
            >
              <span v-if="hasBlockTranslations" class="en">{{ row.source }}</span>
              {{ row.main }}
              <!-- ⭐ 人改留痕：这一句不是模型译的（AI 披露口径的一部分）。
                   ⚠️ **段落精读有两条渲染路径**（桌面 `.page .cols p` / 手机 `.pdoc .zh`），
                   **两边都要标**——只接一条的话，桌面读文献的人**看不到改动痕迹**，
                   而"人改过"正是我们对 AI 披露的核心口径（真踩过：手机那条有、桌面这条漏了）。
                   判据与手机那条**一字不差**：同一个 `editedBlockIds`，不各判一套。 -->
              <span
                v-if="editedBlockIds.has(row.block.block_id)"
                class="pg-edited"
                title="这一句由人改过，不是模型的译文"
              >已人工修改</span>
              <!-- ⭐ 合规 #147：这一段现在还是模型的译文 → 标出来。
                   ⚠️ **段落精读有两条渲染路径**（桌面 `.page .cols p` / 手机 `.pdoc .zh`），
                   两边都要标（只接一条的话，桌面读文献的人看不到这个标注——真踩过）；
                   ⚠️ 人改过的**不再标「AI 翻译」**（改过的句子不该被说成模型译的）。 -->
              <AiBadge
                v-if="blockHasTranslated(row.block) && !editedBlockIds.has(row.block.block_id)"
                kind="translate"
              />
            </p>
          </div>
          <button
            v-if="selChip && selChip.pageKey === page.key"
            class="selchip"
            :style="{ left: selChip.left + 'px', top: selChip.top + 'px' }"
            @mousedown.prevent
            @mouseup.stop
            @click="askSelectedSentence"
          >
            <svg class="ic-inl" aria-hidden="true"><use href="#i-info" /></svg>
            就这句提问
          </button>
          <!-- ⭐ 入口①：划词浮标上的「存为素材」（与"就这句提问"同一处、同一个 store）。
               ⚠️ 它必须是**兄弟节点**，不能塞进上面那个 `<button>` ——按钮套按钮是非法结构。 -->
          <MaterialSaveButton
            v-if="selChip && selChip.pageKey === page.key && selChip.blockId"
            class="selchip-save"
            variant="chip"
            :task-id="currentTask && currentTask.id"
            :block-id="selChip.blockId"
            :style="{ left: selChip.left + 'px', top: Math.max(0, selChip.top - 34) + 'px' }"
          />
        </div>
      </template>
    </div>

    <!-- 左栏 · 原版 / 纯中文 / 双语 PDF：pdf.js 渲染（有文字层，所以能定位、能点段落提问） -->
    <div v-else-if="!isNarrow" class="doc-pane pdf-mode">
      <PdfPane
        :task-id="currentTask.id"
        :variant="docMode"
        :doc-page-count="docPageCount"
        :start-page="pdfStartPage"
        :locate-text="locateText"
        :locate-key="locateKey"
        :fallback-page="pdfFallbackPage"
        :has-dual="fileAvailability.dual"
        @locate="onPdfLocate"
        @ask="onPdfAsk"
        @page-change="(n) => (currentPage = n)"
      />
    </div>

    <!-- 手机 · 顶栏是 .ptop（原型手机屏就是这么一根），不是桌面那条 reader-top -->
    <div v-else class="mobile-reader">
      <div class="ptop">
        <button class="btn ghost sm ptop-icon" @click="backToLibrary">←</button>
        <span class="spacer" />
        <span class="fname">{{ currentTask.filename }}</span>
        <span class="spacer" />
        <button class="btn ghost sm ptop-icon" :title="mobileOriginalTitle" @click="toggleMobileOriginal">
          {{ docMode === 'paragraph' ? pdfQuickLabel : '段落' }}
        </button>
        <!-- 下载入口只有一个名字（「下载译稿 ▾」），手机上不例外 -->
        <div class="menu-wrap">
          <button class="btn ghost sm ptop-icon" title="下载译稿" @click.stop="toggleMenu('dl')">
            <Icon name="download" class="sm" />
          </button>
          <div class="menu" :class="{ open: openMenu === 'dl' }">
            <button v-for="item in downloadOptions" :key="item.key" @click="runDownload(item)">
              {{ item.label }}
            </button>
          </div>
        </div>
        <div class="menu-wrap">
          <button class="btn ghost sm ptop-icon" title="更多" @click.stop="toggleMenu('more')">
            <Icon name="more" class="sm" />
          </button>
          <div class="menu" :class="{ open: openMenu === 'more' }">
            <button @click="openPanel('info', currentTask)">文档信息</button>
            <button :disabled="!canRetryCurrent" @click="retryCurrent">重试翻译（本档）</button>
            <button @click="openPanel('retier', currentTask)">换档位重译…</button>
            <button @click="openPanel('blocks', currentTask)">详情</button>
            <button @click="openPanel('feedback', currentTask)">问题反馈…</button>
            <div class="sep" />
            <button class="danger" @click="openDeletePanel">删除…</button>
          </div>
        </div>
      </div>
      <div class="progress-line">
        <span>{{ pageChipText || stageText }}</span>
        <div class="pl-bar" :class="{ striped: thinBar.striped }"><i :style="{ width: thinBar.width }" /></div>
        <span>{{ statusTextMap[currentTask.status] }}</span>
      </div>
      <!-- 菜单说明这类一次性提示，手机上没有 note-line 可挂，就挂在进度行下面（有内容才占位） -->
      <div v-if="noteLineText" class="note-line">{{ noteLineText }}</div>
      <div class="reader-ctrls">
        <span>
          字号
          <button class="rc-btn" @click="stepFont(-1)">A-</button>
          <button class="rc-btn" @click="stepFont(1)">A+</button>
        </span>
        <span class="spacer" />
        <span v-if="isNativeTask" class="on">原文中文</span>
        <div v-else class="menu-wrap">
          <button class="rc-btn on" @click.stop="toggleMenu('dual')">{{ mobileLangLabel }} ▾</button>
          <div class="menu" :class="{ open: openMenu === 'dual' }">
            <button
              v-for="item in docModeOptions"
              :key="item.value"
              :disabled="item.value === docMode"
              @click="setDocMode(item.value)"
            >
              {{ item.label }}
            </button>
          </div>
        </div>
      </div>
      <div v-if="docMode === 'paragraph'" class="pdoc" :style="pdocStyle">
        <div v-if="scannedNotice" class="honest pdoc-note">
          这份文献是扫描件：文字由本地 OCR 识别，可能有个别错字。
        </div>
        <div v-if="noBlockTranslationNotice" class="honest pdoc-note">
          这篇文献暂无「块级」译文（译文在 PDF 产物里）——下面显示的是原文。
        </div>
        <div v-if="showOutline" class="toc">
          <button class="toc-head" @click="outlineOpen = !outlineOpen">
            <span>目录 · {{ tocItems.length }} 节</span>
            <i>{{ outlineOpen ? '收起' : '展开' }}</i>
          </button>
          <ol v-if="outlineOpen" class="toc-list">
            <li
              v-for="(item, index) in tocItems"
              :key="item.blockId || 'x' + index"
              :style="{ '--toc-depth': item.depth || 0 }"
            >
              <button
                v-if="item.blockId"
                class="toc-item"
                :class="'toc-' + item.type"
                @click="goOutline(item)"
              >
                <span class="toc-text">{{ item.text }}</span>
                <span class="toc-page">{{
                  item.page === null || item.page === undefined ? '' : `第 ${item.page + 1} 页`
                }}</span>
              </button>
              <!-- 同上一处：`block_id` 为 null 的条目照实显示、**不可点**（见上面那段注释） -->
              <span
                v-else
                class="toc-item toc-item-static"
                :class="'toc-' + item.type"
                title="这一条对不上正文块，暂不能跳转"
              >
                <span class="toc-text">{{ item.text }}</span>
              </span>
            </li>
          </ol>
        </div>
        <div v-if="!paragraphRows.length" class="card doc-note">{{ docEmptyText }}</div>
        <template
          v-for="row in pdocRows"
          :key="row.kind === 'page' ? 'sep-' + row.page : row.block.block_id"
        >
          <div v-if="row.kind === 'page'" class="pg-sep">{{ row.label }}</div>
          <template v-else>
            <div
              :id="'m_' + row.block.block_id"
              :ref="(el) => setBlockEl(row.block.block_id, el)"
              :data-block-id="row.block.block_id"
              class="pg"
              :class="[
                'pg-' + (row.block.type || 'body'),
                { flash: flashId === row.block.block_id },
              ]"
            >
              <!-- 触发热区收窄到「段 N」标签本身（不与系统选词 / 滚动抢手势） -->
              <span
                class="seg-no"
                :class="{ 'seg-btn': row.index !== null }"
                :title="row.index !== null ? '点段号提问' : ''"
                @click="togglePgChip(row)"
              >
                {{ row.index !== null ? row.label : '—' }}
              </span>
              <div>
                <div v-if="hasBlockTranslations" class="en">{{ row.source }}</div>
                <div class="zh">
                  {{ row.main }}
                  <!-- ⭐ 人改留痕：这一句不是模型译的（AI 披露口径的一部分） -->
                  <span
                    v-if="editedBlockIds.has(row.block.block_id)"
                    class="pg-edited"
                    title="这一句由人改过，不是模型的译文"
                  >已人工修改</span>
                  <!-- ⭐ 合规 #147：这一段现在还是模型的译文 → 标出来。
                       ⚠️ 人改过的**不再标「AI 翻译」**（改过的句子不该被说成模型译的）——
                       两者共用 `editedBlockIds` 这一个判据，互斥，不各判一套。 -->
                  <AiBadge
                    v-if="blockHasTranslated(row.block) && !editedBlockIds.has(row.block.block_id)"
                    kind="translate"
                  />
                </div>
              </div>
            </div>
            <div v-if="pgChipFor === row.block.block_id" class="pg-chip-row">
              <button class="pg-chip" @click="askParagraph(row)">
                就这段提问
              </button>
              <!-- 没有译文的块不给编辑入口：那本来就是"暂无块级译文"的诚实档 -->
              <button
                v-if="blockHasTranslated(row.block)"
                class="pg-chip pg-chip-edit"
                @click="startEdit(row)"
              >
                改译文
              </button>
            </div>
            <div v-if="editFor === row.block.block_id" class="pg-edit">
              <label class="pg-edit-label" :for="'edit_' + row.block.block_id">
                改这一段的译文（原文不动；存下之后这一句会标成「已人工修改」）
              </label>
              <textarea
                :id="'edit_' + row.block.block_id"
                v-model="editDraft"
                class="pg-edit-box"
                rows="4"
              ></textarea>
              <p v-if="editError" class="pg-edit-error">{{ editError }}</p>
              <div class="pg-edit-ops">
                <button class="btn primary" :disabled="savingEdit" @click="saveEdit(row)">
                  {{ savingEdit ? '存档中…' : '存下这一改' }}
                </button>
                <button class="btn" :disabled="savingEdit" @click="cancelEdit">
                  取消
                </button>
              </div>
            </div>
          </template>
        </template>
      </div>
      <!-- 手机上的「原版」：同一套 pdf.js 视图，换的是容器 -->
      <div v-else class="pdoc-pdf">
        <PdfPane
          :task-id="currentTask.id"
          :variant="docMode"
          :doc-page-count="docPageCount"
          :start-page="pdfStartPage"
          :locate-text="locateText"
          :locate-key="locateKey"
          :fallback-page="pdfFallbackPage"
        :has-dual="fileAvailability.dual"
          @locate="onPdfLocate"
          @ask="onPdfAsk"
          @page-change="(n) => (currentPage = n)"
        />
      </div>
    </div>

    <!-- 桌面：正文与助手之间的**可拖拽分隔条**（手机走抽屉，不需要） -->
    <div
      v-if="!isNarrow"
      class="splitter"
      :class="{ dragging: splitterDragging }"
      role="separator"
      aria-orientation="vertical"
      title="拖动调整正文 / 助手宽度（双击复位）"
      @pointerdown="startSplitterDrag"
      @dblclick="resetSplitter"
    >
      <i />
    </div>

    <!-- 助手区：桌面 = 右栏；手机 = 底部抽屉三档。**同一份 DOM**，只有容器类名不同 -->
    <div :class="assistClass">
      <template v-if="isNarrow">
        <div class="grip" @click="cycleSheet">
          <i /><span>{{ sheetGripText }}</span>
        </div>
        <div class="peek-summary">{{ peekSummary }}</div>
        <div v-if="locatedHint" class="peek-line">
          {{ locatedHint }} · 正文已滚到该段 ·
          <button class="sample-link" @click="sheetState = 'half'">点我回来</button>
        </div>
      </template>

      <!-- 1024–1099：抽屉是全高 fixed，展开后会**盖住顶栏那个开关**，
           所以抽屉自己必须有一个关闭键（否则只剩 Esc 一条路）。其余宽度 CSS 藏起来。
           ⚠️ 放在 `.tabs` **外面**：`.tabs` 的契约是"只有三个页签"
           （`app.smoke.test.js` 直接断言 `tabs.map(text)` 恰好是 问答/导读/术语）。 -->
      <button
        class="assist-close"
        type="button"
        title="收起助手（Esc）"
        aria-label="收起助手"
        @click="closeAssistDrawer"
      >
        <Icon name="x" class="sm" />
      </button>

      <div class="tabs">
        <button
          v-for="tab in assistTabs"
          :key="tab.key"
          :class="{ on: assistTab === tab.key }"
          @click="switchTab(tab.key)"
        >
          {{ tab.label }}
        </button>
      </div>

      <div :class="assistBodyClass" :ref="setAssistBody">
        <div v-if="honestNote" class="honest">{{ honestNote }}</div>

        <!-- ============ 问答（与 agent 统一：它自己会查库） ============ -->
        <div class="tabpane" :class="{ on: assistTab === 'ask' }">
          <AgentChat :scope="agentScope" />
        </div>

        <!-- ============ 导读 ============ -->
        <div class="tabpane" :class="{ on: assistTab === 'guide' }">
          <div v-if="understandingLoading" class="chips-hint">{{ guideEmptyText }}</div>
          <div v-else-if="understandingStatus === 'failed'" class="fail-card">
            {{ understandingError || '导读生成失败' }}
            <button class="btn primary sm" style="margin-top: 8px" @click="retryUnderstanding">重试</button>
          </div>
          <div v-else-if="!guidePoints.length" class="chips-hint">{{ guideEmptyText }}</div>
          <template v-else>
            <!-- ⭐ 合规 #147：整块导读都是模型生成的。要点卡片一行一条，标在面板头一次就够——
                 标注要看得见，也不该把界面糊满芯片（`.k` 那行是用户读的要点名，不动它）。 -->
            <div class="ai-badge-row"><AiBadge kind="guide" /></div>
            <div v-for="point in guidePoints" :key="point.key" class="guide-card">
              <div class="k">{{ point.label }}</div>
              <div class="v">{{ point.text }}</div>
              <div class="ops">
                <template v-if="point.sources.length">
                  <template v-for="src in point.sources" :key="src.id">
                    <button
                      :title="'原文块 ' + src.ids.join(' + ')"
                      @click="traceTo(src.id, { text: src.text })"
                    >
                      看原文（{{ src.label || '位置待定' }}）▸
                    </button>
                    <!-- ⭐ 入口③：导读要点的出处后面「存为素材」（同一条 store 路径） -->
                    <MaterialSaveButton
                      v-if="src.found"
                      variant="guide"
                      label="存素材"
                      :task-id="currentTask && currentTask.id"
                      :block-id="src.id"
                    />
                  </template>
                </template>
                <!-- 没有单一段落出处 → 降级态置灰、不可点、不给箭头 -->
                <button v-else class="dead" disabled>无单一段落出处</button>
                <button @click="probePoint(point)">就这条追问</button>
              </div>
              <!-- 存素材失败要说人话 -->
              <div v-if="saveState.status === 'error'" class="mat-saveerr">
                {{ saveState.message }}
              </div>
              <div v-if="!point.sources.length" class="dead-note">
                该要点由全文综合而成，没有哪一段能单独代表它——所以这里不给「看原文」。
              </div>
            </div>
          </template>
        </div>

        <!-- ============ 术语 ============ -->
        <div class="tabpane" :class="{ on: assistTab === 'terms' }">
          <div v-if="understandingLoading" class="chips-hint">{{ termsEmptyText }}</div>
          <div v-else-if="understandingStatus === 'failed'" class="fail-card">
            {{ understandingError || '术语表生成失败' }}
            <button class="btn primary sm" style="margin-top: 8px" @click="retryUnderstanding">重试</button>
          </div>
          <div v-else-if="!termItems.length" class="chips-hint">{{ termsEmptyText }}</div>
          <template v-else>
            <!-- ⭐ 合规 #147：整张术语表都是模型生成的。一行一条、每行都挂一颗太吵，
                 所以在表头标一次——标注要看得见，也不该把界面糊满芯片。 -->
            <div class="ai-badge-row"><AiBadge kind="terms" /></div>
            <div class="termlist">
              <div v-for="item in termItems" :key="item.key" class="term">
                <b>{{ item.term }}</b><span class="cn">{{ item.cn }}</span>
                <div class="def">{{ item.definition }}</div>
                <div class="ops">
                  <button @click="locateTerm(item)">{{ item.locate }}</button>
                </div>
              </div>
            </div>
            <div class="chips-hint">
              术语表当前没有出处字段：按钮只在「命中之后」才回填坐标，未命中会直说「没找到」——不预填假坐标。
            </div>
          </template>
        </div>
      </div>

      <!-- 问答输入框吸底 -->
    </div>
  </div>
</template>

<script setup>
/**
 * L2 阅读工作区：桌面工具条 / 细进度条 / 提示行 / 左栏（段落精读 · pdf.js）/ 右助手三副页签。
 *
 * **纯搬迁**：模板整段来自 `App.vue` 的「L2 阅读工作区」段，一个类名、一句文案都没改。
 * 状态在 `stores/useReader`（+ `stores/useUi` 的界面零碎事、`stores/useAsk` 的问答线程、
 * `stores/useLibrary` 的任务动作与弹层）。跨视图共享的东西都不在这个组件里。
 *
 * ⚠️ 唯一一个 prop 是 `peekSummary`（手机抽屉收起时那行摘要）：它要读 `useAsk` 的
 * `lastQuestion`，而"摘要留在外壳"是上一轮定下的（放进 `useUi` 会绕成环），
 * 所以由 `App.vue` 算好、当 prop 传进来。
 */
import AgentChat from '../components/AgentChat.vue'
import AiBadge from '../components/AiBadge.vue'
import Icon from '../components/Icon.vue'
import MaterialSaveButton from '../components/MaterialSaveButton.vue'
import PdfPane from '../components/PdfPane.vue'
import {
  askParagraph,
  askPreset,
  probePoint,
} from '../stores/useAsk'
import { canRetryCurrent, openDeletePanel, openPanel, retryCurrent } from '../stores/useLibrary'
// Agent 对话（会自己调工具查库）：状态在 stores/useAgent，页面只传 scope
import {
  agentBusy,
  agentConfigOpen,
  agentError,
  agentMessages,
  loadConfig as loadAgentConfig,
  resetAgentThread,
  sendAgentStream,
} from '../stores/useAgent'
// 埋点 1（译文改动）：入口只在"有译文"的块上给，存下之后打「已人工修改」标记
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

// 问答页签的两种模式：`agent` = 会调工具的助手（默认），`direct` = 只读这一篇的老问答
const agentScope = computed(() => ({ task_id: currentTask.value && currentTask.value.id }))
// ============================================================ 正文 / 助手 可拖拽
// 宽度存 localStorage：用户调过一次，下次进阅读页还是那个比例（换文献也该保持）。
const ASSIST_W_KEY = 'docwise_assist_w'
const SPLITTER_MIN = 300
const SPLITTER_MAX = 760
const splitterDragging = ref(false)
const assistWidth = ref(readAssistWidth())

function readAssistWidth() {
  const saved = Number(localStorage.getItem(ASSIST_W_KEY) || 0)
  return saved >= SPLITTER_MIN && saved <= SPLITTER_MAX ? saved : 340
}

const readerBodyStyle = computed(() => ({
  // 用 CSS 变量传给 `.assist`，避免直接写死 flex-basis
  '--assist-w': `${assistWidth.value}px`,
}))

function clampAssistWidth(px) {
  // 上限还要跟视口走：窄屏上不允许把正文挤到 320 以下
  const viewportMax = Math.max(SPLITTER_MIN, window.innerWidth - 640)
  return Math.min(Math.max(px, SPLITTER_MIN), Math.min(SPLITTER_MAX, viewportMax))
}

function startSplitterDrag(event) {
  if (!event || event.button !== 0) return
  splitterDragging.value = true
  const startX = event.clientX
  const startW = assistWidth.value
  const onMove = (moveEvent) => {
    // 往左拖 = 助手变宽（分隔条在右边）
    assistWidth.value = clampAssistWidth(startW + (startX - moveEvent.clientX))
  }
  const onUp = () => {
    splitterDragging.value = false
    localStorage.setItem(ASSIST_W_KEY, String(assistWidth.value))
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
  // 拖拽时别选到正文文字、也别显示 I 形光标
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

function resetSplitter() {
  assistWidth.value = 340
  localStorage.setItem(ASSIST_W_KEY, '340')
}


// 埋点 2（块曝光 N34）：形态 §5 假设 1 的**分母**（修改率 = 被改块数 / 被曝光块数）
import { createExposureReporter } from '../exposure'
import {
  blockHasTranslated,
  editedBlockIds,
  saveBlockEdit,
} from '../stores/useReader'
// 素材卡的写入路径（M2）：三处入口共用它；`saveState` 用来就地反馈失败原因
import { saveState } from '../stores/useMaterials'
import {
  askSelectedSentence,
  assistTabs,
  backToLibrary,
  currentPage,
  currentTask,
  docEmptyText,
  docMetaLine,
  docMode,
  docModeLabel,
  docModeOptions,
  docPageCount,
  docPages,
  docPaneEl,
  docTitle,
  downloadOptions,
  fileAvailability,
  flashId,
  goOutline,
  guideEmptyText,
  guidePoints,
  hasBlockTranslations,
  honestNote,
  isNativeTask,
  locateKey,
  locateTerm,
  locateText,
  mobileLangLabel,
  mobileOriginalTitle,
  noBlockTranslationNotice,
  noteLineText,
  onBlockClick,
  onDocMouseUp,
  onPaneScroll,
  onPdfAsk,
  onPdfLocate,
  tocItems,
  outlineOpen,
  pageChipText,
  paragraphRows,
  pdfFallbackPage,
  pdfQuickLabel,
  pdfStartPage,
  pickedBlockId,
  pdocRows,
  retryUnderstanding,
  runDownload,
  runSearch,
  scannedNotice,
  searchOpen,
  searchTerm,
  selChip,
  setBlockEl,
  setDocMode,
  setPageEl,
  showOutline,
  stageText,
  switchTab,
  termItems,
  termsEmptyText,
  thinBar,
  toggleMobileOriginal,
  toggleSearch,
  traceTo,
  understandingError,
  understandingLoading,
  understandingStatus,
} from '../stores/useReader'
import { statusTextMap, tierTextMap } from '../stores/useTasks'
import {
  assistBodyClass,
  assistClass,
  assistDrawerOpen,
  assistTab,
  closeAssistDrawer,
  cycleSheet,
  isNarrow,
  locatedHint,
  openMenu,
  pgChipFor,
  pdocStyle,
  setAssistBody,
  sheetGripText,
  sheetState,
  stepFont,
  toggleAssistDrawer,
  toggleMenu,
  togglePgChip,
} from '../stores/useUi'

defineProps({ peekSummary: { type: String, default: '' } })

// ============================================================ 埋点 1：改译文

/** 正在改哪一块（`block_id`；空串＝没在改）。同一时刻只开一个编辑框。 */
const editFor = ref('')
/** 编辑框里的草稿（**只有用户敲的东西**，没敲过就是当前译文）。 */
const editDraft = ref('')
/** 存档失败时给用户看的那一句（成功就清空）。 */
const editError = ref('')
const savingEdit = ref(false)

function startEdit(row) {
  editFor.value = row.block.block_id
  editDraft.value = (row.block.translated || '').trim()
  editError.value = ''
}

function cancelEdit() {
  editFor.value = ''
  editDraft.value = ''
  editError.value = ''
}

/**
 * 存下这一改。⚠️ **只有服务端真存下了才动界面**（`saveBlockEdit` 不做乐观更新）——
 * 失败就如实报错、界面仍是旧译文，不假装成功。
 */
async function saveEdit(row) {
  const after = editDraft.value.trim()
  if (!after) {
    editError.value = '译文不能清空；要撤销请重新编辑'
    return
  }
  savingEdit.value = true
  editError.value = ''
  const failure = await saveBlockEdit(row.block.block_id, after)
  savingEdit.value = false
  if (failure) {
    editError.value = failure
    return
  }
  cancelEdit()
}

// ============================================================ 埋点 2：块曝光（N34）
/**
 * ⭐ 形态 §5 假设 1（"用户真的会去改译文"）判据的**分母**就靠这一路：
 * **修改率 ＝ 被改块数 / 被曝光块数**，且 `≥14 天 且 曝光块数 ≥500` 之前一律"继续观测"。
 *
 * ⚠️ 在这之前**前端一处都没上报过**（`block_exposures` 一直是空表）——
 * 也就是说那个分母**永远是 0**，判据永远算不出来。这一小段就是把它接上。
 *
 * 三条纪律（都是"别把后端打爆 / 别拖慢阅读"）：
 * - **一次会话一个 `session_id`**；同一块**只报一次进入**（用户滚来滚去不刷请求）；
 * - 块**离开视口**时再报一次，只推 `left_at`（这是"看了多久"的来源）；
 * - 上报失败一律吞掉——它是旁支数据，挂了不该让用户读不成文献。
 *
 * ⚠️ 观察 `[data-block-id]` 而**不是**挑某一条渲染路径：窄屏时桌面那条仍在 DOM 里、
 * 反之亦然，按选择器猜当前是哪条路径迟早猜错（两条都挂了这个属性）。
 */
const exposure = ref(null)
let exposureObserver = null

function attachExposure() {
  if (typeof window === 'undefined' || typeof IntersectionObserver === 'undefined') return
  const pane = docPaneEl.value
  if (!pane || !currentTask.value) return
  const taskId = currentTask.value.id
  if (!exposure.value || exposure.value.taskId !== taskId) {
    exposure.value?.dispose()
    exposure.value = createExposureReporter({ taskId })
  }
  const reporter = exposure.value
  // 进来先扫一遍：首屏可见的块不一定会触发 observer 的初始回调
  reporter.scan(pane)
  exposureObserver?.disconnect()
  exposureObserver = new IntersectionObserver(
    (entries) => {
      const entered = []
      const left = []
      for (const entry of entries) {
        const id = entry.target.getAttribute('data-block-id')
        if (!id) continue
        if (entry.isIntersecting) entered.push(id)
        else left.push(id)
      }
      if (entered.length) reporter.enter(entered)
      if (left.length) reporter.leave(left)
    },
    // 阈值给 0：进/出视口各一次即可，不需要"露出多少比例"这种细粒度
    { threshold: 0 },
  )
  for (const el of pane.querySelectorAll('[data-block-id]')) exposureObserver.observe(el)
}

/** 页面隐藏 / 关页：普通 fetch 会被取消，用 Beacon 把最后一批送出去。 */
function flushExposureByBeacon() {
  if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
    exposure.value?.beacon()
  }
}

/**
 * `Esc` 关助手抽屉（1024–1099 档）。
 *
 * 为什么要有：抽屉是 `position: fixed` 盖在正文上，没有遮罩，**键盘用户如果没有 Esc
 * 就只能靠鼠标回去点那个按钮**（与收口检查抽屉的 `Esc 可关` 同一口径）。
 * 其余宽度下抽屉根本不存在，这个监听相当于空转（`closeAssistDrawer()` 幂等）。
 */
function onKeydown(event) {
  if (event.key === 'Escape' && assistDrawerOpen.value) {
    closeAssistDrawer()
  }
}

onMounted(async () => {
  await nextTick()
  // ⭐ 挂载就把模型配置读一次：默认模式靠它判断（有 key/服务端默认 → 直接进助手），
  // 否则要等用户点到「助手」才加载，默认值永远判断不出来。
  loadAgentConfig()
  attachExposure()
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', flushExposureByBeacon)
    window.addEventListener('pagehide', flushExposureByBeacon)
  }
  if (typeof window !== 'undefined') {
    window.addEventListener('keydown', onKeydown)
  }
})

// 换页 / 换文献后 DOM 会重建，重新挂一次（`docPages` 变一次就重挂一次）
watch(docPages, async () => {
  await nextTick()
  attachExposure()
})

onUnmounted(() => {
  exposureObserver?.disconnect()
  exposureObserver = null
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', flushExposureByBeacon)
    window.removeEventListener('pagehide', flushExposureByBeacon)
  }
  if (typeof window !== 'undefined') {
    window.removeEventListener('keydown', onKeydown)
  }
  // 卸载前最后报一次（把 left_at 推到"我看到这里为止"）
  exposure.value?.beacon()
  exposure.value?.dispose()
  exposure.value = null
})
</script>
