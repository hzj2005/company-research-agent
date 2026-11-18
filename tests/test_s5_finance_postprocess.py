"""S5 财务后处理验收：数字保真 / 时间线 / 同轮冲突 / FundingRound 契约。

补齐 V2 设计里因"抽取链下沉风险大"搁置的 4 个财务能力。
验证规则实现的正确性与边界（估值≠融资、跨轮≠冲突），全程 0 模型 0 网络。
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from config.loader import apply_overrides, get_settings
from graph.contracts import Fact
from graph.run import run_research

from capabilities.finance_postprocess import finance_postprocess


def _fact(claim: str, url: str = "https://e.org/a") -> Fact:
    return Fact(claim=claim, source_url=url, confidence=0.9)  # type: ignore[arg-type]


# ----------------------------------------------------------- 时间线 ---

def test_timeline_sorted_by_year() -> None:
    facts = [
        _fact("2023 年完成 B 轮融资 2 亿美元", "https://e.org/b"),
        _fact("2021 年完成 A 轮融资 5000 万美元", "https://e.org/a"),
    ]
    out = finance_postprocess(facts)
    assert [r["round"] for r in out["timeline"]] == ["A轮", "B轮"]
    assert [r["year"] for r in out["timeline"]] == ["2021", "2023"]


def test_cross_round_amount_difference_is_not_conflict() -> None:
    """A 轮 5000 万、B 轮 2 亿是时间序列，不是冲突（财务与公司的核心区别）。"""
    facts = [
        _fact("2021 年完成 A 轮融资 5000 万美元", "https://e.org/a"),
        _fact("2023 年完成 B 轮融资 2 亿美元", "https://e.org/b"),
    ]
    out = finance_postprocess(facts)
    assert out["conflicts"] == [], "不同轮次金额不同是正常时间线"


def test_same_round_amount_conflict_is_flagged() -> None:
    facts = [
        _fact("2021 年完成 A 轮融资 5000 万美元", "https://e.org/a"),
        _fact("2021 年完成 A 轮融资 8000 万美元", "https://e.org/a2"),
    ]
    out = finance_postprocess(facts)
    assert len(out["conflicts"]) == 1
    assert out["conflicts"][0]["round"] == "A轮"
    assert len(out["conflicts"][0]["amounts"]) == 2


# ----------------------------------------------------------- 估值陷阱 ---

def test_valuation_is_not_taken_as_financing_amount() -> None:
    """'融资 2 亿，估值 100 亿' 只取融资额 2 亿。"""
    facts = [_fact("2023 年完成 B 轮融资 2 亿美元，估值达到 100 亿美元", "https://e.org/b")]
    out = finance_postprocess(facts)
    entry = out["timeline"][0]
    assert entry["amount"] == "2 亿美元"
    assert "100 亿" not in entry["amount"]


# ----------------------------------------------------------- 数字保真 ---

def test_amount_verified_against_source() -> None:
    claim = "2021 年完成 A 轮融资 5000 万美元"
    source = {"https://e.org/a": "2021 年完成 A 轮融资 5000 万美元，由红杉领投。"}
    facts = [_fact(claim, "https://e.org/a")]
    out = finance_postprocess(facts, source_texts=source)
    assert out["timeline"][0]["amount_in_source"] is True
    assert out["unverified_amounts"] == []


def test_amount_not_in_source_is_flagged() -> None:
    """fact 里的金额在原文字里找不到 → 标注，不静默采信。"""
    claim = "完成 A 轮融资 5000 万美元"
    source = {"https://e.org/a": "完成 A 轮融资，金额未披露。"}
    facts = [_fact(claim, "https://e.org/a")]
    out = finance_postprocess(facts, source_texts=source)
    assert out["timeline"][0]["amount_in_source"] is False
    assert any(u["reason"] == "money_not_in_source" for u in out["unverified_amounts"])


# ----------------------------------------------------------- 契约构造 ---

def test_funding_round_contract_built_from_rules() -> None:
    facts = [_fact("2021 年完成 A 轮融资 5000 万美元，由红杉领投", "https://e.org/a")]
    out = finance_postprocess(facts)
    rounds = out["funding_rounds"]
    assert len(rounds) == 1
    r = rounds[0]
    assert r["round_name"] == "A轮"
    assert r["amount"] == "5000 万美元"  # 原样保留
    assert r["announced_year"] == "2021"
    assert "红杉" in r["investors"]
    assert r["evidence"]["source_url"] == "https://e.org/a"


def test_no_round_means_no_funding_entry() -> None:
    """'已披露多轮融资'没有具体轮次，不进时间线、不构造契约。"""
    facts = [_fact("已披露多轮融资，投资方包含多家风投机构", "https://e.org/funding")]
    out = finance_postprocess(facts)
    assert out["timeline"] == []
    assert out["funding_rounds"] == []


# ----------------------------------------------------------- 端到端 ---

def test_end_to_end_financial_postprocess_enabled() -> None:
    s = apply_overrides(get_settings(), {"features.postprocess": True})
    with tempfile.TemporaryDirectory() as td:
        state, _ = asyncio.run(run_research("Notion", s, Path(td) / "p.db"))
    pp = state.get("postprocess", {})
    assert "financial" in pp
    fin = pp["financial"]
    assert len(fin["timeline"]) >= 2  # fixture 有 A/B 两轮
    assert fin["conflicts"] == []  # 跨轮不判冲突
    assert all(r["evidence"]["source_url"] for r in fin["funding_rounds"])


def test_report_text_unchanged_with_financial_postprocess() -> None:
    """开启财务后处理不得改变**事实 bullet 与 References**（S7 基线零漂移）。

    R4 起（用户 2026-11-18 确认）：开启后允许新增引用块形式的附加分析行
    （融资时间线等），但正文事实与引用编号必须逐字不变——基线漂移的实质
    是"事实被改变"，不是"多了一行标注"。
    """
    s = get_settings()
    on = apply_overrides(s, {"features.postprocess": True})
    with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
        st_off, _ = asyncio.run(run_research("Notion", s, Path(td1) / "b.db"))
        st_on, _ = asyncio.run(run_research("Notion", on, Path(td2) / "c.db"))

    def bullets_and_refs(text: str) -> tuple[list[str], list[str]]:
        lines = text.splitlines()
        bullets = [ln for ln in lines if ln.startswith("- ")]
        refs_start = next((i for i, ln in enumerate(lines) if ln == "## References"), len(lines))
        return bullets, lines[refs_start:]

    off_b, off_r = bullets_and_refs(st_off["report"])
    on_b, on_r = bullets_and_refs(st_on["report"])
    assert off_b == on_b, "事实 bullet 必须逐字一致（基线零漂移）"
    assert off_r == on_r, "References 必须逐字一致"
    # 开启后新增的是引用块分析行，不是事实
    assert "融资时间线" in st_on["report"]
    assert "融资时间线" not in st_off["report"]
    assert not any("融资时间线" in b for b in on_b)
