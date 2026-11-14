"""采集链路节点（S3）：grounding / research / curate。

- research 调 `@tool` 取回文档，按栏目写入对应 `*_data`（reducer 去重合并）
- curate 按配置阈值过滤，产出 `curated_data` 与 `references` 同一份来源字典，
  让正文行内引用与末尾 References 可自动对齐（AGENT.md 第 8 条）
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from capabilities.retrieval import SECTION_FIELDS
from config.loader import Settings
from graph.conditions import sections_to_research
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


def make_research_node(settings: Settings, document_tool: StructuredTool) -> Node:
    async def research(state: ResearchState) -> dict[str, Any]:
        # 回退轮次 = 已重试次数；rewrite_query 节点在回退前 +1
        round_no = max(state.get("retry_count", {}).values(), default=0)
        sections = sections_to_research(state, settings)
        raw: dict[str, list[dict[str, Any]]] = await document_tool.ainvoke(
            {"company": state["company"], "sections": sections, "round_no": round_no}
        )
        update: dict[str, Any] = {}
        for section, docs in raw.items():
            field = SECTION_FIELDS.get(section)
            if field is None:
                logger.warning("未知栏目 %s，跳过", section)
                continue
            update[field] = {doc["url"]: doc for doc in docs}
        update["review_notes"] = [
            {
                "node": "research",
                "round": round_no,
                "sections": sections,
                "docs": sum(len(v) for v in raw.values()),
            }
        ]
        return update

    return research


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
