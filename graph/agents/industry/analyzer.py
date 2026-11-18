"""R4-4 Industry 专属加工：竞品识别 + 槽位分类 + 事实对比矩阵。

复用 capabilities.postprocess.industry_postprocess：
- 竞品：词表命中 + "竞品包括/对标 X" 句式抽取，都带 evidence fact（防幻觉）；
- 槽位分类：把行业事实按维度归组；
- 对比矩阵：只做**原文搬运**，缺的格子标 missing，不生成"谁更强"的评价。

产出 analysis（进段落）：{competitors, slots, comparison_matrix}
"""

from __future__ import annotations

from typing import Any

from config.loader import Settings
from graph.contracts import Fact


def _to_facts(raw: list[dict[str, Any]]) -> list[Fact]:
    out: list[Fact] = []
    for f in raw:
        try:
            out.append(
                Fact(
                    claim=str(f["claim"]),
                    source_url=f["source_url"],
                    confidence=float(f.get("confidence", 0.0)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def analyze_industry(
    facts: list[dict[str, Any]], company: str, settings: Settings,
    source_texts: dict[str, str] | None = None,
) -> dict[str, Any]:
    """竞品识别 + 框架归类 + 事实对比矩阵（不评价强弱）。"""
    from capabilities.postprocess import industry_postprocess

    result = industry_postprocess(_to_facts(facts), company=company)
    return {
        "conflicts": [],
        "analysis": {
            "competitors": result.get("competitors", []),
            "slots": result.get("slots", {}),
            "comparison_matrix": result.get("comparison_matrix", {}),
        },
    }
