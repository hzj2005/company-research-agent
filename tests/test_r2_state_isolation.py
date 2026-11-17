"""R2 验收（R3 迁移版）：四套独立 state 并行写回不互串、不重复累加。

R3 后回退发生在子图内部，主图 orchestrator 每 case 只派发一次；
子图内部 pipeline 自己返工（review_notes 里 attempt 标记）。
本测试验证：
1. 每张子图的 output schema 只含自己那一个 *_paragraph 字段；
2. 四栏目 references 互不串（按 URL 特征）；
3. 每个 pipeline 只写一次终态段落，orchestrator 只派发一次；
4. 回退轮：子图内 attempt 递增，首轮证据保留（累积）。
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from config.loader import get_settings
from graph.agents.company.state import CompanyAgentOutput
from graph.agents.financial.state import FinancialAgentOutput
from graph.agents.industry.state import IndustryAgentOutput
from graph.agents.news.state import NewsAgentOutput
from graph.run import run_research


def _paragraph_fields(schema: type) -> set[str]:
    return {k for k in schema.__annotations__ if k.endswith("_paragraph")}


def test_each_output_schema_has_exactly_one_paragraph_field() -> None:
    assert _paragraph_fields(CompanyAgentOutput) == {"company_paragraph"}
    assert _paragraph_fields(IndustryAgentOutput) == {"industry_paragraph"}
    assert _paragraph_fields(FinancialAgentOutput) == {"financial_paragraph"}
    assert _paragraph_fields(NewsAgentOutput) == {"news_paragraph"}


def test_output_schemas_are_distinct() -> None:
    schemas = [CompanyAgentOutput, IndustryAgentOutput, FinancialAgentOutput, NewsAgentOutput]
    assert len(set(schemas)) == 4


def test_end_to_end_no_crosstalk_and_no_duplicate_notes() -> None:
    s = get_settings()
    with tempfile.TemporaryDirectory() as td:
        state, _ = asyncio.run(run_research("Notion", s, Path(td) / "p.db"))

    # 每个栏目的 references URL 只属于自己（按 fixture 命名特征）
    assert all("market" not in u for u in state["company_paragraph"]["references"])
    assert all("market" in u for u in state["industry_paragraph"]["references"])
    assert all(
        "funding" in u or "pricing" in u or "series" in u
        for u in state["financial_paragraph"]["references"]
    )
    assert all("news" in u for u in state["news_paragraph"]["references"])

    # orchestrator 每 case 只派发一次
    orch_notes = [n for n in state["review_notes"] if n.get("node") == "orchestrator"]
    assert len(orch_notes) == 1, "orchestrator 留痕重复累加了"
    # 每个 pipeline 只写一个终态段落留痕
    for section in ("company", "industry", "financial", "news"):
        notes = [n for n in state["review_notes"]
                 if n.get("node") == "pipeline" and n.get("section") == section]
        assert len(notes) == 1, f"{section} pipeline 留痕重复"


def test_subgraph_retry_keeps_first_round_evidence() -> None:
    """sparse case：子图内返工一次，首轮证据仍在段落里（累积不覆盖）。"""
    s = get_settings()
    with tempfile.TemporaryDirectory() as td:
        state, _ = asyncio.run(run_research("Linear", s, Path(td) / "p.db"))

    company = state["company_paragraph"]
    claims = [f["claim"] for f in company["facts"]]
    # 首轮（overview）与返工轮（about/customers）的证据都在
    assert any("项目管理工具" in c for c in claims), "首轮证据丢了"
    assert any("团队分布" in c for c in claims), "返工轮证据丢了"
    # retry_count 由子图传出，供评测读取
    assert state["retry_count"].get("company") == 1
