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
    # 关闭自纠正时不允许返工（旧架构 rewrite_query 的开关语义下沉子图）
    max_retry = settings.graph.max_retry if settings.features.self_correction else 0
    # 旧 curate 的相关性阈值过滤也搬进子图：低分无关文档不进段落。
    # 漏搬这块会让 empty case 的低分文档（score 0.12）被抽成 fact → 误报有证据。
    min_score = settings.graph.evidence.min_relevance_score
    require_url = settings.graph.evidence.require_source_url

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

            # ①b 相关性阈值过滤（旧 curate 的职责，R3 下沉子图）
            before = len(docs)
            docs = [
                d for d in docs
                if float(d.get("score", 0) or 0) >= min_score
                and (not require_url or d.get("url"))
            ]
            if before != len(docs):
                all_notes.append(
                    {"node": "relevance_filter", "section": section,
                     "dropped": before - len(docs), "threshold": min_score}
                )

            # ② references（跨轮累积，按 URL 去重；回退重搜保留首轮证据）
            for d in docs:
                if d.get("url"):
                    references[str(d["url"])] = {
                        "title": d.get("title", ""),
                        "score": float(d.get("score", 0) or 0),
                    }

            # ③ extract（栏目自己的实现：LLM + 降级）
            round_facts, extract_status, notes = await extract_fn(company, section, docs, settings)
            all_notes.extend(notes)
            # 跨轮累积 facts（按 source_url 去重）：首轮那 1 条也要留到最终段落，
            # 否则 sparse case 回退后丢首轮证据（R3 实测 sparse:company:2 踩到）
            seen_urls = {f.get("source_url") for f in facts}
            for f in round_facts:
                if f.get("source_url") not in seen_urls:
                    facts.append(f)
                    seen_urls.add(f.get("source_url"))

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
            section, section, _to_facts(facts),
            settings=settings,
            degraded=(status == "degraded"),
            references=references,
        )
        # degraded 标记并行分支各自追加（append_unique reducer 合并），
        # 不依赖 arbitrate 读汇合状态（Send 分支输出对汇合节点不可见）
        degraded_marker = [section] if status in ("degraded", "no_evidence") else []
        # retry_count 同样由并行分支各自写（merge_mapping reducer 合并），
        # 供评测按旧契约读子图内返工轮次
        # 返工轮次 = 实际多跑的轮数（与有没有 facts 无关；empty case 也记满）
        used_round = max(attempt - round_no, 0)
        return {
            f"{section}_paragraph": paragraph,
            "degraded_sections": degraded_marker,
            "retry_count": {section: used_round} if used_round else {},
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
