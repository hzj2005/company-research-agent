"""S5 验收（R3 迁移版）：引用可溯源、伪造 URL 拒绝、降级不编造、引用开关。

R3：抽取下沉到四张子图（extract_section_brief 仍负责 URL 守卫），
briefing 退化为拼装器（assemble_report 负责编号 + References）。
本测试验证这两层的等价能力仍成立。
"""

from __future__ import annotations

import asyncio
from typing import Any

from capabilities.briefing import make_briefing_backend
from capabilities.structured import extract_section_brief
from config.loader import get_settings
from graph.contracts import SectionBrief
from graph.nodes.assemble import assemble_report


def _doc(url: str, content: str, score: float = 0.9) -> dict[str, Any]:
    return {"url": url, "title": url, "content": content, "score": score}


def _extract(section: str, docs: list[dict[str, Any]]) -> SectionBrief:
    s = get_settings()
    backend = make_briefing_backend(s)
    try:
        return asyncio.run(
            extract_section_brief(
                backend.chain, section=section, company="X", docs=docs, settings=s
            )
        ).brief
    finally:
        asyncio.run(backend.aclose())


def test_facts_map_back_to_source_urls() -> None:
    docs = [_doc("https://e.org/a", "事实甲"), _doc("https://e.org/b", "事实乙")]
    brief = _extract("company", docs)
    assert brief.facts
    assert all(str(f.source_url) in {d["url"] for d in docs} for f in brief.facts)


def test_fabricated_url_is_dropped() -> None:
    """抽取层 URL 守卫：stub 只回显给定文档的 URL，不引入外部 URL。"""
    docs = [_doc("https://e.org/a", "事实甲")]
    brief = _extract("company", docs)
    assert all(str(f.source_url) == "https://e.org/a" for f in brief.facts)


def test_no_docs_degrades_without_fabrication() -> None:
    brief = _extract("company", [])
    assert brief.facts == []
    assert brief.degraded is True


def test_inline_citations_switch_applies_in_assemble() -> None:
    s = get_settings()
    section = {
        "key": "company", "status": "ok",
        "facts": [{"claim": "事实", "source_url": "https://e.org/a"}],
        "references": {"https://e.org/a": {"title": "A", "score": 0.9}},
        "conflicts": [],
    }
    report, _ = assemble_report("X", [section], s)
    assert "- 事实 [1]" in report
    assert "[1] A — https://e.org/a" in report

    off = s.model_copy(deep=True)
    off.features.inline_citations = False
    report_off, _ = assemble_report("X", [section], off)
    assert "- 事实\n" in report_off, "关闭行内引用后不应有 [n]"


def test_fact_without_source_gets_no_number() -> None:
    s = get_settings()
    section = {
        "key": "company", "status": "ok",
        "facts": [{"claim": "无来源", "source_url": ""}],
        "references": {}, "conflicts": [],
    }
    report, _ = assemble_report("X", [section], s)
    assert "- 无来源\n" in report
    assert "- 无来源 [" not in report


def test_fixture_backend_is_offline() -> None:
    """fixture backend 指向不可达地址，靠 MockTransport 拦截（不联网）。"""
    s = get_settings()
    backend = make_briefing_backend(s)
    try:
        assert backend.mode == "fixture"
        assert backend.base_url == "http://127.0.0.1:1/v1"
    finally:
        asyncio.run(backend.aclose())
