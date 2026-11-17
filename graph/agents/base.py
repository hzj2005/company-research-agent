"""基础栏目节点：检索 → 出文档（S4 阶段 Industry/News 用）。

S5 会为这两个栏目加差异能力（竞品识别 / 时效过滤），届时替换为本栏目
专属节点。此处保留与旧 make_analyst_node 完全等价的行为，确保 S4 拆分
过程中这两个栏目零行为变化、可单独回滚。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import StructuredTool

from capabilities.retrieval import SECTION_FIELDS
from config.loader import Settings

logger = logging.getLogger(__name__)


def make_base_node(settings: Settings, document_tool: StructuredTool, section: str) -> Any:
    """返回一个只做检索、不做额外处理的栏目节点。"""

    async def base_agent(state: dict[str, Any]) -> dict[str, Any]:
        field = SECTION_FIELDS[section]
        round_no = int(state.get("retry_count", {}).get(section, 0))
        raw = await document_tool.ainvoke(
            {"company": state["company"], "sections": [section], "round_no": round_no}
        )
        docs = list(raw.get(section, []))
        return {
            field: {str(doc["url"]): doc for doc in docs},
            "review_notes": [
                {
                    "node": "research",
                    "analyst": section,
                    "round": round_no,
                    "sections": [section],
                    "docs": len(docs),
                }
            ],
        }

    return base_agent
