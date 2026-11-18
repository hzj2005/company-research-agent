"""补账回归（R3 迁移版）：正文结论与 References 一一对应，无孤儿编号。

R3：max_references 截断下沉到子图 pipeline，briefing 拼装器统一编号。
验证：
- 超过上限时每栏只保留 max_references 条，且都带 [n]；
- References 编号连续、正文编号都能解析；
- 截断数留痕（truncated_per_section）；
- 降级栏目不产生孤儿引用；引用开关关闭仍渲染。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from langchain_core.tools import tool

from config.loader import get_settings
from graph.agents.company.graph import build_company_subgraph
from graph.nodes.assemble import assemble_report


def _many_docs(n: int) -> dict[str, list[dict[str, Any]]]:
    return {
        "company": [
            {"url": f"https://example.org/{i}", "title": f"来源 {i}",
             "content": f"事实 {i}", "score": 0.9, "section": "company"}
            for i in range(n)
        ]
    }


def _pipeline_output(n: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    s = get_settings()

    @tool
    async def fetch(
        company: str,
        sections: list[str],
        round_no: int,
        queries: list[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """返回构造的多篇文档。"""
        return _many_docs(n)

    graph = build_company_subgraph(s, fetch)
    out = asyncio.run(graph.ainvoke({"company": "X", "round_no": 0}))
    return out["company_paragraph"], out["review_notes"]


def test_every_factual_bullet_has_inline_citation() -> None:
    s = get_settings()
    para, _ = _pipeline_output(12)
    assert len(para["facts"]) == s.report.max_references, "每栏结论数应受上限约束"
    report, _ = assemble_report("X", [{**para, "key": "company"}], s)
    facts = [ln for ln in report.splitlines() if ln.startswith("- 事实")]
    assert all(re.search(r"\[\d+\]$", ln) for ln in facts), "每条事实必须带 [n]"


def test_reference_numbers_are_dense_and_resolvable() -> None:
    s = get_settings()
    para, _ = _pipeline_output(12)
    report, _ = assemble_report("X", [{**para, "key": "company"}], s)
    used = [int(n) for n in re.findall(r"- 事实 \d+ \[(\d+)\]", report)]
    refs = [int(n) for n in re.findall(r"^\[(\d+)\] ", report, flags=re.M)]
    assert used and set(used) <= set(refs), "正文编号必须能在 References 找到"
    assert refs == list(range(1, len(refs) + 1)), "编号必须连续无空洞"


def test_truncated_documents_are_recorded() -> None:
    para, notes = _pipeline_output(12)
    assert para["truncated"] == 2, "超出的 2 条应记进截断数"
    assert any(n.get("node") == "truncate" and n["dropped"] == 2 for n in notes)


def test_degraded_section_emits_no_orphan_reference() -> None:
    s = get_settings()
    para = {"key": "company", "status": "degraded", "facts": [],
            "references": {}, "conflicts": [], "truncated": 0}
    report, _ = assemble_report("X", [para], s)
    assert "该类信息未找到公开依据" in report
    assert "[1]" not in report, "降级栏目不得留孤儿引用"


def test_inline_citations_switch_off_still_renders() -> None:
    s = get_settings().model_copy(deep=True)
    s.features.inline_citations = False
    para, _ = _pipeline_output(3)
    report, _ = assemble_report("X", [{**para, "key": "company"}], s)
    assert "事实 0" in report and "## References" in report
