"""读段预算守卫：挡住重复读同一段，也挡住把上下文烧光。

实测过：读懂侧 14 个工具里 `read_blocks` / `read_section` 是
"重读"高发户；模型有时会把同一节读三遍（换了个问法就再读一次）。
后果有三条：① 挤掉真正有用的上下文；② 白花钱；
③ 工具调用数看着很多，实际没产出。

这个模块只做一件事：记住"读过哪些段、花了多少字"，
在下次读之前回答"还能不能读"。它**不查库、不依赖框架**，
是纯状态对象，方便单测与替换。

## 口径（没有隐式规则）

1. **同一个 key 第二次就不许**：重复读是本次要挡的主要问题。
   note 固定为「这一段已经读过了，用之前的内容回答；
   确实需要重读请说明原因」。
2. **预算用完也不许**：累计读满 `max_reads` 次，或累计字数
   加上这次要读的字数会超过 `max_chars`，都拒绝；note 说明
   "预算用完，先整理已有内容"。
3. `allow` **不改变状态**：先问后记。哪怕连问三次，
   `stats()` 仍是全 0（避免"问了就算读过"）。
4. `record` **幂等**：同一 key 重复 record 只增加 `repeated`，
   不重复加 `reads` / `chars`；先 `allow` 再 `record` 是
   调用方的责任，`record` 自己不拦预算。
5. `chars` 为 0 按 0 计；负数按 0 计（不抛异常）。
   一次 0 字的读仍然占一次 `max_reads` 名额。

判定顺序：先看重复（规则 1），再看预算（规则 2）。
两样都占时返回重复的 note——它更接近"这次为什么不该读"。
key 按原样比较（不去空格、不改大小写）。
"""

from __future__ import annotations

_REPEAT_NOTE = "这一段已经读过了，用之前的内容回答；确实需要重读请说明原因"
_READS_NOTE = (
    "读段预算用完（已读 {reads}/{max_reads} 次），"
    "先整理已有内容；确实需要继续读请说明原因"
)
_CHARS_NOTE = (
    "读段预算用完（这次要读 {need} 字，会超出 {chars}/{max_chars} "
    "字的上限），先整理已有内容；确实需要继续读请说明原因"
)


def _clean_chars(chars: int) -> int:
    """负数按 0 计；转不成整数的也按 0，不抛异常。"""
    try:
        value = int(chars)
    except (TypeError, ValueError):
        return 0
    return max(0, value)


class ReadBudget:
    """一次会话里的读段预算；一个会话一个实例，线程不安全。"""

    def __init__(self, max_reads: int = 6, max_chars: int = 24000) -> None:
        self.max_reads = max(0, int(max_reads))
        self.max_chars = max(0, int(max_chars))
        self._reads = 0
        self._chars = 0
        self._repeated = 0
        self._keys: list[str] = []
        self._seen: set[str] = set()

    def allow(self, key: str, chars: int = 0) -> tuple[bool, str]:
        """能不能再读一次；返回 `(allowed, note)`。

        `chars` 是这次打算读的字数，用来判断会不会撑破字符预算。
        允许时 note 是空串；拒绝时 note 是给人看的理由。
        **本方法只读状态**，调用它不会让 `stats()` 发生变化。
        """
        need = _clean_chars(chars)
        if key in self._seen:
            return False, _REPEAT_NOTE
        if self._reads >= self.max_reads:
            return False, _READS_NOTE.format(
                reads=self._reads,
                max_reads=self.max_reads,
            )
        if self._chars >= self.max_chars or (
            self._chars + need > self.max_chars
        ):
            return False, _CHARS_NOTE.format(
                need=need,
                chars=self._chars,
                max_chars=self.max_chars,
            )
        return True, ""

    def record(self, key: str, chars: int) -> None:
        """记一次已读（key 形如 `p0_b4` 或 `sec:3`）。

        同一 key 只算第一次：`reads` / `chars` 不动，
        `repeated` 加一。`chars` 为负按 0 计。
        """
        cost = _clean_chars(chars)
        if key in self._seen:
            self._repeated += 1
            return
        self._seen.add(key)
        self._keys.append(key)
        self._reads += 1
        self._chars += cost

    def stats(self) -> dict:
        """`{"reads", "chars", "repeated", "keys"}`，keys 保序去重。"""
        return {
            "reads": self._reads,
            "chars": self._chars,
            "repeated": self._repeated,
            "keys": list(self._keys),
        }
