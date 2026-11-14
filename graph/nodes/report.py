"""简报生成节点（S3 fixture 版）。

S5 会把这里换成 `with_structured_output` 的 LLM 生成，但两条约定现在就成立：
1. 正文行内引用 [n] 与末尾 References **来自同一份** `state["references"]`；
2. 降级栏目直接输出配置里的「未找到公开依据」，绝不拿低分/无关内容硬凑。
"""

from __future__ import annotations

from typing import Any, Callable

from config.loader import Settings
from graph.state import ResearchState

Node = Callable[[ResearchState], Any]


def make_briefing_node(settings: Settings) -> Node:
    """生成简报；正文结论与末尾 References 共用同一份「选中文档」。

    旧实现只按 max_references 截断引用表，正文却遍历全部文档，文档数一多就会出现
    「有结论、没有 [n]」的孤儿事实。现在先按栏目选出正文要用的文档，再统一编号，
    保证每条事实性结论都能对回 References 中的一条来源（AGENT.md 第 8 条）。
    """
    async def briefing(state: ResearchState) -> dict[str, Any]:
        curated = state.get("curated_data", {})
        references = state.get("references", {})
        degraded = set(state.get("degraded_sections", []))
        limit = settings.report.max_references

        # 先选文档：来源字典里查不到的文档不进正文，避免无引用结论
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

        # 编号池 = 所有被选中的 URL；按相关度统一排序后分配 [1], [2], ...
        ordered_urls = sorted(
            {doc["url"] for docs in selected.values() for doc in docs},
            key=lambda u: (-float(references[u].get("score", 0)), u),
        )
        index = {url: i + 1 for i, url in enumerate(ordered_urls)}

        lines: list[str] = [f"# {state['company']} Research Report", ""]
        briefings: dict[str, dict[str, Any]] = {}

        # headings 前四项对应四个栏目，第五项是 References
        for heading, section in zip(settings.report.headings, settings.graph.sections):
            lines.extend([f"## {heading}", ""])
            if section in degraded:
                # S4：降级不可关闭，话术只由配置提供
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

        lines.extend(["## References", ""])
        for url in ordered_urls:
            meta = references[url]
            lines.append(f"[{index[url]}] {meta.get('title', '')} — {url}")

        report = "\n".join(lines).rstrip() + "\n"
        return {
            "report": report,
            "briefings": briefings,
            "review_notes": [
                {
                    "node": "briefing",
                    "referenced": len(ordered_urls),
                    "truncated_per_section": truncated,
                }
            ],
        }

    return briefing
