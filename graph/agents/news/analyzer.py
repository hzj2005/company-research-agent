"""R4-2 News 专属加工：时效标注 + 事件去重（不删事实）。

复用 capabilities.postprocess.news_postprocess：给每条事实标注推断年份与 stale，
按「动作词 + 年份」聚成事件组（多来源计数）。**不删事实**——日期是从正文抠的，
不精确，误删代价高于保留。是否在报告里弱化由 postprocess 开关控制（报告层）。

产出 analysis（结构化，进段落）：
  {events: [...], stale_count: N, stale_urls: [...], reference_year: Y}
"""

from __future__ import annotations

from datetime import date
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


def analyze_news(
    facts: list[dict[str, Any]], company: str, settings: Settings,
    source_texts: dict[str, str] | None = None,
) -> dict[str, Any]:
    """时效标注 + 事件去重，全部保留、只标注。"""
    from capabilities.postprocess import news_postprocess

    result = news_postprocess(_to_facts(facts), reference_year=date.today().year)
    stale = [i for i in result["items"] if i.get("stale")]
    return {
        "conflicts": [],
        "analysis": {
            "events": result["events"],
            "stale_count": len(stale),
            "stale_urls": sorted({str(i["source_url"]) for i in stale}),
            "reference_year": result["reference_year"],
        },
    }
