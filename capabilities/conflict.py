"""S10-B 同栏目事实冲突前置：同一栏目对同一槽位给出不同取值时，**显式标注**而不是假装一致。

真机证据（同一份报告）：
    - Notion was founded in 2013. [6]      # PitchBook
    - Notion was founded in 2014. [4]      # CB Insights
两句都进了 Company 栏目。S8.4 的 judge 按 prompt 里「同一事实给冲突取值 → refuted」的
规则判它不可靠 —— 判定没错，错在合成层把两个来源的说法原样并列，读者无从判断。

**为什么不按置信度选一条**：这次真机里 CB Insights 的 score 是 0.77，PitchBook 是 0.72，
按分数保留会留下**错的**那个（Notion 实际成立于 2013 年）。用置信度替读者做决定，
在来源本身就错的情况下比并列更糟。所以这里只做「检出 + 标注」，**不改写、不删除任何事实**，
判断权留给读者与人工复核。

**槽位选择**：只做三个能可靠判定的槽位，并且只有第一个会给出明确取舍建议：
1. `founded_year` 成立年份 —— 不随时间变，同年份两个值必有一个错；
2. `headquarters` 总部 —— 用城市/国家 token 集合是否相交判定，容忍「London」与
   「London, England」这类写法差异；
3. `employee_count` 员工数 —— **只标不判**：同一公司不同年份员工数本就不同，
   这是时变事实而非冲突，所以差异要超过 10% 才算「同一时点的两个说法」。

**边界**：只在 `features.structured_output=on` 的结构化路径上运行 —— 模板基线路径
直接贴原文、没有 Fact 粒度，不做分析。跨栏目冲突（Company 说 2013、News 说 2014）
本模块不管，按栏目独立检测。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

# 槽位 -> (中文名, 抽取正则列表)
# 每个槽位允许多个模式（中/英）：claim 按 prompts 要求是简体中文，但上游 fixture
# 与历史数据是英文，两种都要认。取第一个命中的模式。
_SLOT_PATTERNS: dict[str, tuple[str, tuple[re.Pattern[str], ...]]] = {
    "founded_year": (
        "成立年份",
        (
            re.compile(
                r"\b(?:founded|established|incorporated|formed)\b[^.;\n]{0,24}?"
                r"\b((?:1[89]|20)\d{2})\b",
                re.IGNORECASE,
            ),
            # 中文：「成立于 2013 年」「2013 年成立」
            re.compile(
                r"(?:成立|创立|创建|创办|设立)(?:于|在)?\s*((?:1[89]|20)\d{2})\s*年?"
            ),
            re.compile(
                r"((?:1[89]|20)\d{2})\s*年[^。；;\n]{0,6}?(?:成立|创立|创建|创办|设立)"
            ),
        ),
    ),
    "headquarters": (
        "总部位置",
        (
            re.compile(
                r"\bheadquarter(?:ed|s)?\b[^.;\n]{0,40}?\b(?:in|at)\s+([^.;\n]{3,90})",
                re.IGNORECASE,
            ),
            # 中文：「总部位于北京」「总部设在上海」
            re.compile(
                r"(?:总部|总部位|总部设)(?:于|在|位于|设于)?\s*([\u4e00-\u9fa5A-Za-z][^。；;\n]{1,29})"
            ),
        ),
    ),
    "employee_count": (
        "员工人数",
        (
            re.compile(
                r"\b(\d[\d,]{1,9})\s+(?:employees|people|staff|workers)\b",
                re.IGNORECASE,
            ),
            # 中文：「1200 名员工」「员工 1200 人」——不用裸「人」避免误匹配
            re.compile(r"(\d[\d,]{1,9})\s*(?:名|位)?\s*(?:员工|雇员)"),
            re.compile(r"(?:员工|雇员)\s*(?:约|近)?\s*(\d[\d,]{1,9})\s*(?:名|人)?"),
        ),
    ),
}

# 总部判定用的停用词：地址里的通用成分不参与「是否同一个地方」的比较
_HQ_STOPWORDS = frozenset({
    "the", "and", "of", "in", "at", "is", "was", "located", "headquarters",
    "headquartered", "street", "st", "road", "rd", "avenue", "ave", "suite",
    "floor", "building", "box", "city", "office", "offices", "based",
    # 中文停用成分
    "总部", "位于", "设于", "设在", "公司", "集团", "中国", "美国",
})


def _hq_tokens(text: str) -> frozenset[str]:
    """取地名 token：英文 3+ 字母词 + 中文 2+ 字片段，去掉通用停用成分。"""
    en = re.findall(r"[a-z]{3,}", text.lower())
    zh = re.findall(r"[\u4e00-\u9fa5]{2,}", text)
    return frozenset(w for w in (*en, *zh) if w not in _HQ_STOPWORDS)


@dataclass(frozen=True)
class SlotValue:
    """某个取值，以及说过这话的所有来源。"""

    display: str
    normalised: str
    source_urls: tuple[str, ...]


@dataclass(frozen=True)
class Conflict:
    slot: str
    label: str
    values: tuple[SlotValue, ...]

    def render(self, index_by_url: Mapping[str, int]) -> str:
        """渲染成报告里的一行（markdown 引用块，不算事实 bullet）。

        `index_by_url` 的 key 可能已归一化（去掉尾斜杠），而 `source_url` 来自
        Pydantic `HttpUrl` 的 `str()`，两者形态不一定一致；统一去尾斜杠后再查。
        """
        lookup = {str(k).rstrip("/"): v for k, v in index_by_url.items()}
        parts = []
        for value in self.values:
            nums = "".join(
                f"[{n}]"
                for n in (lookup.get(u.rstrip("/")) for u in value.source_urls)
                if n
            )
            parts.append(f"{value.display} {nums}".strip())
        joined = " / ".join(parts)
        return (
            f"**来源冲突**：{self.label}出现 {len(self.values)} 个取值 —— {joined}，"
            f"来源之间不一致，未判定哪个正确"
        )


def _slot_values(claim: str) -> dict[str, tuple[str, str]]:
    """一条 claim 里能抽到的槽位 -> (归一值, 展示值)。每个槽位取第一个命中的模式。"""
    out: dict[str, tuple[str, str]] = {}
    for slot, (_, patterns) in _SLOT_PATTERNS.items():
        m = None
        for pattern in patterns:
            m = pattern.search(claim)
            if m:
                break
        if not m:
            continue
        raw = m.group(1).strip()
        if slot == "founded_year":
            out[slot] = (raw, raw)
        elif slot == "headquarters":
            tokens = _hq_tokens(raw)
            if not tokens:
                continue
            # 归一成「排序后的 token 串」，只用于相等判断，不用于展示
            out[slot] = ("|".join(sorted(tokens)), raw.rstrip(" ,"))
        else:  # employee_count
            digits = raw.replace(",", "")
            if not digits.isdigit():
                continue
            value = int(digits)
            out[slot] = (str(value), f"{value:,}")
    return out


def _group_hq(entries: Sequence[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """总部取值按 token 交集聚类：`London` 与 `London, England` 视为同一个地方。"""
    groups: list[list[tuple[str, str]]] = []
    for normalised, display in entries:
        tokens = set(normalised.split("|"))
        for group in groups:
            group_tokens = set(group[0][0].split("|"))
            if tokens & group_tokens:
                group.append((normalised, display))
                break
        else:
            groups.append([(normalised, display)])
    return groups


def detect_conflicts(
    facts: Iterable[Any], *, employee_relative_delta: float = 0.10
) -> list[Conflict]:
    """检出一个栏目内的事实冲突；`facts` 需要有 `claim` 与 `source_url`。

    返回顺序固定为 `_SLOT_PATTERNS` 的声明顺序，保证报告可复现。
    """
    collected: dict[str, list[tuple[str, str, str]]] = {slot: [] for slot in _SLOT_PATTERNS}
    for fact in facts:
        claim = str(getattr(fact, "claim", "") or "")
        url = str(getattr(fact, "source_url", "") or "")
        for slot, (normalised, display) in _slot_values(claim).items():
            collected[slot].append((normalised, display, url))

    conflicts: list[Conflict] = []
    for slot, (label, _) in _SLOT_PATTERNS.items():
        entries = collected[slot]
        if len(entries) < 2:
            continue

        if slot == "headquarters":
            raw_groups = _group_hq([(n, d) for n, d, _ in entries])
            if len(raw_groups) < 2:
                continue
            values = tuple(
                SlotValue(
                    display=group[0][1],
                    normalised=group[0][0],
                    source_urls=tuple(dict.fromkeys(
                        url for n, d, url in entries if (n, d) in group
                    )),
                )
                for group in raw_groups
            )
        elif slot == "employee_count":
            numbers = sorted({int(n) for n, _, _ in entries})
            hi, lo = numbers[-1], numbers[0]
            if hi == 0 or (hi - lo) / hi <= employee_relative_delta:
                continue
            values = tuple(
                SlotValue(
                    display=f"{value:,}",
                    normalised=str(value),
                    source_urls=tuple(dict.fromkeys(
                        url for n, d, url in entries if int(n) == value
                    )),
                )
                for value in numbers
            )
        else:  # founded_year
            distinct = list(dict.fromkeys(n for n, _, _ in entries))
            if len(distinct) < 2:
                continue
            values = tuple(
                SlotValue(
                    display=value,
                    normalised=value,
                    source_urls=tuple(dict.fromkeys(
                        url for n, _, url in entries if n == value
                    )),
                )
                for value in distinct
            )

        conflicts.append(Conflict(slot=slot, label=label, values=values))
    return conflicts
