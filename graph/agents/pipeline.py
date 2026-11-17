"""R3 子图自闭环执行器：检索 → 消歧 → extract(栏目自己实现) → 判定 → 返工 → 写段落。

设计（用户 2026-11-17 决策）：
- 每个子图端到端负责一个栏目，消歧与证据判定都在子图内（主图移除 curate/evidence_check）；
- 证据不足时子图**自己返工**（≤2 轮），Orchestrator 不协调回退；
- extract 由每个栏目传入自己的实现（各栏目独立），本引擎只做编排；
- 产出「栏目段落」= facts + 状态 + 冲突标注，**不带编号**（编号交给报告层）。

复用现有能力：EntityGuard（消歧）、extract_section_brief（抽取，三级降级在 extract 层）。
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from config.loader import Settings
from capabilities.entity_guard import EntityGuard
from graph.agents.paragraph import make_paragraph

logger = logging.getLogger(__name__)

# extract 函数签名：(company, section, docs, settings) -> (facts: list[dict], status: str, notes: list)
ExtractFn = Callable[[str, str, list[dict[str, Any]], Settings], Awaitable[tuple[list[dict[str, Any]], str, list[dict[str, Any]]]]]


def make_pipeline_node(
    settings: Settings,
    section: str,
    document_tool: Any,
    extract_fn: ExtractFn,
    *,
    do_guard: bool = False,
) -> Any:
    """构造一个子图自闭环节点。

    `do_guard=True` 时先做实体消歧（company/financial 用），其他栏目跳过。
    `extract_fn` 是栏目自己的抽取实现（LLM + 降级）。
    """
    min_docs = settings.graph.evidence.min_docs_per_section
    max_retry = settings.graph.max_retry

    async def pipeline(state: dict[str, Any]) -> dict[str, Any]:
        company = state["company"]
        round_no = int(state.get("round_no", 0))
        all_notes: list[dict[str, Any]] = []
        facts: list[dict[str, Any]] = []
        references: dict[str, dict[str, Any]] = {}
        status = "insufficient"

        # 子图内自闭环：当前轮不够且未超上限 → 自己返工重搜
        for attempt in range(round_no, max_retry + 1):
            raw = await document_tool.ainvoke(
                {"company": company, "sections": [section], "round_no": attempt}
            )
            docs = [dict(d) for d in raw.get(section, [])]

            # ① 消歧（子图内，company/financial）
            if do_guard and settings.features.entity_guard:
                guard = EntityGuard(company, enabled=True)
                result = guard.filter_docs(docs)
                docs = [dict(d) for d in result.kept]
                if result.rejected or result.all_rejected_fallback:
                    all_notes.append(
                        {
                            "node": "entity_guard",
                            "section": section,
                            "rejected": result.rejected,
                            "all_rejected_fallback": result.all_rejected_fallback,
                        }
                    )

            # ② references（消歧后的文档，供报告编号用）
            references = {
                str(d["url"]): {
                    "title": d.get("title", ""),
                    "score": float(d.get("score", 0) or 0),
                }
                for d in docs
                if d.get("url")
            }

            # ③ extract（栏目自己的实现：LLM + 降级）
            facts, extract_status, notes = await extract_fn(company, section, docs, settings)
            all_notes.extend(notes)

            # ④ 证据判定：够 → 写段落退出；不够 → 返工
            if len(facts) >= min_docs or extract_status == "no_retry":
                status = "ok" if facts else "degraded"
                break
            all_notes.append(
                {
                    "node": "evidence",
                    "section": section,
                    "attempt": attempt,
                    "facts": len(facts),
                    "needed": min_docs,
                    "verdict": "insufficient",
                }
            )
            logger.info("%s 第 %d 轮不足（%d/%d），子图内返工", section, attempt, len(facts), min_docs)
        else:
            status = "degraded"

        # ⑤ 写段落（facts 带 source_url，不带编号）
        paragraph = make_paragraph(
            section, section, _to_facts(facts), settings,
            degraded=(status == "degraded"),
            references=references,
        )
        return {
            f"{section}_paragraph": paragraph,
            "review_notes": [
                *all_notes,
                {
                    "node": "pipeline",
                    "section": section,
                    "status": status,
                    "rounds": max(round_no, 0) + 1,
                    "facts": len(facts),
                },
            ],
        }

    return pipeline


def _to_facts(facts: list[dict[str, Any]]) -> list[Any]:
    """dict → Fact 对象（make_paragraph 需要 Fact）。"""
    from graph.contracts import Fact

    out: list[Any] = []
    for f in facts:
        try:
            out.append(
                Fact(
                    claim=str(f["claim"]),
                    source_url=f["source_url"],
                    confidence=float(f.get("confidence", 0.0)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out
