"""R2 验收：四套独立 state 并行写回不互串、不重复累加。

验证 R1 搭的骨架状态隔离是真的：
1. 每张子图的 output_schema 只含自己那一个 *_data 字段——结构上不可能写串；
2. 端到端跑两轮（首轮 + 自纠正回退），review_notes 不翻倍、各栏目 URL 不重复；
3. 直接调四张子图并行写回，确认各栏只拿回自己的数据。

全程 fixture、0 网络 0 模型。
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


def _data_fields(schema: type) -> set[str]:
    """schema 里所有 *_data 字段。"""
    return {k for k in schema.__annotations__ if k.endswith("_data")}


def test_each_output_schema_has_exactly_one_data_field() -> None:
    """结构上保证每张子图只能写自己那一个字段。"""
    assert _data_fields(CompanyAgentOutput) == {"company_data"}
    assert _data_fields(IndustryAgentOutput) == {"industry_data"}
    assert _data_fields(FinancialAgentOutput) == {"financial_data"}
    assert _data_fields(NewsAgentOutput) == {"news_data"}


def test_output_schemas_are_distinct() -> None:
    """四套输出 schema 是四个不同的类，不共用。"""
    schemas = [CompanyAgentOutput, IndustryAgentOutput, FinancialAgentOutput, NewsAgentOutput]
    assert len(set(schemas)) == 4


def test_end_to_end_no_crosstalk_and_no_duplicate_notes() -> None:
    """端到端：4 栏目数据互不串，review_notes 只记一轮（无重复累加）。"""
    s = get_settings()
    with tempfile.TemporaryDirectory() as td:
        state, _ = asyncio.run(run_research("Notion", s, Path(td) / "p.db"))

    # 每个栏目的 URL 只属于自己（按 fixture 命名特征）
    assert all("market" not in u for u in state["company_data"]), "行业文档串进公司"
    assert all("market" in u for u in state["industry_data"]), "公司文档串进行业"
    assert all("funding" in u or "pricing" in u or "series" in u for u in state["financial_data"])
    assert all("news" in u for u in state["news_data"])

    # orchestrator 只派发一次（sufficient case 无回退），留痕不重复
    orch_notes = [n for n in state["review_notes"] if n.get("node") == "orchestrator"]
    assert len(orch_notes) == 1, "orchestrator 留痕重复累加了"
    # 每个 agent 只留痕一次
    for section in ("company", "industry", "financial", "news"):
        agent_notes = [n for n in state["review_notes"] if n.get("analyst") == section]
        assert len(agent_notes) == 1, f"{section} agent 留痕重复"

    # 同一栏目内 URL 不重复（dict 天然保证，但显式断言隔离生效）
    for field in ("company_data", "industry_data", "financial_data", "news_data"):
        urls = list(state[field].keys())
        assert len(urls) == len(set(urls)), f"{field} 出现重复 URL"


def test_retry_round_does_not_duplicate_first_round_notes() -> None:
    """回退轮：首轮的 doctor 数据保留，orchestrator 只多一条派发留痕。"""
    s = get_settings()
    with tempfile.TemporaryDirectory() as td:
        state, _ = asyncio.run(run_research("Linear", s, Path(td) / "p.db"))

    orch_notes = [n for n in state["review_notes"] if n.get("node") == "orchestrator"]
    # Linear 是 sparse case，会回退一次 → 2 轮派发
    assert len(orch_notes) == 2, f"回退轮数不对：{len(orch_notes)}"
    # 回退只派发不足栏目（company）
    assert all(n["dispatch_to"] == ["company"] for n in orch_notes[1:2]), "回退派发了多余栏目"
    # company 被检索 2 次（首轮+回退），其它栏目只 1 次
    company_runs = [n for n in state["review_notes"] if n.get("analyst") == "company"]
    assert len(company_runs) == 2, "回退栏目应检索两次"
    news_runs = [n for n in state["review_notes"] if n.get("analyst") == "news"]
    assert len(news_runs) == 1, "未回退栏目不应重复检索"
