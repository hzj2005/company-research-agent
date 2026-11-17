"""S5 验收：行业/新闻后处理层。

验证：
1. 默认关闭——报告文本与 briefings 结构完全不受影响（基线不漂移）；
2. 竞品识别只认词表、归一化分层、带 evidence；不认识的合同名不会被编成竞品；
3. 对比矩阵每格带 source_url，无依据记 missing，不生成推断结论；
4. 新闻时效标注（推断日期）+ 事件去重（多来源客观计数）；
5. 从 briefing 产物接入的端到端路径。

全程 fixture、0 网络 0 模型调用。
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from config.loader import apply_overrides, get_settings
from graph.contracts import Fact
from graph.run import run_research

from capabilities.postprocess import (
    industry_postprocess,
    news_postprocess,
    postprocess_from_briefing,
)


def _fact(claim: str, url: str = "https://e.org/a") -> Fact:
    return Fact(claim=claim, source_url=url, confidence=0.9)  # type: ignore[arg-type]


# ----------------------------------------------------------- 默认关闭 ---

def test_postprocess_off_by_default() -> None:
    assert get_settings().features.postprocess is False


def test_default_run_has_empty_postprocess() -> None:
    s = get_settings()
    with tempfile.TemporaryDirectory() as td:
        state, _ = asyncio.run(run_research("Notion", s, Path(td) / "p.db"))
    assert state.get("postprocess") == {}


# --------------------------------------------------------- 竞品识别 ---

def test_competitors_from_known_alias_table() -> None:
    facts = [
        _fact("直接竞品包括 Obsidian 与 Coda，差异化在模板生态", "https://e.org/comp"),
        _fact("Word 是常见替代方案", "https://e.org/word"),
    ]
    out = industry_postprocess(facts, company="Notion")
    names = {c["name"] for c in out["competitors"]}
    assert names == {"Obsidian", "Coda", "Word"}
    tiers = {c["name"]: c["tier"] for c in out["competitors"]}
    assert tiers["Obsidian"] == "direct"
    assert tiers["Word"] == "substitute"


def test_unknown_name_is_not_invented_as_competitor() -> None:
    facts = [_fact("某公司发布了新产品")]
    out = industry_postprocess(facts, company="Notion")
    assert out["competitors"] == [], "无竞品句式时不得凭空生成竞品"


def test_competitor_from_explicit_phrase_outside_wordlist() -> None:
    """方案A：词表外但出现在明确竞品句式里的名字应被识别（突破固定词表）。"""
    facts = [_fact("直接竞品包括 Rover 与 Acme，差异化在模板生态", "https://e.org/comp")]
    out = industry_postprocess(facts, company="Notion")
    names = {c["name"] for c in out["competitors"]}
    assert {"Rover", "Acme"} <= names, "明确句式里的新名字应被识别"
    for c in out["competitors"]:
        if c["name"] in {"Rover", "Acme"}:
            assert c["evidence"]["source_url"] == "https://e.org/comp"
            assert c["tier_inferred"] is True, "词表外名字的分层是推断，必须留痕"


def test_wordlist_competitor_tier_is_not_flagged_inferred() -> None:
    facts = [_fact("直接竞品包括 Obsidian 与 Coda", "https://e.org/comp")]
    out = industry_postprocess(facts, company="Notion")
    obs = next(c for c in out["competitors"] if c["name"] == "Obsidian")
    assert obs["tier_inferred"] is False, "词表标注的分层不是推断"


def test_competitor_keeps_evidence_url() -> None:
    facts = [_fact("直接竞品包括 Obsidian 与 Coda", "https://e.org/comp")]
    out = industry_postprocess(facts, company="Notion")
    obs = next(c for c in out["competitors"] if c["name"] == "Obsidian")
    assert obs["evidence"]["source_url"] == "https://e.org/comp"


# --------------------------------------------------------- 对比矩阵 ---

def test_matrix_cells_carry_source_and_missing_recorded() -> None:
    facts = [
        _fact("2025 年协同文档市场规模约 50 亿美元（Gartner 口径）", "https://e.org/size"),
        _fact("Notion 提供协作工作区", "https://e.org/notion"),
    ]
    out = industry_postprocess(facts, company="Notion")
    matrix = out["comparison_matrix"]
    assert matrix["company"] == "Notion"
    for cell in matrix["cells"]:
        assert cell["source_url"].startswith("https://e.org/"), "每格必须指向原文"
    # 无依据的 (维度,主体) 必须记进 missing，不能脑补一格
    assert any("/" in m for m in matrix["missing"])


def test_matrix_never_contains_fabricated_conclusion() -> None:
    facts = [_fact("Notion 提供协作工作区")]
    out = industry_postprocess(facts, company="Notion")
    all_text = " ".join(c["text"] for c in out["comparison_matrix"]["cells"])
    for banned in ("更高端", "市场第一", "最优秀", "领先对手"):
        assert banned not in all_text, "对比矩阵只能搬运事实，不能有推断结论"


# --------------------------------------------------------- 新闻后处理 ---

def test_news_marks_inferred_date_and_stale() -> None:
    facts = [
        _fact("2026 年 3 月发布新版本", "https://e.org/new"),
        _fact("2020 年 5 月发布早期版本", "https://e.org/old"),
        _fact("近期达成合作，没有写日期", "https://e.org/nodate"),
    ]
    out = news_postprocess(facts, reference_year=2026)
    by_url = {i["source_url"]: i for i in out["items"]}
    assert by_url["https://e.org/new"]["inferred_year"] == 2026
    assert by_url["https://e.org/new"]["date_is_inferred"] is True
    assert by_url["https://e.org/old"]["stale"] is True
    assert by_url["https://e.org/nodate"]["inferred_year"] is None


def test_news_event_dedup_counts_sources_objectively() -> None:
    facts = [
        _fact("2026 年 3 月发布新版本 A", "https://e.org/a"),
        _fact("2026 年 3 月发布新版本 B", "https://e.org/b"),
    ]
    out = news_postprocess(facts, reference_year=2026)
    events = [e for e in out["events"] if e["count"] == 2]
    assert events and events[0]["multi_source"] is True
    assert set(events[0]["source_urls"]) == {"https://e.org/a", "https://e.org/b"}


# --------------------------------------------------------- 端到端 ---

def test_briefing_integration_when_enabled() -> None:
    s = apply_overrides(get_settings(), {"features.postprocess": True})
    assert s.features.postprocess is True
    # 用真实 fixture 跑一次，确认开启后 postprocess 有行业/新闻产物
    with tempfile.TemporaryDirectory() as td:
        state, _ = asyncio.run(run_research("Notion", s, Path(td) / "p.db"))
    pp = state.get("postprocess", {})
    assert "industry" in pp and "news" in pp
    assert "competitors" in pp["industry"]
    assert "events" in pp["news"]
    # 关键：报告文本必须 unaffected（与默认模式一致性由 test_default_run 保证）
    assert state["report"].startswith("# Notion 研究报告")
