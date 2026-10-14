<script setup>
/**
 * 左栏骨架（形态 v2 §1.2「两段式」+ §1.2b「260 ⇄ 58」）。
 *
 * **两段式的理由是这一条**：「做什么」（动词）和「有什么」（资产）是两种不同的东西，
 * 不能用同一套导航表达 —— 上段是三个模块入口，下段是知识库入口。
 * （形态 v2 §1.2 原话；AFFiNE 只有动作、Zotero 只有资产，我们两个都要。）
 *
 * ⚠️ **这个组件是"哑"的**：不 import 任何 store、不读 `location.hash`、不认识数据。
 * - 收起态与当前选中项由外壳经 props 交进来（`railMin` / `activeNav`）；
 * - 点哪里由外壳处理（`@select` / `@toggle`）。
 * 这么切的两个理由：① 契约 §0.5 把 `App.vue` 与 `router.js` 定为共享接口面，
 * **地址只在 `router.js` 里被读写**，组件自己碰 `location.hash` 就是结构退化；
 * ② 页面里的导航项与路由的对应关系会随 M1–M3 变，那属于外壳的知识，不属于左栏的形状。
 *
 * ⚠️ **计数徽章本期一律不显示**（R4 卡接口契约：计数先写死/写空，真数据在 M1 的 N8/D4）。
 * **不写假数字**——所以这里连 `0` 都不印，等真数据来了再补。
 *
 * ⚠️ **tooltip 用 CSS 实现，不用原生 `title`**（R1 明确要求：`title` 延迟不可控，
 * 演示视频里来不及出现）。名字走 `data-tip` 属性，样式在 `style.css` 的 `[M0]` 段，
 * 且 `:hover` 与 `:focus-visible` 两条都要能触发（§7.6 第 5 条：键盘用户也要看得到）。
 */

import Icon from './Icon.vue'

defineProps({
  /** 收起态（58px 图标态）。由外壳交给 `useUi` 的 `railMin` 决定。 */
  railMin: { type: Boolean, default: false },
  /** 当前选中的导航项 key（`read` / `write` / `check` / `library` / …）。 */
  activeNav: { type: String, default: 'read' },
})

defineEmits(['toggle', 'select'])

/**
 * 上段：三个模块入口（动词）。
 * `tip` 是收起态 tooltip 的全文 —— 展开态看得到名字，收起了才需要它说清"点了会怎样"。
 */
const ACTIONS = [
  { key: 'read', label: '读懂', tip: '读懂 · 读文献、存素材', icon: 'book' },
  { key: 'write', label: '起草', tip: '起草 · 攒稿、插引文', icon: 'pen' },
  { key: 'check', label: '收口', tip: '收口 · 检稿、出报告', icon: 'check-search' },
]

/**
 * 下段：知识库入口（名词）。
 * 按形态 v2 §1.2 的布局图逐项做（7 项）：全部文献 / 集合 / 标签 / 待读 / 素材 / 草稿 / 引用。
 * ⚠️ 「待读」是**智能集合**（已保存的搜索），不是手建的集合 —— 形态 §4.1 第 2 条。
 */
const LIBRARY_ITEMS = [
  { key: 'lib-all', label: '全部文献', tip: '全部文献', icon: 'layers' },
  { key: 'lib-collections', label: '集合', tip: '集合 · 可嵌套的组织容器', icon: 'folder' },
  { key: 'lib-tags', label: '标签', tip: '标签 · 主题 / 方法 / 状态', icon: 'tag' },
  { key: 'lib-todo', label: '待读', tip: '待读 · 智能集合（规则：状态 = 待读）', icon: 'filter' },
  { key: 'lib-materials', label: '素材', tip: '素材 · 从文献里取出的证据', icon: 'bookmark' },
  { key: 'lib-drafts', label: '草稿', tip: '草稿', icon: 'file' },
  { key: 'lib-refs', label: '引用', tip: '引用', icon: 'quote' },
]

/** 底部两条（形态 v2 §1.2 布局图里在分隔线下面、账号区上面）。 */
const FOOT_ITEMS = [
  { key: 'memory', label: '记忆', tip: '记忆 · 可看可删可下钻', icon: 'gear' },
  { key: 'process', label: '处理过程', tip: '处理过程 · 它做了什么', icon: 'listcheck' },
]
</script>

<template>
  <!-- 上段与下段包在一个滚动容器里（`.rail-foot` 用 `margin-top:auto` 沉到底） -->
  <div class="rail-main">
    <!-- 顶栏（品牌 + 收起按钮）：不是 <header>，左栏本来就是一个 <aside> -->
    <div class="rail-head">
      <div class="rail-brand">
        docwise
        <span>文献工作台</span>
      </div>
      <button
        class="rail-toggle"
        type="button"
        :aria-label="railMin ? '展开左栏（Ctrl+B）' : '收起左栏（Ctrl+B）'"
        :title="railMin ? '展开左栏（Ctrl+B）' : '收起左栏（Ctrl+B）'"
        @click="$emit('toggle')"
      >
        <Icon :name="railMin ? 'chev-double-right' : 'chev-double-left'" class="sm" />
      </button>
    </div>

    <!-- 上段：做什么（动词） -->
    <div class="rail-sec">
      <div class="rail-sec-t">做什么</div>
      <button
        v-for="item in ACTIONS"
        :key="item.key"
        type="button"
        class="rail-item"
        :class="{ on: activeNav === item.key }"
        :data-tip="item.tip"
        @click="$emit('select', item.key)"
      >
        <Icon :name="item.icon" />
        <span class="rail-lbl">{{ item.label }}</span>
      </button>
    </div>

    <!-- 下段：我的库（名词） -->
    <div class="rail-sec">
      <div class="rail-sec-t">我的库</div>
      <button
        v-for="item in LIBRARY_ITEMS"
        :key="item.key"
        type="button"
        class="rail-item"
        :class="{ on: activeNav === item.key }"
        :data-tip="item.tip"
        @click="$emit('select', item.key)"
      >
        <Icon :name="item.icon" />
        <span class="rail-lbl">{{ item.label }}</span>
      </button>
    </div>

    <div class="rail-foot">
      <div class="rail-div" />
      <button
        v-for="item in FOOT_ITEMS"
        :key="item.key"
        type="button"
        class="rail-item"
        :class="{ on: activeNav === item.key }"
        :data-tip="item.tip"
        @click="$emit('select', item.key)"
      >
        <Icon :name="item.icon" />
        <span class="rail-lbl">{{ item.label }}</span>
      </button>

      <!-- 「本地优先 · 服务自持」是**状态文字，不可点**（R7 判据⑤：与账号区视觉可分）。
           ⚠️ 口径：不能说"数据不出本机"——外文翻译 / 扫描件逐段翻译 / 导读问答三处仍调云端模型 API。 -->
      <div class="rail-sw">
        <Icon name="lock" class="sm" />
        <span class="rail-lbl">本地优先 · 服务自持</span>
      </div>

      <!-- ⭐ 账号区（R7 的 `RailAccount.vue` 就挂在这里）。
           本卡（R4）**只留位置、不建组件**——账号区要读 `GET /api/auth/me` 并处理 `#/me` 高亮，
           那是 R7 的范围；这里先把"位置在最低处、与上面两条同宽"这个形状定住，
           这样 R7 只改自己那一个文件，不碰 `App.vue`。 -->
      <slot name="account" />
    </div>
  </div>
</template>
