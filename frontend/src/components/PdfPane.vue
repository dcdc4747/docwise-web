<script setup>
/**
 * 左栏的 PDF 视图（原版 / 纯中文 / 双语三种产物共用一套）。
 *
 * 为什么不用 iframe：iframe 里是**浏览器自带的阅读器**（PDFium），
 * 拿不到 DOM、拿不到文字位置、也不知道当前在第几页——"点出处跳过去看那一段"和
 * "点 PDF 里的段落提问"这两件事**物理上做不到**。pdf.js 有文字层坐标，所以能。
 *
 * 它负责三件事：
 * ① 渲染：每页一张 canvas（按需渲染，滚到附近才画），宽度自适应容器；
 * ② 命中：整篇的文字层建成索引（`pdfText.js` 的纯函数），按文本找块 → 滚过去 + 画高亮框；
 * ③ 提问：点页面上任意一行 → 浮出「就这段提问」，把那一行（带上下文）交给外层。
 *
 * **对不上就如实说**（硬约束④）：找不到那段文字时只翻到页、不画任何高亮，
 * 由外层把 `.honest` 的话写出来——宁可不给，也不假高亮。
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import {
  buildLines,
  buildPageIndex,
  findTextInPages,
} from '../pdfText'
import { itemBox, openPdfDocument } from '../pdfLoader'
import { authFetch } from '../auth'

const props = defineProps({
  taskId: { type: Number, required: true },
  /** 'mono' = 纯中文稿 / 原稿（中文文献），'dual' = 双语稿。 */
  variant: { type: String, required: true },
  /** 要定位的原文文本（块里的 text）；空串表示不定位。 */
  locateText: { type: String, default: '' },
  /** 每次请求定位都 +1：同一个块再点一次也要重新定位一次。 */
  locateKey: { type: Number, default: 0 },
  /** 文本对不上时至少翻到第几页（1 起；0 = 不知道）。 */
  fallbackPage: { type: Number, default: 0 },
  /** 打开时落在第几页（1 起；0/1 = 从头）——从段落精读切过来时"接着读"。 */
  startPage: { type: Number, default: 0 },
  /** 这份文献原文一共几页（块里推出来的）。用来判断双语稿是不是"原页+译页"交替。 */
  docPageCount: { type: Number, default: 0 },
  /** 这篇有没有双语稿——纯中文稿定位要靠它当"几何参照"（见 locateViaReference）。 */
  hasDual: { type: Boolean, default: false },
})

const emit = defineEmits(['ask', 'page-change', 'locate'])

const loading = ref(true)
const error = ref('')
const pageCount = ref(0)
const pages = ref([]) // [{ n, baseWidth, baseHeight, rendered }]
const indexes = ref([]) // 每页的文字层索引（坐标是缩放 1 的视口坐标）
const scale = ref(1)
const paneEl = ref(null)
const hl = ref(null) // { page, rects(缩放 1 的坐标) }
const picked = ref(null) // { page, line, rect }

let pdfDoc = null
let pdfjsRef = null
let observer = null
let resizeObserver = null
let resizeTimer = null
let loadToken = 0
/** 纯中文稿定位失败时，用双语稿当"几何参照"（惰性打开，拿到就复用）。 */
let reference = null
let referenceLoading = null
/**
 * 渲染串行化：同一个 canvas 上并发跑两次 page.render() 会直接抛
 * 「Cannot use the same canvas during multiple render() operations」
 * （第一版就是这么崩的，截图里白底红字）。所以：
 * ① 所有渲染排进一条链，一次只画一张；② 每页自己有 rendering 标记，重复请求直接忽略。
 */
let renderChain = Promise.resolve()

const displayScale = computed(() => scale.value)

/**
 * 对不上时该翻到第几页。
 * 双语稿常见形态是"原页 + 译页"交替（页数约等于原文两倍），此时原文第 N 页是 PDF 的第 2N-1 页；
 * 左右并排的双语稿页数不变，就按 N 算。判断依据是**实测页数**，不是猜的。
 */
const targetPage = computed(() => {
  const n = props.fallbackPage
  if (!n) return 0
  if (
    props.variant === 'dual' &&
    props.docPageCount > 0 &&
    pageCount.value >= props.docPageCount * 2 - 1
  ) {
    return n * 2 - 1
  }
  return n
})

/** 高亮框换算成当前显示尺寸（命中坐标只存一份，缩放时乘系数即可）。 */
const hlBoxes = computed(() => {
  const out = {}
  if (!hl.value) return out
  const k = displayScale.value
  out[hl.value.page] = hl.value.rects.map((r) => ({
    left: `${r.x * k}px`,
    top: `${r.y * k}px`,
    width: `${Math.max(2, r.w * k)}px`,
    height: `${Math.max(2, r.h * k)}px`,
  }))
  return out
})

const chipBox = computed(() => {
  const item = picked.value
  // 已经就这段问过了：高亮留着（让用户看得见自己问的是哪一段），浮标收起来
  if (!item || item.asked) return null
  const k = displayScale.value
  return {
    page: item.page,
    style: {
      left: `${item.rect.x * k}px`,
      top: `${Math.max(0, item.rect.y * k - 30)}px`,
    },
  }
})

/** 每页的文字**段**框：热区按段给，所以鼠标扫过去亮的是"这一段"，不是一行。 */
function pageParagraphs(n) {
  const index = indexes.value.find((item) => item.page === n)
  return index ? index.paragraphs : []
}

function boxStyle(rect) {
  const k = displayScale.value
  return {
    left: `${rect.x * k}px`,
    top: `${rect.y * k}px`,
    width: `${Math.max(4, rect.w * k)}px`,
    height: `${Math.max(4, rect.h * k)}px`,
  }
}

/** 选中的那一段（点了就亮，点到别处才灭——不是"点完就没"）。 */
const pickedBox = computed(() => {
  const item = picked.value
  if (!item) return null
  return { page: item.page, style: boxStyle(item.rect) }
})

function pageStyle(page) {
  const k = displayScale.value
  return { width: `${page.baseWidth * k}px`, height: `${page.baseHeight * k}px` }
}

/** 缩放系数：把页面塞进容器宽度（0.5–2.5 倍之间），和常见 PDF 阅读器的"适应宽度"一致。 */
function computeScale(baseWidth) {
  const pane = paneEl.value
  const available = pane && pane.clientWidth ? pane.clientWidth - 32 : 0
  // 量不到宽度（还没挂上 / 测试环境）就按 1 倍——**别拿 0 宽去算出一个荒唐的系数**
  if (!available || !baseWidth) return 1
  return Math.min(2.5, Math.max(0.5, available / baseWidth))
}

async function renderPage(page) {
  if (!pdfDoc || page.rendering) return
  page.rendering = true
  try {
    const entry = await pdfDoc.getPage(page.n)
    const canvas = paneEl.value && paneEl.value.querySelector(`canvas[data-page="${page.n}"]`)
    if (!canvas) return
    const dpr = Math.min(2, (typeof window !== 'undefined' && window.devicePixelRatio) || 1)
    const viewport = entry.getViewport({ scale: displayScale.value * dpr })
    // happy-dom 里没有 2d 上下文：**跳过画，但别报错**（文字层与命中不依赖 canvas）
    const ctx = canvas.getContext && canvas.getContext('2d')
    if (!ctx) {
      page.rendered = true
      return
    }
    canvas.width = Math.floor(viewport.width)
    canvas.height = Math.floor(viewport.height)
    const task = entry.render({ canvasContext: ctx, viewport })
    page.task = task
    await task.promise
    page.rendered = true
    entry.cleanup()
  } catch (err) {
    // 缩放变化会主动 cancel 掉在跑的渲染——那是预期内的，不算错
    if (!err || err.name !== 'RenderingCancelledException') page.rendered = true
  } finally {
    page.task = null
    page.rendering = false
  }
}

function queueRender(page) {
  renderChain = renderChain.then(() => renderPage(page)).catch(() => {})
  return renderChain
}

/** 没有 IntersectionObserver（测试环境 / 老浏览器）时退化：全部直接排进渲染链。 */
function renderAll() {
  for (const page of pages.value) queueRender(page)
}

/** 读一整页的文字层，建成"可搜索 + 可点"的索引。 */
async function indexPage(page) {
  const entry = await pdfDoc.getPage(page.n)
  const viewport = entry.getViewport({ scale: 1 })
  const content = await entry.getTextContent()
  const boxes = []
  for (const item of content.items) {
    if (!item || !item.str) continue
    boxes.push(itemBox(pdfjsRef, viewport, item))
  }
  entry.cleanup()
  return buildPageIndex(buildLines(boxes), page.n)
}

async function load() {
  const token = ++loadToken
  loading.value = true
  error.value = ''
  hl.value = null
  picked.value = null
  pages.value = []
  indexes.value = []
  try {
    const { doc, pdfjs } = await openPdfDocument({
      getBytes: async () => {
        const res = await authFetch(`/api/tasks/${props.taskId}/files/${props.variant}`)
        if (!res.ok) throw new Error(`读不到这份 PDF（HTTP ${res.status}）`)
        return new Uint8Array(await res.arrayBuffer())
      },
    })
    if (token !== loadToken) {
      doc.destroy()
      return
    }
    pdfDoc = doc
    pdfjsRef = pdfjs
    pageCount.value = doc.numPages

    const first = await doc.getPage(1)
    const base = first.getViewport({ scale: 1 })
    const list = []
    for (let n = 1; n <= doc.numPages; n += 1) {
      const vp = n === 1 ? base : (await doc.getPage(n)).getViewport({ scale: 1 })
      list.push({ n, baseWidth: vp.width, baseHeight: vp.height, rendered: false })
    }
    pages.value = list
    scale.value = computeScale(base.width)
    loading.value = false

    // 文字层一次建完（不涉及绘图，很快；命中要用整篇）
    const built = []
    for (const page of list) built.push(await indexPage(page))
    if (token !== loadToken) return
    indexes.value = built

    await nextTick()
    observePages()
    // 从段落精读切过来：接着读（翻到刚才那一页），不从头开始
    if (props.startPage > 1) scrollToPage(props.startPage)
  } catch (err) {
    if (token !== loadToken) return
    error.value = err && err.message ? err.message : '这份 PDF 打不开'
    loading.value = false
  }
}

function observePages() {
  if (typeof IntersectionObserver === 'undefined' || !paneEl.value) {
    // 没有 IntersectionObserver（老浏览器 / 测试环境）就全部直接画
    renderAll()
    return
  }
  if (observer) observer.disconnect()
  observer = new IntersectionObserver(
    (entries) => {
      for (const item of entries) {
        if (!item.isIntersecting) continue
        const n = Number(item.target.dataset.page)
        const page = pages.value.find((p) => p.n === n)
        if (page && !page.rendered) queueRender(page)
      }
    },
    { root: paneEl.value, rootMargin: '600px 0px' },
  )
  paneEl.value.querySelectorAll('.pdf-page').forEach((el) => observer.observe(el))
}

function scrollToPage(n, { center = false } = {}) {
  const pane = paneEl.value
  if (!pane) return
  const el = pane.querySelector(`.pdf-page[data-page="${n}"]`)
  if (!el) return
  const top = el.offsetTop - pane.offsetTop
  pane.scrollTo({ top: Math.max(0, top - (center ? 80 : 12)), behavior: 'smooth' })
  emit('page-change', n)
}

/**
 * 定位到某段原文：找到就滚过去 + 画高亮；找不到就走"几何参照"，再不行只翻到页并如实回报。
 */
async function locate() {
  const needle = props.locateText
  await nextTick()
  if (!needle || !indexes.value.length) {
    if (targetPage.value) scrollToPage(targetPage.value)
    return
  }
  const hit = findTextInPages(indexes.value, needle)
  if (hit) {
    await applyHighlight(hit.page, hit.rects)
    emit('locate', { found: true, page: hit.page, exact: hit.exact, translated: false })
    return
  }

  // 纯中文稿：块里是英文、这一份是中文，直接搜必然搜不到——
  // 用双语稿的"原页 → 译页"几何关系把这一段的中文找出来（见 locateViaReference）
  const viaRef = await locateViaReference(needle)
  if (viaRef) {
    await applyHighlight(viaRef.page, viaRef.rects)
    emit('locate', { found: true, page: viaRef.page, exact: false, translated: true })
    return
  }

  hl.value = null
  if (targetPage.value) scrollToPage(targetPage.value)
  emit('locate', { found: false, page: targetPage.value || 0 })
}

async function applyHighlight(page, rects) {
  hl.value = { page, rects }
  picked.value = null
  await nextTick()
  scrollToPage(page, { center: true })
  const pane = paneEl.value
  const el = pane && pane.querySelector(`.pdf-page[data-page="${page}"]`)
  if (pane && el && rects.length) {
    const k = displayScale.value
    const top = el.offsetTop - pane.offsetTop + rects[0].y * k - 120
    pane.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
  }
}

/**
 * **纯中文稿的段落定位**（不靠引擎返工）。
 *
 * 双语稿是"原页 + 译页"交替的**版式保持**产物，所以：
 *   ① 在双语稿里搜到这段**英文原文** → 它在原页 P 上的 y 区间；
 *   ② 双语稿的译页 Q 上、与这段 y 区间**上下重叠**的那几行，就是它的中文译文；
 *   ③ 纯中文稿（只由译页组成）第 Q/2 页、同样 y 区间的那几行，是同一段。
 * 实测（4 份真产物）②③ 两处取到的中文行**完全一致**，所以这条路站得住。
 *
 * 只读双语稿、只取几何，**不改后端、不改引擎**；拿不准时宁可不给（返回 null）。
 */
async function locateViaReference(needle) {
  if (props.variant !== 'mono' || !props.hasDual) return null
  const reference = await ensureReference()
  if (!reference || !reference.indexes.length) return null
  const hit = findTextInPages(reference.indexes, needle)
  if (!hit) return null

  const refPage = reference.indexes.find((item) => item.page === hit.page)
  if (!refPage || !hit.paragraphs.length) return null
  const y0 = Math.min(...hit.paragraphs.map((p) => p.rect.y))
  const y1 = Math.max(...hit.paragraphs.map((p) => p.rect.y + p.rect.h))

  // 交替双语稿：奇数页原页、偶数页译页；左右并排的双语稿则同页（页数不会翻倍）
  const interleaved =
    reference.pageCount >= 2 * (props.docPageCount || reference.pageCount / 2) - 1 &&
    reference.pageCount > props.docPageCount
  const refTransPage = interleaved ? (hit.page % 2 === 1 ? hit.page + 1 : hit.page) : hit.page
  const monoPage = interleaved ? Math.ceil(refTransPage / 2) : hit.page
  if (!monoPage || monoPage > pageCount.value) return null

  const monoIndex = indexes.value.find((item) => item.page === monoPage)
  if (!monoIndex) return null
  // 在纯中文稿的同一 y 区间上取中文段（**用本页自己的几何**，不照抄参照页的坐标）
  const scope = monoIndex.paragraphs.filter((p) => p.rect.y < y1 && p.rect.y + p.rect.h > y0)
  if (!scope.length) return null
  // 兜底校验：这段真得有字（别把空白区当成命中）
  if (!scope.some((p) => p.text && p.text.trim())) return null
  return { page: monoPage, rects: scope.map((p) => p.rect) }
}

/** 惰性打开双语稿当参照（只在纯中文稿定位失败时用一次，之后复用）。 */
async function ensureReference() {
  if (reference) return reference
  if (referenceLoading) return referenceLoading
  referenceLoading = (async () => {
    try {
      const { doc } = await openPdfDocument({
        getBytes: async () => {
          const res = await authFetch(`/api/tasks/${props.taskId}/files/dual`)
          if (!res.ok) throw new Error('读不到双语稿')
          return new Uint8Array(await res.arrayBuffer())
        },
      })
      const pageCountOfRef = doc.numPages
      const indexes = []
      for (let n = 1; n <= pageCountOfRef; n += 1) {
        const entry = await doc.getPage(n)
        const viewport = entry.getViewport({ scale: 1 })
        const content = await entry.getTextContent()
        const boxes = []
        for (const item of content.items) {
          if (!item || !item.str) continue
          boxes.push(itemBox(pdfjsRef, viewport, item))
        }
        entry.cleanup()
        indexes.push(buildPageIndex(buildLines(boxes), n))
      }
      reference = { doc, indexes, pageCount: pageCountOfRef }
      return reference
    } catch {
      reference = null
      return null
    } finally {
      referenceLoading = null
    }
  })()
  return referenceLoading
}

/**
 * 点页面：命中的那**一段**当场点亮（选中态一直留着，点到别处才灭），
 * 并在它上方浮出「就这段提问」——点哪儿哪儿有反应，不是点完什么都没发生。
 */
function onPaneClick(event) {
  const target = event.target
  const holder = target && target.closest ? target.closest('.pdf-page') : null
  if (!holder) return
  const hitEl = target.closest ? target.closest('[data-para]') : null
  if (!hitEl) {
    picked.value = null
    return
  }
  const page = Number(holder.dataset.page)
  const para = Number(hitEl.dataset.para)
  const index = indexes.value.find((item) => item.page === page)
  const paragraph = index && index.paragraphs[para]
  if (!paragraph) {
    picked.value = null
    return
  }
  // 同一段再点一次 = 取消选中
  if (picked.value && picked.value.page === page && picked.value.para === para) {
    picked.value = null
    return
  }
  picked.value = { page, para, rect: paragraph.rect, text: paragraph.text, asked: false }
}

/** Esc 取消选中（和常见阅读器一致）。 */
function onKeydown(event) {
  if (event.key === 'Escape') picked.value = null
}

function askPicked() {
  const item = picked.value
  if (!item) return
  const index = indexes.value.find((entry) => entry.page === item.page)
  if (!index) return
  const text = item.text || index.paragraphs[item.para].text
  emit('ask', { text, context: text })
  // 高亮留着、浮标收起来：让用户看得见"我刚问的是这一段"
  picked.value = { ...item, asked: true }
}

/** 缩放变了要重画：**先取消在跑的那次渲染**（否则旧尺寸会覆盖新尺寸），再重新观察一遍。 */
watch(scale, async () => {
  if (!pdfDoc) return
  const redraw = pages.value.filter((page) => page.rendered)
  for (const page of redraw) {
    if (page.task) {
      try {
        page.task.cancel()
      } catch {
        /* 已经结束了就算了 */
      }
    }
    page.rendered = false
  }
  await nextTick()
  observePages()
})

watch(() => [props.taskId, props.variant], load, { immediate: true })
watch(() => props.locateKey, locate)

function onResize() {
  if (resizeTimer) clearTimeout(resizeTimer)
  resizeTimer = setTimeout(() => {
    if (!pages.value.length) return
    scale.value = computeScale(pages.value[0].baseWidth)
  }, 200)
}

if (typeof window !== 'undefined' && typeof ResizeObserver !== 'undefined') {
  resizeObserver = new ResizeObserver(onResize)
}

if (typeof window !== 'undefined') window.addEventListener('keydown', onKeydown)

onBeforeUnmount(() => {
  loadToken += 1
  if (typeof window !== 'undefined') window.removeEventListener('keydown', onKeydown)
  if (observer) observer.disconnect()
  if (resizeObserver) resizeObserver.disconnect()
  if (resizeTimer) clearTimeout(resizeTimer)
  if (pdfDoc) pdfDoc.destroy()
})

defineExpose({ locate, scrollToPage })

watch(paneEl, (el) => {
  if (resizeObserver && el) resizeObserver.observe(el)
})
</script>

<template>
  <div ref="paneEl" class="pdf-pane" @click="onPaneClick">
    <div v-if="loading" class="card doc-note">正在打开这份 PDF…</div>
    <div v-else-if="error" class="card doc-note">{{ error }}</div>
    <template v-else>
      <div
        v-for="page in pages"
        :key="page.n"
        class="pdf-page"
        :data-page="page.n"
        :style="pageStyle(page)"
      >
        <canvas :data-page="page.n" />
        <!-- 文字段热区：透明、可 hover、可点（点哪儿哪儿亮，亮的是**一整段**） -->
        <span
          v-for="(para, i) in pageParagraphs(page.n)"
          :key="'hit-' + i"
          class="pdf-hit"
          :data-para="i"
          :style="boxStyle(para.rect)"
        />
        <span
          v-for="(box, i) in hlBoxes[page.n] || []"
          :key="'hl-' + i"
          class="pdf-hl"
          :style="box"
        />
        <span
          v-if="pickedBox && pickedBox.page === page.n"
          class="pdf-sel"
          :style="pickedBox.style"
        />
        <button
          v-if="chipBox && chipBox.page === page.n"
          class="pdf-chip"
          :style="chipBox.style"
          @click.stop="askPicked"
        >
          就这段提问
        </button>
      </div>
    </template>
  </div>
</template>
