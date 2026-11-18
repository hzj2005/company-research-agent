"""R4-3 Financial 专属加工：融资时间线 + 数字保真 + 同轮冲突。

复用 capabilities.finance_postprocess：
- 时间线：按年份排序（轮次是时间序列，跨轮不同金额不算冲突）；
- 数字保真：金额必须原样出现在原文 content 里，否则标注 unverified（不静默采信）；
- 同轮冲突：同一轮次出现不同金额才标注。

产出 analysis（进段落）：{timeline, unverified, conflicts, rounds_count}
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


def analyze_financial(
    facts: list[dict[str, Any]], company: str, settings: Settings,
    source_texts: dict[str, str] | None = None,
) -> dict[str, Any]:
    """融资时间线 + 数字保真 + 同轮金额冲突。"""
    from capabilities.finance_postprocess import finance_postprocess

    result = finance_postprocess(_to_facts(facts), source_texts=source_texts or None)
    return {
        "conflicts": result.get("conflicts", []),
        "analysis": {
            "timeline": result.get("timeline", []),
            "unverified": result.get("unverified_amounts", []),
            "rounds_count": len(result.get("timeline", [])),
        },
    }
