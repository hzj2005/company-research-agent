"""判定与回退节点（S3）：evidence_check / rewrite_query / degrade。

这是本项目最核心的改造：原版 prompt 写着 `Never mention "no information found"`，
检索不到时会硬凑事实。这里把「证据够不够」变成显式的图节点 + 条件边，
查不到就改写 query 重搜，重试上限用完就明确拒答。
"""

from __future__ import annotations

from typing import Any, Callable

from config.loader import Settings
from graph.state import ResearchState

Node = Callable[[ResearchState], Any]


def make_evidence_check_node(settings: Settings) -> Node:
    async def evidence_check(state: ResearchState) -> dict[str, Any]:
        min_docs = settings.graph.evidence.min_docs_per_section
        curated = state.get("curated_data", {})
        degraded = set(state.get("degraded_sections", []))
        verdicts: dict[str, str] = {}
        counts: dict[str, int] = {}

        for section in settings.graph.sections:
            if section in degraded:
                verdicts[section] = "degraded"
                counts[section] = 0
                continue
            n = sum(
                1
                for doc in curated.values()
                if doc.get("section") == section and doc.get("url")
            )
            counts[section] = n
            verdicts[section] = "sufficient" if n >= min_docs else "insufficient"

        return {
            "evidence_verdict": verdicts,
            "review_notes": [
                {"node": "evidence_check", "counts": counts, "verdicts": verdicts}
            ],
        }

    return evidence_check


def make_rewrite_query_node(settings: Settings) -> Node:
    async def rewrite_query(state: ResearchState) -> dict[str, Any]:
        verdicts = state.get("evidence_verdict", {})
        pending = [s for s, v in verdicts.items() if v == "insufficient"]
        counts = state.get("retry_count", {})
        updates = {s: counts.get(s, 0) + 1 for s in pending}
        queries: dict[str, list[str]] = {}
        for section in pending:
            n = updates[section]
            history = list(state.get("rewrite_queries", {}).get(section, []))
            history.append(f"{state['company']} {section} 补充公开资料 第{n}轮")
            queries[section] = history

        return {
            "retry_count": updates,
            "rewrite_queries": queries,
            "review_notes": [
                {
                    "node": "rewrite_query",
                    "sections": pending,
                    "round": max(updates.values()) if updates else 0,
                    "queries": queries,
                }
            ],
        }

    return rewrite_query


def make_degrade_node(settings: Settings) -> Node:
    async def degrade(state: ResearchState) -> dict[str, Any]:
        verdicts = state.get("evidence_verdict", {})
        pending = [s for s, v in verdicts.items() if v == "insufficient"]
        message = settings.graph.degrade.message
        return {
            "degraded": True,
            "degraded_sections": pending,
            "evidence_verdict": {s: "degraded" for s in pending},
            "review_notes": [
                {
                    "node": "degrade",
                    "sections": pending,
                    "enabled": settings.graph.degrade.enabled,
                    "message": message if settings.graph.degrade.enabled else "",
                }
            ],
        }

    return degrade
