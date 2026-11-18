"""R4-1 验收：Company 冲突标注（同轮才判）。

规则（用户 2026-11-18 确认）：不同轮次的取值视为陆续补充/修正，不算冲突；
只有同一轮内出现两个不同取值才标注。冲突渲染成报告引用块并带 [n]。

验证：
1. 同一轮两个不同成立年份 → 段落 conflicts 有 1 条，报告出现 `>` 引用块带编号；
2. 跨轮两个不同年份 → 不标冲突；
3. 同一轮同一取值 → 不标冲突。
"""

from __future__ import annotations

from config.loader import get_settings
from graph.agents.company.analyzer import detect_same_round_conflicts
from graph.nodes.assemble import assemble_report


def _fact(claim: str, url: str, round_no: int = 0) -> dict:
    return {"claim": claim, "source_url": url, "confidence": 0.8, "_round": round_no}


def test_same_round_conflict_detected() -> None:
    s = get_settings()
    facts = [
        _fact("Notion 成立于 2013 年。", "https://e.org/a", 0),
        _fact("Notion 成立于 2014 年。", "https://e.org/b", 0),
    ]
    conflicts = detect_same_round_conflicts(facts, "Notion", s)["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["slot"] == "founded_year"
    assert {v["display"] for v in conflicts[0]["values"]} == {"2013", "2014"}


def test_cross_round_difference_is_not_conflict() -> None:
    """跨轮不同取值 = 陆续补充，不判冲突。"""
    s = get_settings()
    facts = [
        _fact("Notion 成立于 2013 年。", "https://e.org/a", 0),
        _fact("Notion 成立于 2014 年。", "https://e.org/b", 1),
    ]
    assert detect_same_round_conflicts(facts, "Notion", s)["conflicts"] == []


def test_same_value_same_round_no_conflict() -> None:
    s = get_settings()
    facts = [
        _fact("Notion 成立于 2013 年。", "https://e.org/a", 0),
        _fact("Notion 于 2013 年成立。", "https://e.org/b", 0),
    ]
    assert detect_same_round_conflicts(facts, "Notion", s)["conflicts"] == []


def test_conflict_rendered_as_quote_block_with_citation() -> None:
    """报告层渲染：引用块（非 bullet），带 [n] 编号。"""
    s = get_settings()
    facts = [
        _fact("Notion 成立于 2013 年。", "https://e.org/a", 0),
        _fact("Notion 成立于 2014 年。", "https://e.org/b", 0),
    ]
    conflicts = detect_same_round_conflicts(facts, "Notion", s)["conflicts"]
    para = {
        "key": "company", "status": "ok",
        "facts": [{"claim": "Notion 成立于 2013 年。", "source_url": "https://e.org/a"}],
        "references": {
            "https://e.org/a": {"title": "A", "score": 0.9},
            "https://e.org/b": {"title": "B", "score": 0.8},
        },
        "conflicts": conflicts,
    }
    report, _ = assemble_report("Notion", [para], s)
    quote = [ln for ln in report.splitlines() if ln.startswith("> ")]
    assert len(quote) == 1
    assert "来源冲突" in quote[0] and "2013" in quote[0] and "2014" in quote[0]
    assert "[1]" in quote[0] or "[2]" in quote[0], "冲突行应带引用编号"
