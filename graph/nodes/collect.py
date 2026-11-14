"""采集链路节点（S4）：grounding / curate。

S4 起 `research` 由图子图承担（`graph/subgraphs/research.py`），本文件不再包含
S3 的单节点版 `make_research_node` —— 精确回退改由 `Send` 派发实现。

curate 每轮基于**全量** `*_data` 重算 curated_data / references，
配合 `replace_mapping` reducer，上一轮已失效的引用会被自动移除。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from langchain_core.messages import AIMessage

from capabilities.retrieval import SECTION_FIELDS
from config.loader import Settings
from graph.state import ResearchState

logger = logging.getLogger(__name__)

Node = Callable[[ResearchState], Any]


def make_grounding_node(settings: Settings) -> Node:
    async def grounding(state: ResearchState) -> dict[str, Any]:
        return {
            "messages": [
                AIMessage(content=f"开始调研 {state['company']}（模式 {settings.app.mode}）")
            ]
        }

    return grounding


def make_curate_node(settings: Settings) -> Node:
    async def curate(state: ResearchState) -> dict[str, Any]:
        threshold = settings.graph.evidence.min_relevance_score
        require_url = settings.graph.evidence.require_source_url
        curated: dict[str, dict[str, Any]] = {}
        references: dict[str, dict[str, Any]] = {}
        dropped = 0

        for section, field in SECTION_FIELDS.items():
            for url, doc in state.get(field, {}).items():
                if float(doc.get("score", 0)) < threshold:
                    dropped += 1
                    continue
                if require_url and not doc.get("url"):
                    dropped += 1
                    continue
                item = dict(doc)
                item["url"] = url
                item["section"] = section
                curated[url] = item
                references[url] = {
                    "title": item.get("title", ""),
                    "score": float(item.get("score", 0)),
                    "used_by": [section],
                }

        return {
            "curated_data": curated,
            "references": references,
            "review_notes": [
                {"node": "curate", "kept": len(curated), "dropped": dropped, "threshold": threshold}
            ],
        }

    return curate
