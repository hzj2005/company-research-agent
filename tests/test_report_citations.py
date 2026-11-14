"""补账回归：正文结论与 References 必须一一对应，不允许孤儿事实。

起因：旧实现按 max_references 截断引用表、正文却遍历全部文档，
实测 12 篇合格文档时会出现 2 条「有结论、没有 [n]」的事实。
fixture 只有 8~9 篇所以一直没暴露，接真实检索必现。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from config.loader import Settings, get_settings
from graph.nodes.report import make_briefing_node


def _state(n_docs: int, *, degraded: list[str] | None = None) -> dict[str, Any]:
    urls = [f"https://example.org/{i}" for i in range(n_docs)]
    return {
        "company": "X",
        "curated_data": {
            u: {"url": u, "content": f"事实 {i}", "score": 0.9, "section": "company"}
            for i, u in enumerate(urls)
        },
        "references": {
            u: {"title": f"来源 {i}", "score": 0.9, "used_by": ["company"]}
            for i, u in enumerate(urls)
        },
        "degraded_sections": degraded or [],
    }


def _render(state: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    return asyncio.run(make_briefing_node(settings or get_settings())(state))


def test_every_factual_bullet_has_inline_citation() -> None:
    """故意超过 max_references：不能有不带 [n] 的事实性结论。"""
    out = _render(_state(12))
    facts = [ln for ln in out["report"].splitlines() if ln.startswith("- 事实")]
    assert len(facts) == get_settings().report.max_references, "每栏目结论数应受配置约束"
    assert all(re.search(r"\[\d+\]$", ln) for ln in facts), "每条事实性结论必须带 [n]"


def test_reference_numbers_are_dense_and_resolvable() -> None:
    report = _render(_state(12))["report"]
    used = [int(n) for n in re.findall(r"- 事实 \d+ \[(\d+)\]", report)]
    refs = [int(n) for n in re.findall(r"^\[(\d+)\] ", report, flags=re.M)]
    assert used and set(used) <= set(refs), "正文编号必须能在末尾 References 找到"
    assert refs == list(range(1, len(refs) + 1)), "References 编号必须连续无空洞"


def test_truncated_documents_are_recorded_not_silently_dropped() -> None:
    out = _render(_state(12))
    note = next(n for n in out["review_notes"] if n["node"] == "briefing")
    assert note["truncated_per_section"]["company"] == 2
    assert note["referenced"] == get_settings().report.max_references


def test_degraded_section_emits_no_orphan_reference() -> None:
    out = _render(_state(3, degraded=["company"]))
    assert "该类信息未找到公开依据" in out["report"]
    assert "事实" not in out["report"]
    assert "[1]" not in out["report"], "降级栏目不得在 References 里留下无正文的条目"


def test_inline_citations_switch_off_still_renders() -> None:
    s = get_settings().model_copy(deep=True)
    s.features.inline_citations = False
    report = _render(_state(12), s)["report"]
    assert "事实 0" in report and "## References" in report
