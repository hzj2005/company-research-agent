"""News Agent 的 nodes（四件套之一，R3）。

栏目任务流：pipeline(检索→消歧→extract→判定→返工→写段落)。
extract 用本栏目 prompt + 共享三级降级链（graph/agents/extract.py）。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from config.loader import Settings
from graph.agents.news.prompts import NEWS_ADDENDUM
from graph.agents.extract import extract_with_fallback
from graph.agents.pipeline import make_pipeline_node


async def news_extract(
    company: str, section: str, docs: list[dict[str, Any]], settings: Settings
) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    """News extract：本栏目 prompt + 共享三级降级链。"""
    return await extract_with_fallback(
        company, section, docs, settings, addendum=NEWS_ADDENDUM
    )


def make_news_pipeline_node(settings: Settings, document_tool: StructuredTool) -> Any:
    return make_pipeline_node(settings, "news", document_tool, news_extract, do_guard=False)
