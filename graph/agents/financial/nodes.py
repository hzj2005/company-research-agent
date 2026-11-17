"""Financial Agent 的 nodes（四件套之一，R3）。

栏目任务流：pipeline(检索→消歧→extract→判定→返工→写段落)。
Financial 特有：ticker_binding + 实体消歧（do_guard=True）。
extract 用本栏目自己的 prompt（数字保真/轮次不判冲突）。
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool

from config.loader import Settings
from graph.agents.pipeline import make_pipeline_node


async def financial_extract(
    company: str, section: str, docs: list[dict[str, Any]], settings: Settings
) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    """Financial 自己的 extract：LLM 抽事实 + 失败降级到规则。"""
    from capabilities.briefing import make_briefing_backend
    from capabilities.structured import extract_section_brief
    from graph.agents.financial.prompts import FINANCIAL_ADDENDUM
    from graph.agents.prompts import build_section_prompt

    if not docs:
        return [], "ok", [
            {"node": "extract", "section": section, "status": "no_docs"}
        ]

    backend = make_briefing_backend(
        settings, system_prompt=build_section_prompt(FINANCIAL_ADDENDUM)
    )
    try:
        result = await extract_section_brief(
            backend.chain, section=section, company=company, docs=docs, settings=settings
        )
        if result.brief.facts:
            return (
                [f.model_dump(mode="json") for f in result.brief.facts],
                "ok",
                [{"node": "extract", "section": section, "status": "llm",
                  "facts": len(result.brief.facts), "prompt": "financial"}],
            )
    except Exception:  # noqa: BLE001
        pass
    finally:
        await backend.aclose()

    facts = [
        {"claim": str(d["content"]), "source_url": d["url"],
         "confidence": float(d.get("score", 0) or 0)}
        for d in docs if d.get("url") and d.get("content")
    ]
    return facts, "no_retry", [
        {"node": "extract", "section": section, "status": "rule_fallback",
         "reason": "llm_failed_or_empty", "facts": len(facts)}
    ]


def make_financial_pipeline_node(settings: Settings, document_tool: StructuredTool) -> Any:
    return make_pipeline_node(settings, "financial", document_tool, financial_extract, do_guard=True)
