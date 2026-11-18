"""R3：子图产出"栏目段落"的共享逻辑。

每张子图：检索 → 抽取 → 校验 → 调用本模块写自己的段落。
段落里只有事实（claim + source_url）+ 状态 + 冲突标注，**不含编号**——
编号与 References 由报告层 assemble_report 统一处理（用户 2026-11-17 决策）。
"""

from __future__ import annotations

from typing import Any

from config.loader import Settings
from graph.contracts import Fact, SectionBrief


def make_paragraph(
    key: str,
    section: str,
    facts: list[Fact],
    *,
    settings: Settings,
    degraded: bool = False,
    conflicts: list[Any] | None = None,
    references: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """把一个栏目抽出的 facts 写成段落产物（供报告层拼装）。

    refs 来自该栏目检索到的文档：url -> {title, score}，供统一编号排序用。
    """
    if degraded or not facts:
        return {
            "key": key,
            "section": section,
            "status": "degraded" if degraded else "no_evidence",
            "facts": [],
            "conflicts": [],
            "references": references or {},
        }
    return {
        "key": key,
        "section": section,
        "status": "ok",
        "facts": [f.model_dump(mode="json") for f in facts],
        "conflicts": conflicts or [],
        "references": references or {},
    }


def brief_to_facts(brief: SectionBrief) -> list[Fact]:
    """抽取结果 → facts（保持 source_url 原样，供拼装器编号）。"""
    return list(brief.facts)
