"""Company Agent 的 nodes（四件套之一，R3）。

栏目任务流：pipeline(检索→消歧→extract→判定→返工→写段落)。
Company 特有：实体消歧（do_guard=True）。
extract 用本栏目 prompt + 共享三级降级链（graph/agents/extract.py）。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from config.loader import Settings
from graph.agents.company.prompts import COMPANY_ADDENDUM
from graph.agents.extract import extract_with_fallback
from graph.agents.pipeline import make_pipeline_node


async def company_extract(
    company: str, section: str, docs: list[dict[str, Any]], settings: Settings
) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    """Company extract：本栏目 prompt + 共享三级降级链。"""
    return await extract_with_fallback(
        company, section, docs, settings, addendum=COMPANY_ADDENDUM
    )


def make_company_pipeline_node(settings: Settings, document_tool: StructuredTool) -> Any:
    return make_pipeline_node(settings, "company", document_tool, company_extract, do_guard=True)
