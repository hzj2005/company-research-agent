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
# analyzer 签名：(facts 带 _round, company, settings, source_texts) ->
#   {"conflicts": [...], "analysis": {...}}
# source_texts = url -> 原文 content（数字保真校验需要，如财务金额是否真在原文里）
AnalyzerFn = Callable[[list[dict[str, Any]], str, Settings, dict[str, str]], dict[str, Any]]


def make_pipeline_node(
    settings: Settings,
    section: str,
    document_tool: Any,
    extract_fn: ExtractFn,
    *,
    do_guard: bool = False,
    analyzer: AnalyzerFn | None = None,
) -> Any:
    """构造一个子图自闭环节点。

    `do_guard=True` 时先做实体消歧（company/financial 用），其他栏目跳过。
    `extract_fn` 是栏目自己的抽取实现（LLM + 降级）。
    `analyzer` 是栏目专属加工钩子（R4），产出结构化冲突等，**不带编号**。
    """
    min_docs = settings.graph.evidence.min_docs_per_section
    # 关闭自纠正时不允许返工（旧架构 rewrite_query 的开关语义下沉子图）
    max_retry = settings.graph.max_retry if settings.features.self_correction else 0
    # 旧 curate 的相关性阈值过滤也搬进子图：低分无关文档不进段落。
    # 漏搬这块会让 empty case 的低分文档（score 0.12）被抽成 fact → 误报有证据。
    min_score = settings.graph.evidence.min_relevance_score
    require_url = settings.graph.evidence.require_source_url
    # 每栏目事实数上限（旧 briefing 的 max_references 截断下沉子图）
    max_facts = settings.report.max_references

    async def pipeline(state: dict[str, Any]) -> dict[str, Any]:
        company = state["company"]
        round_no = int(state.get("round_no", 0))
        all_notes: list[dict[str, Any]] = []
        facts: list[dict[str, Any]] = []
        references: dict[str, dict[str, Any]] = {}
        source_texts: dict[str, str] = {}
        processed_urls: set[str] = set()
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
                    if d.get("content"):
                        source_texts[str(d["url"])] = str(d["content"])

            # ③ extract（栏目自己的实现：LLM + 降级）
            # 跨轮只对"未处理过的文档"抽取：避免同一文档重复抽；
            # 但同一文档抽出的多条事实必须全部保留（R3 曾按 url 去重，会丢同文档多事实）
            new_docs = [d for d in docs if str(d.get("url", "")) not in processed_urls]
            round_facts, extract_status, notes = await extract_fn(
                company, section, new_docs, settings
            )
            all_notes.extend(notes)
            for f in round_facts:
                # 记轮次（_round）：冲突判定要求"同轮才判"，跨轮视为陆续补充
                facts.append({**f, "_round": attempt})
            processed_urls.update(str(d.get("url", "")) for d in new_docs)

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

        # ④b 每栏结论数截断（防正文事实多于 References 造成孤儿编号）
        truncated = max(0, len(facts) - max_facts)
        if truncated:
            all_notes.append(
                {"node": "truncate", "section": section,
                 "kept": max_facts, "dropped": truncated}
            )
            facts = facts[:max_facts]

        # ⑤ 栏目专属加工（R4）：冲突标注 + 结构化分析产物
        conflicts: list[dict[str, Any]] = []
        analysis: dict[str, Any] = {}
        if analyzer is not None and status == "ok":
            try:
                res = analyzer(facts, company, settings, source_texts) or {}
                # 兼容旧形态：直接返回 list 视为 conflicts
                if isinstance(res, list):
                    conflicts = res
                else:
                    conflicts = res.get("conflicts", []) or []
                    analysis = res.get("analysis", {}) or {}
                if analysis:
                    all_notes.append(
                        {"node": "analyzer", "section": section,
                         "analysis_keys": sorted(analysis.keys())}
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s analyzer 失败，跳过：%s", section, exc)
                all_notes.append(
                    {"node": "analyzer", "section": section, "status": "failed",
                     "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
                )

        # ⑥ 写段落（facts 带 source_url，不带编号）
        paragraph = make_paragraph(
            section, section, _to_facts(facts),
            settings=settings,
            degraded=(status == "degraded"),
            conflicts=conflicts,
            references=references,
        )
        # degraded 标记并行分支各自追加（append_unique reducer 合并），
        # 不依赖 arbitrate 读汇合状态（Send 分支输出对汇合节点不可见）
        degraded_marker = [section] if status in ("degraded", "no_evidence") else []
        # retry_count 同样由并行分支各自写（merge_mapping reducer 合并），
        # 供评测按旧契约读子图内返工轮次
        # 返工轮次 = 实际多跑的轮数（与有没有 facts 无关；empty case 也记满）
        used_round = max(attempt - round_no, 0)
        paragraph["truncated"] = truncated
        if analysis:
            paragraph["analysis"] = analysis
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
