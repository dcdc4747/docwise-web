/**
 * 测试环境兜底：happy-dom 里没有的浏览器 API，补上最小实现。
 * 只补 naive-ui 组件在渲染时会用到的那几个，不做完整 polyfill。
 */

// naive-ui 的 tabs / upload 等组件会用 ResizeObserver
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}

// 个别组件会问"是不是深色模式"
if (!globalThis.matchMedia) {
  globalThis.matchMedia = () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  })
}

// App.vue 进度推送用 EventSource（测试里不会真的连，占位防 ReferenceError）
if (!globalThis.EventSource) {
  globalThis.EventSource = class {
    constructor() {
      this.readyState = 0
    }
    close() {}
  }
}
