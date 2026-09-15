/**
 * pdf.js 的加载层（单独一个模块的两个理由）：
 * ① worker 的 URL 只有打包器认识（`?url`），藏在组件里会把测试也一起拖进打包器；
 * ② 单测里把这个模块换掉，就不用真的去渲染 canvas 了。
 */

/** pdf.js 需要"标准字体数据"才能正确画非嵌入字体；这些文件由 vite.config.js 从
 *  node_modules/pdfjs-dist/standard_fonts 发到 <base>/pdfjs/standard_fonts/（不进 git）。 */
const STANDARD_FONTS_URL = `${import.meta.env?.BASE_URL || '/'}pdfjs/standard_fonts/`

let pdfjsPromise = null

/** 惰性加载 pdf.js 并配好 worker（worker 只加载一次，多篇文档共用）。 */
export function loadPdfjs() {
  if (!pdfjsPromise) {
    pdfjsPromise = (async () => {
      const pdfjs = await import('pdfjs-dist')
      const worker = await import('pdfjs-dist/build/pdf.worker.min.mjs?url')
      pdfjs.GlobalWorkerOptions.workerSrc = worker.default
      return pdfjs
    })()
  }
  return pdfjsPromise
}

/** 视口变换：把 `[a,b,c,d,e,f]` 这样的文本矩阵换算成视口坐标（左上角原点）。 */
export function itemBox(pdfjs, viewport, item) {
  const m = pdfjs.Util.transform(viewport.transform, item.transform)
  const height = Math.hypot(m[2], m[3]) || Math.abs(item.height) || 10
  const width = (item.width || 0) * (viewport.scale || 1)
  return { text: item.str || '', x: m[4], y: m[5], w: width, h: height }
}

/**
 * 打开一篇 PDF，返回 `{ doc, pdfjs }`（pdfjs 给调用方换算文字层坐标用）。
 *
 * **刻意不走 `?ticket=` 的 URL**：票据 60 秒有效，而 pdf.js 会按需分片拉取，
 * 读一篇要几分钟 → 中途过期就是"读一半白屏"。
 * 这里用 `getBytes()` 一次性把字节取回来（走带 Bearer 头的 authFetch），
 * 顺带也不用管 `/files` 要不要支持 Range。
 */
export async function openPdfDocument({ getBytes }) {
  const pdfjs = await loadPdfjs()
  const data = await getBytes()
  const doc = await pdfjs.getDocument({
    data,
    standardFontDataUrl: STANDARD_FONTS_URL,
    isEvalSupported: false,
  }).promise
  return { doc, pdfjs }
}
