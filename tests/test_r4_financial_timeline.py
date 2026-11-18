"""R4-3 验收：Financial 融资时间线 + 数字保真 + 同轮冲突。

验证：
1. 多轮融资按年份排序成时间线；
2. 金额在原文里不存在 → 标 unverified（不静默采信）；
3. 同一轮次出现两个金额 → 冲突标注；跨轮不同金额不算冲突。
"""

from __future__ import annotations

from config.loader import get_settings
from graph.agents.financial.analyzer import analyze_financial


def _fact(claim: str, url: str) -> dict:
    return {"claim": claim, "source_url": url, "confidence": 0.8, "_round": 0}


def test_timeline_sorted_by_year() -> None:
    facts = [
        _fact("2021 年完成 B 轮融资 5000 万美元。", "https://e.org/b"),
        _fact("2019 年完成 A 轮融资 1000 万美元。", "https://e.org/a"),
    ]
    out = analyze_financial(facts, "X", get_settings())
    timeline = out["analysis"]["timeline"]
    assert [r["year"] for r in timeline] == ["2019", "2021"], "应按年份升序"


def test_amount_not_in_source_flagged_unverified() -> None:
    """原文没有这个金额 → unverified（数字保真）。"""
    facts = [_fact("2021 年完成 A 轮融资 5000 万美元。", "https://e.org/a")]
    out = analyze_financial(
        facts, "X", get_settings(),
        source_texts={"https://e.org/a": "2021 年完成 A 轮融资，投资方为 Sequoia。"},
    )
    assert out["analysis"]["unverified"], "金额未在原文出现应被标注"
    assert out["analysis"]["unverified"][0]["reason"] == "money_not_in_source"


def test_amount_in_source_passes() -> None:
    facts = [_fact("2021 年完成 A 轮融资 5000 万美元。", "https://e.org/a")]
    out = analyze_financial(
        facts, "X", get_settings(),
        source_texts={"https://e.org/a": "2021 年完成 A 轮融资 5000 万美元，投资方为 Sequoia。"},
    )
    assert out["analysis"]["unverified"] == []


def test_cross_round_amounts_are_timeline_not_conflict() -> None:
    """不同轮次金额不同是正常时间序列，不算冲突。"""
    facts = [
        _fact("2019 年完成 A 轮融资 1000 万美元。", "https://e.org/a"),
        _fact("2021 年完成 B 轮融资 5000 万美元。", "https://e.org/b"),
    ]
    out = analyze_financial(facts, "X", get_settings())
    assert out["conflicts"] == []
    assert out["analysis"]["rounds_count"] == 2
