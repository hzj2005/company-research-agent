"""Company Agent 的栏目专属实现。

R7 起节点编排写在 `graph.py`（每个栏目自己决定流程），本文件只保留
Company 自己的抽取实现：本栏目 prompt + 共享三级降级链。
"""

from __future__ import annotations

from typing import Any

from config.loader import Settings
from graph.agents.company.prompts import COMPANY_ADDENDUM
from graph.agents.extract import extract_with_fallback


async def company_extract(
    company: str, section: str, docs: list[dict[str, Any]], settings: Settings
) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    """Company extract：本栏目 prompt + 共享三级降级链。"""
    return await extract_with_fallback(
        company, section, docs, settings, addendum=COMPANY_ADDENDUM
    )
