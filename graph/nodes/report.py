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
    async def briefing(state: ResearchState) -> dict[str, Any]:
        curated = state.get("curated_data", {})
        references = state.get("references", {})
        degraded = set(state.get("degraded_sections", []))

        ordered = sorted(
            references.items(),
            key=lambda kv: (-float(kv[1].get("score", 0)), kv[0]),
        )[: settings.report.max_references]
        index = {url: i + 1 for i, (url, _) in enumerate(ordered)}

        lines: list[str] = [f"# {state['company']} Research Report", ""]
        briefings: dict[str, dict[str, Any]] = {}

        # headings 前四项对应四个栏目，第五项是 References
        for heading, section in zip(settings.report.headings, settings.graph.sections):
            lines.extend([f"## {heading}", ""])
            if section in degraded:
                text = (
                    settings.graph.degrade.message
                    if settings.graph.degrade.enabled
                    else "（无可用公开资料）"
                )
                lines.append(f"- {text}")
                briefings[section] = {"status": "degraded", "text": text}
            else:
                docs = sorted(
                    (d for d in curated.values() if d.get("section") == section),
                    key=lambda d: -float(d.get("score", 0)),
                )
                if not docs:
                    lines.append(f"- {settings.graph.degrade.message}")
                    briefings[section] = {"status": "no_evidence", "docs": []}
                else:
                    for doc in docs:
                        url = doc["url"]
                        marker = (
                            f" [{index[url]}]"
                            if settings.features.inline_citations and url in index
                            else ""
                        )
                        lines.append(f"- {doc.get('content', '')}{marker}")
                    briefings[section] = {
                        "status": "ok",
                        "docs": [d["url"] for d in docs],
                    }
            lines.append("")

        lines.extend(["## References", ""])
        for url, meta in ordered:
            lines.append(f"[{index[url]}] {meta.get('title', '')} — {url}")

        report = "\n".join(lines).rstrip() + "\n"
        return {"report": report, "briefings": briefings}

    return briefing
