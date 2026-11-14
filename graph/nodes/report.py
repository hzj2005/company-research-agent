"""简报生成节点（S5-B：模板基线 / 结构化输出双路径）。

两条硬约定始终成立：
1. 正文行内引用 [n] 与末尾 References **来自同一份** `state["references"]`；
2. 降级栏目直接输出「该类信息未找到公开依据」，绝不拿低分/无关内容硬凑。

`features.structured_output`：
- **off**：S4 模板路径，报告与 S4 **逐字一致**（A/B 基线）。
- **on**：`prompt | with_structured_output(SectionBrief)` 真跑 LCEL；fixture 模式
  后端是本地 mock HTTP 的确定性 stub（见 `capabilities/briefing.py`），**不是模型能力**。
  每条 Fact 的 `source_url` 必须落在本次文档集合里，否则由抽取层剔除并留痕。

结构化抽取失败属于「生成失败」，与 evidence_check 判定的「检索证据不足」是两类降级：
只在报告与 `briefings` 里拒答、在 `review_notes` 留痕，不改写 `degraded_sections`。
"""

from __future__ import annotations

from typing import Any, Callable

from capabilities.briefing import BriefingBackend, make_briefing_backend
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
    lines: list[str] = [f"# {state['company']} Research Report", ""]
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
    lines: list[str] = [f"# {state['company']} Research Report", ""]
    briefings: dict[str, dict[str, Any]] = {}
    notes: list[dict[str, Any]] = []

    # 串行逐栏目抽取：不用 asyncio.gather（AGENT.md 6.4：并行应由图编排）
    for heading, section in zip(settings.report.headings, settings.graph.sections):
        lines.extend([f"## {heading}", ""])
        if section in degraded:
            text = settings.graph.degrade.message
            lines.append(f"- {text}")
            briefings[section] = {"status": "degraded", "text": text}
            lines.append("")
            continue
        if not selected[section]:
            lines.append(f"- {settings.graph.degrade.message}")
            briefings[section] = {"status": "no_evidence", "docs": []}
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
            }
        else:
            for fact in result.brief.facts:
                marker = (
                    f" [{norm_index[_norm(fact.source_url)]}]"
                    if settings.features.inline_citations
                    else ""
                )
                lines.append(f"- {fact.claim}{marker}")
            briefings[section] = {
                "status": "ok",
                "docs": [d["url"] for d in selected[section]],
                "facts": [f.model_dump(mode="json") for f in result.brief.facts],
            }
        lines.append("")
    return lines, briefings, notes


def make_briefing_node(
    settings: Settings, *, backend: BriefingBackend | None = None
) -> Node:
    active_backend = backend
    if settings.features.structured_output and active_backend is None:
        active_backend = make_briefing_backend(settings)

    async def briefing(state: ResearchState) -> dict[str, Any]:
        selected, truncated, ordered_urls, references = _select_documents(state, settings)
        degraded = set(state.get("degraded_sections", []))
        index = {url: i + 1 for i, url in enumerate(ordered_urls)}
        norm_index = {_norm(url): n for url, n in index.items()}

        if settings.features.structured_output and active_backend is not None:
            lines, briefings, notes = await _render_structured(
                state, settings, selected, degraded, norm_index, active_backend
            )
        else:
            lines, briefings, notes = _render_template(
                state, settings, selected, degraded, index
            )

        lines.extend(["## References", ""])
        for url in ordered_urls:
            meta = references[url]
            lines.append(f"[{index[url]}] {meta.get('title', '')} — {url}")

        report = "\n".join(lines).rstrip() + "\n"
        # briefing note 必须是最后一条：tests/test_report_citations.py 依赖它取截断信息
        base_note = {
            "node": "briefing",
            "referenced": len(ordered_urls),
            "truncated_per_section": truncated,
        }
        return {
            "report": report,
            "briefings": briefings,
            "review_notes": [*notes, base_note],
        }

    return briefing
