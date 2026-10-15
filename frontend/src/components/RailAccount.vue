<script setup>
/**
 * 左栏底部账号区（R7 / 形态 v2 §1.2 布局图第 60 行）。
 *
 * 形态原文：`│ 小研 ›   │  ← 账号区（点进个人中心，进入后高亮）`，
 * M0 判据也写着「**账号区点进个人中心且进入后高亮**」——所以这个组件只做三件事：
 * ① 露出现在是谁；② 点它进 `#/me`；③ 到了 `#/me` 要**亮**（走左栏同一套选中态，不另搞一套）。
 *
 * ⚠️ 与 `AppRail.vue` 同一套规矩：**它也是哑的** —— 不 import store、不读 `location.hash`。
 * 名字与选中态由外壳经 props 交进来，点哪里由外壳处理（`@select`）。理由同 `AppRail.vue`
 * 顶部注释（契约 §0.5：`location.hash` 只在 `router.js` 里读写）。
 *
 * ⚠️ **类名故意不叫 `.rail-item`**：`app.smoke.test.js` 有一条用例断言
 * 「`button.rail-item` **恰好 12 个**」（左栏 12 项）——账号区借用那个类名会把它数成 13。
 * 形状与交互在 `style.css` 的 `[R7]` 段里**照 `.rail-item` 逐条对齐**（同一套 hover / 选中态 / 焦点环），
 * 只多两样它没有的：**首字头像**与右侧那个 `›`。
 *
 * 收起态（58px）：名字用既有的 `.rail-lbl`，由 `.rail-min .rail-lbl { display:none }` 自动藏；
 * 头像**不跟着藏**（那就是收起态唯一要看的东西）——**不新造一套收起逻辑**。
 */
import { computed } from 'vue'

const props = defineProps({
  /** 现在是谁（外壳的 `accountLabel`；未登录时是空串）。 */
  label: { type: String, default: '' },
  /** 到了个人中心就该亮（外壳用 `activeNav === 'me'` 算，与左栏其它项同一套）。 */
  active: { type: Boolean, default: false },
})

defineEmits(['select'])

/** 头像里的那个字：取名字首字（`tester（普通用户）` → `t`）。没有名字就不画。 */
const initial = computed(() => (props.label || '').trim().slice(0, 1))
</script>

<template>
  <!-- 原生 `<button>`：键盘可达（本仓真规矩：不许用 `div + @click` 当按钮） -->
  <button
    type="button"
    class="rail-account"
    :class="{ on: active }"
    :data-tip="label ? `个人中心 · ${label}` : '个人中心'"
    :aria-current="active ? 'page' : undefined"
    @click="$emit('select')"
  >
    <span v-if="initial" class="rail-av" aria-hidden="true">{{ initial }}</span>
    <span class="rail-lbl">{{ label }}</span>
    <span class="rail-arrow" aria-hidden="true">›</span>
  </button>
</template>
