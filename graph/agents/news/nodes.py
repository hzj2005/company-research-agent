"""News Agent 的栏目专属实现。

News 的独有阶段是**语义实体过滤**：新闻检索面最广，同名公司混入的概率最高，
而字面规则挡不住（见 `capabilities/entity_filter.py` 的论证与真实事故）。
抽取本身仍走共用三级降级链。
"""

from __future__ import annotations

from typing import Any

from config.loader import Settings
from graph.agents.extract import extract_with_fallback
from graph.agents.news.prompts import NEWS_ADDENDUM


async def news_extract(
    company: str, section: str, docs: list[dict[str, Any]], settings: Settings
) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    """News extract：本栏目 prompt + 共享三级降级链。"""
    return await extract_with_fallback(
        company, section, docs, settings, addendum=NEWS_ADDENDUM
    )
