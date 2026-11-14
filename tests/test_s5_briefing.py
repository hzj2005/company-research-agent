"""S5-B 8.3 验收：briefing 的结构化输出双路径。

覆盖：开关 on/off 逐字一致、on 真跑 LCEL 留痕、URL 级回溯、抽取失败拒答、
行内引用开关、以及 fixture 后端完全离网。**无 key、0 次网络请求、0 次 Tavily 调用**。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import pytest
from langchain_core.runnables import RunnableLambda
from pydantic import HttpUrl

from capabilities.briefing import BriefingBackend, make_briefing_backend
from capabilities.structured import extract_section_brief
from config.loader import apply_overrides, get_settings
from graph.contracts import Fact, SectionBrief
from graph.nodes.report import make_briefing_node
from graph.state import initial_state

COMPANY = "X"


def _state(n: int = 2) -> dict[str, Any]:
    """构造 n 篇全部落在 references 里的合格文档（与 test_report_citations 同形）。"""
    urls = [f"https://example.org/{i}" for i in range(n)]
    return {
        **initial_state(COMPANY),
        "curated_data": {
            u: {"url": u, "title": f"来源 {i}", "score": 0.9,
                "content": f"事实 {i}", "section": "company"}
            for i, u in enumerate(urls)
        },
        "references": {
            u: {"title": f"来源 {i}", "score": 0.9, "used_by": ["company"]}
            for i, u in enumerate(urls)
        },
        "degraded_sections": [],
    }


def _backend(brief: SectionBrief) -> BriefingBackend:
    """离线替身：直接返回给定 SectionBrief，用于验证节点的降级/回溯分支。"""
    return BriefingBackend(
        chain=RunnableLambda(lambda _payload: brief), mode="test", seen=[]
    )


def _render(state: dict[str, Any], settings: Any, backend: BriefingBackend | None = None):
    return asyncio.run(make_briefing_node(settings, backend=backend)(state))


# ---------------------------------------------------------------- A/B 基线

@pytest.mark.parametrize("n", [2, 12])
def test_on_off_reports_are_identical(n: int) -> None:
    """fixture stub 的 claim 就是 doc.content，因此两条路径应逐字一致。"""
    s = get_settings()
    off = apply_overrides(s, {"features.structured_output": False})
    state = _state(n)
    on_out = _render(state, s)
    off_out = _render(state, off)
    assert on_out["report"] == off_out["report"]
    assert on_out["briefings"]["company"]["docs"] == off_out["briefings"]["company"]["docs"]


def test_on_path_actually_invokes_extraction_chain() -> None:
    s = get_settings()
    out = _render(_state(2), s)
    notes = [n for n in out["review_notes"] if n["node"] == "structured_extract"]
    # 4 个栏目里 3 个无文档被短路，只有 company 真发了抽取请求
    assert len(notes) == 1 and notes[0]["status"] == "ok" and notes[0]["facts"] == 2
    assert "facts" in out["briefings"]["company"]
    assert out["review_notes"][-1]["node"] == "briefing", "截断留痕必须仍是最后一条"


def test_off_path_never_touches_backend() -> None:
    off = apply_overrides(get_settings(), {"features.structured_output": False})

    class ExplodingBackend(BriefingBackend):
        def __init__(self):
            super().__init__(chain=RunnableLambda(lambda _p: None), mode="test")

    out = _render(_state(2), off, ExplodingBackend())
    assert "事实 0" in out["report"]
    assert not [n for n in out["review_notes"] if n["node"] == "structured_extract"]


# ---------------------------------------------------------------- 回溯与降级

def test_facts_must_map_back_to_references() -> None:
    s = get_settings()
    state = _state(2)
    brief = SectionBrief(
        section="company",
        facts=[
            Fact(claim="事实 0", source_url=HttpUrl("https://example.org/0"), confidence=0.9),
            Fact(claim="事实 1", source_url=HttpUrl("https://example.org/1"), confidence=0.8),
        ],
    )
    out = _render(state, s, _backend(brief))
    used = [int(x) for x in re.findall(r"- 事实 \d+ \[(\d+)\]", out["report"])]
    refs = [int(x) for x in re.findall(r"^\[(\d+)\] ", out["report"], flags=re.M)]
    assert used and set(used) <= set(refs)
    assert len(out["briefings"]["company"]["facts"]) == 2


def test_fabricated_url_is_dropped_and_section_abstains() -> None:
    s = get_settings()
    brief = SectionBrief(
        section="company",
        facts=[Fact(claim="编造", source_url=HttpUrl("https://evil.example/fake"), confidence=0.99)],
    )
    out = _render(_state(2), s, _backend(brief))
    notes = [n for n in out["review_notes"] if n["node"] == "structured_extract"]
    assert any(n["status"] == "dropped_uncited_facts" for n in notes)
    assert any(n["status"] == "degraded" for n in notes)
    assert "编造" not in out["report"]
    assert "该类信息未找到公开依据" in out["report"]
    assert out["briefings"]["company"]["status"] == "extraction_degraded"


def test_backend_degraded_never_fabricates() -> None:
    s = get_settings()
    brief = SectionBrief(section="company", facts=[], degraded=True, degrade_reason="模型无输出")
    out = _render(_state(2), s, _backend(brief))
    assert "事实 0" not in out["report"]
    assert "该类信息未找到公开依据" in out["report"]


def test_inline_citation_switch_applies_to_structured_path() -> None:
    s = apply_overrides(get_settings(), {"features.inline_citations": False})
    out = _render(_state(2), s)
    assert "事实 0" in out["report"] and "[1]" not in out["report"].split("## References")[0]
    assert "## References" in out["report"]


def test_truncation_keeps_every_bullet_cited_on_structured_path() -> None:
    s = get_settings()
    out = _render(_state(12), s)
    bullets = [l for l in out["report"].splitlines() if l.startswith("- 事实")]
    assert len(bullets) == s.report.max_references
    assert all(re.search(r"\[\d+\]$", line) for line in bullets)
    assert out["review_notes"][-1]["truncated_per_section"]["company"] == 2


# ---------------------------------------------------------------- 后端本身

def test_fixture_backend_parses_user_role_payload_and_stays_offline() -> None:
    """回归：OpenAI 请求体里 human 的 role 是 user，取错会静默抽不出事实。"""
    s = get_settings()
    backend = make_briefing_backend(s)
    assert backend.mode == "fixture"
    assert backend.client is not None
    assert backend.base_url and "127.0.0.1:1" in backend.base_url, "mock 必须指向不可达本地端口"
    docs = [
        {"url": "https://example.org/a", "title": "A", "content": "事实 A"},
        {"url": "https://example.org/b", "title": "B", "content": "事实 B"},
    ]
    result = asyncio.run(
        extract_section_brief(
            backend.chain, section="company", company=COMPANY, docs=docs, settings=s
        )
    )
    assert len(backend.seen) == 1
    assert "<documents>" in backend.seen[0]
    assert not result.brief.degraded and len(result.brief.facts) == 2
    assert [f.claim for f in result.brief.facts] == ["事实 A", "事实 B"]
    asyncio.run(backend.aclose())
