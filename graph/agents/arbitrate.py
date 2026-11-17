"""Orchestrator 的仲裁节点：4 路 Agent 结果汇合后的跨栏一致性检查。

职责边界（PROJECT_PLAN_V2.md 3/4.1）：
- 只做**跨栏目**冲突标注（Company 说 2013、News 说 2014 这种），只标不改；
- 同栏目冲突仍由报告层 `detect_conflicts` 做（report.py:160），此处不重复；
- 不产出报告内容、不改任何 *_data，只写 review_notes 留痕。

为什么不复用 capabilities.conflict.detect_conflicts：那个模块的槽位正则是
英文的（founded|headquartered），而本项目 fixture/报告的正文是中文事实
（"成立于 2013 年"），直接复用会空跑、检出率恒为 0（S4 已踩过这个坑）。
这里用中英双语正则做最小跨栏年份比对，诚实标注只覆盖 founded_year 一个槽位。

纯规则、0 模型 0 网络。默认随 multi_agent 开关启用；关闭时该节点不进图。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from capabilities.retrieval import SECTION_FIELDS
from config.loader import Settings

logger = logging.getLogger(__name__)

# 中英双语成立年份槽位（跨栏比对用，只做这一个能可靠判定的槽位）
_FOUNDED = re.compile(
    r"(?:成立于|创办于|创立于|founded|established|incorporated)\D{0,12}?((?:19|20)\d{2})",
    re.IGNORECASE,
)


def make_arbitrate_node(settings: Settings) -> Any:
    async def arbitrate(state: dict[str, Any]) -> dict[str, Any]:
        # 按栏目收集"成立年份"取值，跨栏出现不同值才标注（同栏内多值由报告层管）
        years_by_section: dict[str, set[str]] = {}
        for section, field in SECTION_FIELDS.items():
            years: set[str] = set()
            for doc in state.get(field, {}).values():
                m = _FOUNDED.search(str(doc.get("content", "")))
                if m:
                    years.add(m.group(1))
            if years:
                years_by_section[section] = years

        all_years = {y for ys in years_by_section.values() for y in ys}
        # 真正的"跨栏"冲突：至少两个栏目都提到年份，且取值不一致。
        # 同栏内的多个年份（如 company 同时有 2013/2014）归报告层
        # detect_conflicts 管，arbitrate 不重复报（否则职责越界、误报）。
        cross_conflict = len(years_by_section) >= 2 and len(all_years) > 1

        note: dict[str, Any] = {
            "node": "arbitrate",
            "sections_checked": list(SECTION_FIELDS),
            "years_by_section": {k: sorted(v) for k, v in years_by_section.items()},
            "cross_section_year_conflict": sorted(all_years) if cross_conflict else [],
        }
        enabled = settings.features.conflict_annotation and cross_conflict
        return {"review_notes": [note] if enabled else []}

    return arbitrate
