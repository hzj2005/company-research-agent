"""R7：子图编排原语（共用），与「编排」分离。

R3 的做法是一个 228 行的 `make_pipeline_node` 统一四个栏目，结果四个子图拓扑
完全相同——只在 prompt 和 analyzer 上有差别。R7 把「检索 / 过滤 / 抽取 / 判定 /
写段落」拆成原语（本模块），**节点顺序由各栏目自己的 graph.py 决定**：

- company:   retrieve → guard → extract → judge → conflict → write
- financial: retrieve → bind_subject → extract → verify_amount → judge → timeline → write
- news:      retrieve → guard → filter_entity → extract → judge → freshness → write
- industry:  retrieve → guard → extract → judge → competitor_scan ⇄ competitor_fetch → matrix → write

共用的是原语实现，不是流程。这样既不必把同一段逻辑抄四份，也不会把四种不同
任务的认知过程抹平。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from capabilities.entity_guard import EntityGuard
from config.loader import Settings
from graph.agents.paragraph import make_paragraph

logger = logging.getLogger(__name__)

ExtractFn = Callable[
    [str, str, list[dict[str, Any]], Settings],
    Awaitable[tuple[list[dict[str, Any]], str, list[dict[str, Any]]]],
]
AnalyzerFn = Callable[
    [list[dict[str, Any]], str, Settings, dict[str, str]], dict[str, Any]
]


@dataclass(frozen=True)
class Limits:
    """一次子图运行的硬边界，全部来自配置，不在节点里写魔法数。"""

    min_docs: int
    max_retry: int
    min_score: float
    require_url: bool
    max_facts: int


def limits_from(settings: Settings) -> Limits:
    return Limits(
        min_docs=settings.graph.evidence.min_docs_per_section,
        # 关闭自纠正时不允许返工（旧 rewrite_query 开关语义下沉子图）
        max_retry=settings.graph.max_retry if settings.features.self_correction else 0,
        min_score=settings.graph.evidence.min_relevance_score,
        require_url=settings.graph.evidence.require_source_url,
        max_facts=settings.report.max_references,
    )


def to_facts(facts: list[dict[str, Any]]) -> list[Any]:
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


def _append_notes(state: dict[str, Any], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [*(state.get("notes") or []), *extra]


# ---------------------------------------------------------------- 节点：检索


def make_retrieve_node(section: str, tool: Any) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    """检索节点。`attempt` 由本节点维护：首轮取 round_no，返工时 +1。"""

    async def retrieve(state: dict[str, Any]) -> dict[str, Any]:
        # next_attempt 由判定节点在返工时写入；首轮没有该字段则用 round_no
        attempt = int(state.get("next_attempt", state.get("round_no", 0) or 0))
        payload = {
            "company": state["company"],
            "sections": [section],
            "round_no": attempt,
        }
        raw = await tool.ainvoke(payload)
        docs = [dict(d) for d in (raw.get(section) or [])]
        return {"docs": docs, "attempt": attempt}

    return retrieve


def make_guard_node(
    section: str, settings: Settings, limits: Limits, *, entity_guard: bool
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """消歧 + 相关性过滤。

    `entity_guard=True` 时才做同名实体剔除（company/financial）。相关性阈值过滤
    对所有栏目都做——低分无关文档混进抽取会被编成事实（R3 曾漏搬导致 empty case
    误报有证据）。
    """

    def guard(state: dict[str, Any]) -> dict[str, Any]:
        docs = [dict(d) for d in (state.get("docs") or [])]
        notes: list[dict[str, Any]] = []

        if entity_guard and settings.features.entity_guard:
            result = EntityGuard(state["company"], enabled=True).filter_docs(docs)
            docs = [dict(d) for d in result.kept]
            if result.rejected or result.all_rejected_fallback:
                notes.append(
                    {
                        "node": "entity_guard",
                        "section": section,
                        "rejected": result.rejected,
                        "all_rejected_fallback": result.all_rejected_fallback,
                    }
                )

        before = len(docs)
        docs = [
            d
            for d in docs
            if float(d.get("score", 0) or 0) >= limits.min_score
            and (not limits.require_url or d.get("url"))
        ]
        if before != len(docs):
            notes.append(
                {
                    "node": "relevance_filter",
                    "section": section,
                    "dropped": before - len(docs),
                    "threshold": limits.min_score,
                }
            )

        return {"docs": docs, "notes": _append_notes(state, notes)}

    return guard


# ---------------------------------------------------------------- 节点：抽取


def make_extract_node(
    section: str, extract_fn: ExtractFn, settings: Settings
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    """抽取节点：只抽本轮没处理过的文档，事实跨轮累积。

    跨轮"按文档去重"而不是按 URL 去重——同一文档抽出的多条事实必须全保留
    （R3 曾按 url 去重，静默丢掉同文档的多条事实）。
    """

    async def extract(state: dict[str, Any]) -> dict[str, Any]:
        docs = [dict(d) for d in (state.get("docs") or [])]
        references = dict(state.get("references") or {})
        source_texts = dict(state.get("source_texts") or {})
        for d in docs:
            url = d.get("url")
            if not url:
                continue
            references[str(url)] = {
                "title": d.get("title", ""),
                "score": float(d.get("score", 0) or 0),
            }
            if d.get("content"):
                source_texts[str(url)] = str(d["content"])

        processed = set(state.get("processed_urls") or [])
        new_docs = [d for d in docs if str(d.get("url", "")) not in processed]

        attempt = int(state.get("attempt", 0) or 0)
        round_facts, extract_status, notes = await extract_fn(
            state["company"], section, new_docs, settings
        )

        facts = list(state.get("facts") or [])
        facts.extend({**f, "_round": attempt} for f in round_facts)

        return {
            "facts": facts,
            "extract_status": extract_status,
            "processed_urls": sorted(processed | {str(d.get("url", "")) for d in new_docs}),
            "references": references,
            "source_texts": source_texts,
            "notes": _append_notes(state, notes),
        }

    return extract


# ---------------------------------------------------------------- 节点：判定


def make_judge_node(
    section: str, limits: Limits
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """证据判定 + 路由决策。

    判定看的是**事实条数是否达到门槛**，不问模型「够不够」。三种结局：
    - `ok`：达标（或有 facts 且已无法再返工）
    - `degraded`：轮次用尽仍不足，或抽不出任何事实
    - 继续返工：`status` 留空，路由函数据此回边到检索
    """

    def judge(state: dict[str, Any]) -> dict[str, Any]:
        facts = state.get("facts") or []
        attempt = int(state.get("attempt", 0) or 0)
        round_no = int(state.get("round_no", 0) or 0)
        count = len(facts)

        if count >= limits.min_docs or state.get("extract_status") == "no_retry":
            verdict = "ok" if count else "degraded"
        elif attempt + 1 <= limits.max_retry:
            return {
                "status": "",
                "next_attempt": attempt + 1,
                "notes": _append_notes(
                    state,
                    [
                        {
                            "node": "evidence",
                            "section": section,
                            "attempt": attempt,
                            "facts": count,
                            "needed": limits.min_docs,
                            "verdict": "insufficient",
                        }
                    ],
                ),
            }
        else:
            verdict = "degraded"

        if verdict == "degraded" and count:
            logger.info("%s 轮次用尽仅 %d 条（门槛 %d），按降级处理", section, count, limits.min_docs)

        # 只有「判定不足 → 决定返工」才留痕；终局状态由 write 节点的 pipeline note 承载，
        # 避免每次判定都写一条（原 R3 语义）。
        return {
            "status": verdict,
            "used_round": max(attempt - round_no, 0),
        }

    return judge


def route_after_judge(state: dict[str, Any]) -> str:
    """判定后路由：结论未定时回边返工，否则往下走。"""
    return "retry" if state.get("status", "") == "" else "continue"


# ---------------------------------------------------------------- 节点：加工


def make_analyzer_node(
    section: str,
    analyzer: AnalyzerFn,
    settings: Settings,
    *,
    extra: Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    """栏目专属加工节点（冲突标注 / 时间线 / 竞品矩阵 / 时效去重）。

    只在 `status == ok` 时跑：已经拒答的栏目没有事实可加工，硬算就是编造。
    `extra` 供需要额外数据的栏目（如财务要原文、行业要补检索）注入异步步骤。
    """

    async def analyze(state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") != "ok":
            return {}
        facts = state.get("facts") or []
        source_texts = state.get("source_texts") or {}
        payload: dict[str, Any] = {}
        if extra is not None:
            payload = await extra(state, {}) or {}

        try:
            result = analyzer(facts, state["company"], settings, source_texts) or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s analyzer 失败，跳过：%s", section, exc)
            return {
                "notes": _append_notes(
                    state,
                    [
                        {
                            "node": "analyzer",
                            "section": section,
                            "status": "failed",
                            "error": f"{type(exc).__name__}: {str(exc)[:120]}",
                        }
                    ],
                ),
                **payload,
            }

        if isinstance(result, list):
            conflicts, analysis = result, {}
        else:
            conflicts = result.get("conflicts", []) or []
            analysis = result.get("analysis", {}) or {}

        notes: list[dict[str, Any]] = []
        if analysis:
            notes.append(
                {
                    "node": "analyzer",
                    "section": section,
                    "analysis_keys": sorted(analysis.keys()),
                }
            )
        return {
            "conflicts": conflicts,
            "analysis": analysis,
            "notes": _append_notes(state, notes),
            **payload,
        }

    return analyze


# ---------------------------------------------------------------- 节点：写段落


def make_write_node(
    section: str, settings: Settings, limits: Limits
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """写段落 + 产出子图对外字段（段落 / 降级标记 / 返工轮次 / 留痕）。

    编号不在这里分配——子图只写 claim + source_url，编号归报告层。
    """

    def write(state: dict[str, Any]) -> dict[str, Any]:
        facts = list(state.get("facts") or [])
        status = state.get("status") or "degraded"
        used_round = int(state.get("used_round", 0) or 0)

        truncated = max(0, len(facts) - limits.max_facts)
        if truncated:
            facts = facts[: limits.max_facts]

        paragraph = make_paragraph(
            section,
            section,
            to_facts(facts),
            settings=settings,
            degraded=(status == "degraded"),
            conflicts=state.get("conflicts") or [],
            references=state.get("references") or {},
        )
        paragraph["truncated"] = truncated
        # 前置独立节点产出的分析（如财务的金额核对）覆盖 analyzer 的同名键，
        # 保证「独立节点」是唯一来源，不是两份结果并存
        analysis = dict(state.get("analysis") or {})
        analysis.update(state.get("analysis_extra") or {})
        if analysis and status == "ok":
            paragraph["analysis"] = analysis
        binding = state.get("subject_binding") or {}
        if binding:
            paragraph["subject_binding"] = binding

        notes: list[dict[str, Any]] = []
        if truncated:
            notes.append(
                {
                    "node": "truncate",
                    "section": section,
                    "kept": limits.max_facts,
                    "dropped": truncated,
                }
            )
        notes.append(
            {
                "node": "pipeline",
                "section": section,
                "status": status,
                "rounds": used_round + 1,
                "facts": len(facts),
            }
        )

        all_notes = _append_notes(state, notes)
        return {
            f"{section}_paragraph": paragraph,
            "degraded_sections": [section] if status in ("degraded", "no_evidence") else [],
            "retry_count": {section: used_round} if used_round else {},
            "notes": all_notes,
            # 子图出口：中间态 notes 搬到父图可见的 review_notes
            "review_notes": all_notes,
        }

    return write
