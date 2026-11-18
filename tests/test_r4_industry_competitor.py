"""R4-4 验收：Industry 竞品识别 + 槽位分类 + 对比矩阵（不评价强弱）。

验证：
1. 词表内竞品被识别且带 evidence；
2. 句式「竞品包括 X」能抽取词表外名字；
3. 对比矩阵只做原文搬运，缺格标 missing，不产生"更好/更强"之类的评语。
"""

from __future__ import annotations

from config.loader import get_settings
from graph.agents.industry.analyzer import analyze_industry


def _fact(claim: str, url: str) -> dict:
    return {"claim": claim, "source_url": url, "confidence": 0.8, "_round": 0}


def test_wordlist_competitor_detected_with_evidence() -> None:
    facts = [_fact("该赛道的主要竞品包括 Confluence 和 Coda。", "https://e.org/i")]
    out = analyze_industry(facts, "Notion", get_settings())
    names = {c["name"] for c in out["analysis"]["competitors"]}
    assert names, "应识别出竞品"
    assert all(c.get("evidence") for c in out["analysis"]["competitors"]), "竞品必须带 evidence"


def test_competitor_from_phrase_beyond_wordlist() -> None:
    """「与 X 对标」语序（名字在前）也应能抽取词表外名字。"""
    facts = [_fact("与 Acme 对标的产品也在争夺同一批用户。", "https://e.org/i")]
    out = analyze_industry(facts, "Notion", get_settings())
    names = {c["name"] for c in out["analysis"]["competitors"]}
    assert "Acme" in names, "句式抽取应能识别词表外名字"


def test_matrix_is_verbatim_and_marks_missing() -> None:
    facts = [
        _fact("Notion 支持团队协作与文档编辑。", "https://e.org/i"),
        _fact("主要竞品包括 Confluence。", "https://e.org/i2"),
    ]
    out = analyze_industry(facts, "Notion", get_settings())
    matrix = out["analysis"]["comparison_matrix"]
    assert "cells" in matrix and "missing" in matrix
    for cell in matrix["cells"]:
        assert cell["text"], "矩阵格子必须是原文搬运，非空"
        # 不得出现评价性结论词
        for banned in ("更好", "更强", "领先于", "优于"):
            assert banned not in cell["text"]


def test_analyzer_shape() -> None:
    out = analyze_industry([_fact("行业规模 50 亿。", "https://e.org/s")], "X", get_settings())
    assert set(out.keys()) == {"conflicts", "analysis"}
    assert set(out["analysis"].keys()) == {"competitors", "slots", "comparison_matrix"}
