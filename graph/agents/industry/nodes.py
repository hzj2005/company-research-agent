"""Industry Agent 的栏目专属实现 + 两阶段检索的两个节点。

行业是唯一需要**两轮不同 query** 的栏目：
第一轮的 query 是围绕目标公司的（`X industry market landscape competitors`），
拿不到竞品的独立事实——所以矩阵会是稀的。第二轮拿第一轮扫出的竞品名单去查，
才有「竞品自己的定价 / 定位」可填。

- `competitor_scan`：从已抽事实里识别竞品，产出待查名单（含分层）；
- `competitor_fetch`：按名单逐条发 query 补检索，新文档交给下一次 extract。
"""

from __future__ import annotations

from typing import Any

from capabilities.postprocess import industry_postprocess
from config.loader import Settings
from graph.agents.extract import extract_with_fallback
from graph.agents.industry.prompts import INDUSTRY_ADDENDUM
from graph.agents.primitives import to_facts


async def industry_extract(
    company: str, section: str, docs: list[dict[str, Any]], settings: Settings
) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    """Industry extract：本栏目 prompt + 共享三级降级链。"""
    return await extract_with_fallback(
        company, section, docs, settings, addendum=INDUSTRY_ADDENDUM
    )


def make_competitor_scan_node(section: str, settings: Settings) -> Any:
    """竞品扫描：产出第二轮要查的名单。只在开关打开时工作。"""
    cfg = settings.graph.competitor_fetch

    def scan(state: dict[str, Any]) -> dict[str, Any]:
        facts = to_facts(state.get("facts") or [])
        if not cfg.enabled or cfg.max_competitors <= 0 or not facts:
            return {
                "competitor_candidates": [],
                "notes": [
                    *(state.get("notes") or []),
                    {"node": "competitor_scan", "section": section,
                     "status": "skipped", "reason": "disabled_or_no_facts"},
                ],
            }

        result = industry_postprocess(facts, company=state["company"])
        target = state["company"].strip().lower()
        candidates = [
            {"name": c["name"], "tier": c.get("tier", "direct")}
            for c in result.get("competitors", [])
            # 目标公司自己不是竞品：行业文章常写「X 的竞品包括 X 自身产品线」，
            # 不过滤会导致第二轮拿自己的名字去搜（2026-11-18 首跑实测踩到）
            if c.get("name") and c["name"].strip().lower() != target
        ][: cfg.max_competitors]

        return {
            "competitor_candidates": candidates,
            "notes": [
                *(state.get("notes") or []),
                {"node": "competitor_scan", "section": section,
                 "status": "ok", "candidates": [c["name"] for c in candidates]},
            ],
        }

    return scan


def make_competitor_fetch_node(section: str, document_tool: Any) -> Any:
    """竞品补检索：每个竞品一条 query，拿到的是竞品自己的文档。

    追加到 state["docs"]，由后续 extract 只抽「没抽过的文档」。没有候选名单时
    不发起任何检索（0 额度）。
    """

    async def fetch(state: dict[str, Any]) -> dict[str, Any]:
        candidates = state.get("competitor_candidates") or []
        if not candidates:
            return {}

        queries = [
            f"{c['name']} pricing features positioning" for c in candidates
        ]
        raw = await document_tool.ainvoke(
            {
                "company": state["company"],
                "sections": [section],
                "round_no": 0,
                "queries": queries,
            }
        )
        new_docs = [dict(d) for d in (raw.get(section) or [])]
        docs = [*(state.get("docs") or []), *new_docs]

        return {
            "docs": docs,
            "notes": [
                *(state.get("notes") or []),
                {"node": "competitor_fetch", "section": section,
                 "queries": len(queries), "docs": len(new_docs)},
            ],
        }

    return fetch


def route_after_scan(state: dict[str, Any]) -> str:
    """有名单才补检索；没有就直接进矩阵。"""
    return "fetch" if state.get("competitor_candidates") else "matrix"
