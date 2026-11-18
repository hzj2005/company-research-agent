"""简报节点（R3 起）：把四栏目段落**拼装**成报告，不再自己调 LLM 抽取。

职责：
- 收集四子图写好的段落（facts 带 source_url、状态、冲突、analysis）；
- 应用人工复核/子图判定的降级栏目（强制拒答 + 清空孤儿引用）；
- 调 `graph/nodes/assemble.py` 统一编号、生成 References、拼 Markdown。

两条硬约定始终成立：
1. 正文行内引用 [n] 与末尾 References **来自同一份** URL 集合；
2. 降级栏目直接输出「该类信息未找到公开依据」，绝不拿低分/无关内容硬凑。

历史说明：S5-B 时本节点有「模板基线 / 结构化输出」双路径，抽取也在这里做；
R3 把抽取下沉进各子图（`graph/agents/extract.py` 的三级降级链），本节点退化为
纯拼装工，`features.structured_output` 因此不再影响报告文本（A/B 中如实标 no_effect）。
"""

from __future__ import annotations

from typing import Any, Callable

from capabilities.briefing import BriefingBackend, make_briefing_backend
from capabilities.conflict import detect_conflicts
from capabilities.structured import extract_section_brief
from config.loader import Settings
from graph.state import ResearchState, Section

Node = Callable[[ResearchState], Any]


def _norm(url: Any) -> str:
    return str(url).rstrip("/")


def _select_documents(
    state: ResearchState, settings: Settings
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int], list[str], dict[str, Any]]:
    """按栏目选正文文档；不在 references 里的文档不进正文（避免无引用结论）。"""
    curated = state.get("curated_data", {})
    references = state.get("references", {})
    degraded = set(state.get("degraded_sections", []))
    limit = settings.report.max_references

    selected: dict[str, list[dict[str, Any]]] = {}
    truncated: dict[str, int] = {}
    for section in settings.graph.sections:
        if section in degraded:
            selected[section] = []
            truncated[section] = 0
            continue
        docs = sorted(
            (
                d
                for d in curated.values()
                if d.get("section") == section and d.get("url") in references
            ),
            key=lambda d: (-float(d.get("score", 0)), str(d.get("url", ""))),
        )
        selected[section] = docs[:limit]
        truncated[section] = len(docs) - len(docs[:limit])

    ordered_urls = sorted(
        {doc["url"] for docs in selected.values() for doc in docs},
        key=lambda u: (-float(references[u].get("score", 0)), u),
    )
    return selected, truncated, ordered_urls, references


def _render_template(
    state: ResearchState,
    settings: Settings,
    selected: dict[str, list[dict[str, Any]]],
    degraded: set[str],
    index: dict[str, int],
) -> tuple[list[str], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """S4 基线实现，逐字保留，供 A/B 关闭开关时对照。"""
    lines: list[str] = [f"# {state['company']} 研究报告", ""]
    briefings: dict[str, dict[str, Any]] = {}
    for heading, section in zip(settings.report.headings, settings.graph.sections):
        lines.extend([f"## {heading}", ""])
        if section in degraded:
            text = settings.graph.degrade.message
            lines.append(f"- {text}")
            briefings[section] = {"status": "degraded", "text": text}
        elif not selected[section]:
            lines.append(f"- {settings.graph.degrade.message}")
            briefings[section] = {"status": "no_evidence", "docs": []}
        else:
            for doc in selected[section]:
                marker = f" [{index[doc['url']]}]" if settings.features.inline_citations else ""
                lines.append(f"- {doc.get('content', '')}{marker}")
            briefings[section] = {
                "status": "ok",
                "docs": [d["url"] for d in selected[section]],
            }
        lines.append("")
    return lines, briefings, []


async def _render_structured(
    state: ResearchState,
    settings: Settings,
    selected: dict[str, list[dict[str, Any]]],
    degraded: set[str],
    norm_index: dict[str, int],
    backend: BriefingBackend,
) -> tuple[list[str], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    lines: list[str] = [f"# {state['company']} 研究报告", ""]
    briefings: dict[str, dict[str, Any]] = {}
    notes: list[dict[str, Any]] = []

    # 串行逐栏目抽取：不用 asyncio.gather（AGENT.md 6.4：并行应由图编排）
    for heading, section in zip(settings.report.headings, settings.graph.sections):
        lines.extend([f"## {heading}", ""])
        if section in degraded:
            text = settings.graph.degrade.message
            lines.append(f"- {text}")
            briefings[section] = {"status": "degraded", "text": text, "conflicts": []}
            lines.append("")
            continue
        if not selected[section]:
            lines.append(f"- {settings.graph.degrade.message}")
            briefings[section] = {"status": "no_evidence", "docs": [], "conflicts": []}
            lines.append("")
            continue

        result = await extract_section_brief(
            backend.chain,
            section=section,
            company=state["company"],
            docs=selected[section],
            settings=settings,
        )
        notes.extend(result.notes)
        if result.brief.degraded or not result.brief.facts:
            text = settings.graph.degrade.message
            lines.append(f"- {text}")
            briefings[section] = {
                "status": "extraction_degraded",
                "text": text,
                "docs": [],
                "conflicts": [],
            }
        else:
            for fact in result.brief.facts:
                marker = (
                    f" [{norm_index[_norm(fact.source_url)]}]"
                    if settings.features.inline_citations
                    else ""
                )
                lines.append(f"- {fact.claim}{marker}")
            # S10：同栏目事实冲突前置 —— 检出后**标注而不是改写**，因为来源本身
            # 可能就有错（真机里分数更高的 CB Insights 反而给了错的成立年份）
            conflicts = (
                detect_conflicts(result.brief.facts)
                if settings.features.conflict_annotation
                else []
            )
            for conflict in conflicts:
                lines.append(f"> {conflict.render(norm_index)}")
            briefings[section] = {
                "status": "ok",
                "docs": [d["url"] for d in selected[section]],
                "facts": [f.model_dump(mode="json") for f in result.brief.facts],
                "conflicts": [
                    {
                        "slot": c.slot,
                        "label": c.label,
                        "values": [
                            {"value": v.display, "source_urls": list(v.source_urls)}
                            for v in c.values
                        ],
                    }
                    for c in conflicts
                ],
            }
        lines.append("")
    return lines, briefings, notes


def make_briefing_node(
    settings: Settings, *, backend: BriefingBackend | None = None
) -> Node:
    """R3 拼装工：读四张子图写好的栏目段落，统一编号 + References 拼成报告。

    不再自己调 LLM 抽取（那会与子图内 extract 重复，抽两次）——
    子图已端到端完成检索→消歧→抽取→判定→写段落，这里只做拼装。
    `backend` 参数保留只为兼容旧调用签名，新路径不使用。
    """

    async def briefing(state: ResearchState) -> dict[str, Any]:
        from graph.nodes.assemble import assemble_report

        # R8：只渲染本次请求的栏目。**未请求 ≠ 证据不足**——不能给未派发的栏目
        # 补拒答话术，否则用户说「只看财务」会收到三段「未找到公开依据」，
        # 看起来像系统坏了，也变相替用户做了他没要的结论。
        requested = [
            s for s in (state.get("requested_sections") or [])
            if s in settings.graph.sections
        ]
        if not requested and state.get("route_meta"):
            # 路由判定需要追问：本次不生成报告，把追问话术作为输出
            clarify = state.get("clarify") or {}
            question = str(clarify.get("question") or "").strip() or (
                "请告诉我公司名，以及想了解哪几块。"
            )
            return {
                "report": question,
                "briefings": {},
                "review_notes": [
                    {
                        "node": "briefing",
                        "status": "clarify",
                        "kind": clarify.get("kind"),
                        "question": question,
                    }
                ],
            }
        if not requested:
            requested = list(settings.graph.sections)

        # 收集本次请求的段落产物
        sections: list[dict[str, Any]] = []
        for key in requested:
            paragraph = state.get(f"{key}_paragraph") or {}
            if paragraph:
                sections.append(paragraph)
            else:
                # 子图没产出段落（异常/未派发）→ 降级段，写拒答
                sections.append(
                    {"key": key, "section": key, "status": "degraded",
                     "facts": [], "conflicts": [], "references": {}}
                )

        # 人工复核/子图判定降级的栏目 → 强制该段走拒答话术
        # （复核 reject 写 degraded_sections 后，报告必须真的不输出该栏目）
        degraded = set(state.get("degraded_sections") or [])
        for sec in sections:
            if sec.get("key") in degraded:
                sec["status"] = "degraded"
                sec["facts"] = []
                sec["conflicts"] = []
                sec["references"] = {}  # 全拒答时不得留孤儿引用

        report, briefings = assemble_report(state["company"], sections, settings)

        # 兼容旧断言：briefing note 最后一条，带 referenced 计数
        all_urls = {
            str(f.get("source_url", ""))
            for sec in sections
            for f in sec.get("facts", [])
            if f.get("source_url")
        }
        truncated_per_section = {
            sec["key"]: sec["truncated"]
            for sec in sections
            if sec.get("truncated")
        }
        base_note = {
            "node": "briefing",
            "referenced": len(all_urls),
            "truncated_per_section": truncated_per_section,
        }
        result: dict[str, Any] = {
            "report": report,
            "briefings": briefings,
            "review_notes": [base_note],
        }
        # 后处理：默认关闭，读拼装用的 facts 做行业/新闻/财务专项加工
        if settings.features.postprocess:
            from datetime import date

            from capabilities.postprocess import postprocess_from_briefing

            result["postprocess"] = postprocess_from_briefing(
                briefings,
                company=state["company"],
                reference_year=date.today().year,
                source_docs=None,  # R3 段落只带 url，无原文 content；财务数字保真留 R4
            )
        return result

    return briefing
