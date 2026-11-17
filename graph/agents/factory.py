"""R3：构建四张独立编译的 Agent 子图（四件套的 graph.py 汇总入口）。

每张子图现在由自己的 graph.py 定义（state + nodes + prompts + graph）。
本工厂只负责汇总，供 Orchestrator 派发。

四张子图输出各自的 <section>_paragraph（facts + 状态，不带编号），
由 Orchestrator 收集后传给报告层统一编号拼装。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from config.loader import Settings
from graph.agents.company.graph import build_company_subgraph
from graph.agents.financial.graph import build_financial_subgraph
from graph.agents.industry.graph import build_industry_subgraph
from graph.agents.news.graph import build_news_subgraph


def build_all_agent_subgraphs(
    settings: Settings, document_tool: StructuredTool
) -> dict[str, Any]:
    """构建四张独立编译子图，供 Orchestrator 派发。"""
    return {
        "company": build_company_subgraph(settings, document_tool),
        "industry": build_industry_subgraph(settings, document_tool),
        "financial": build_financial_subgraph(settings, document_tool),
        "news": build_news_subgraph(settings, document_tool),
    }
