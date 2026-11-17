"""S10-B 护栏：同栏目事实冲突必须被**标注**，而不是被悄悄抹平或替读者猜。

真机证据：`docs/LIVE_SCORE.md` 里 `notion:company:0` 被判 refuted 的直接原因，
是 Company 栏目同时写了 2013 与 2014。

两条硬要求：
1. 只标注、不改写：开启冲突标注后，把 `> ` 开头的行去掉，报告与关闭时**逐字相同**；
2. 冲突行不许伪装成事实 bullet —— 它不以 `- ` 开头，不能污染「每条 bullet 必须带引用」的统计。

**0 次网络 / 0 次模型 / 0 次 Tavily 调用。**
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import pytest
from langchain_core.runnables import RunnableLambda
from pydantic import HttpUrl

from capabilities.briefing import BriefingBackend
from capabilities.conflict import detect_conflicts
from config.loader import apply_overrides, get_settings
from graph.contracts import Fact, SectionBrief
from graph.nodes.report import make_briefing_node
from graph.state import initial_state

COMPANY = "Notion"
PITCHBOOK = "https://pitchbook.com/profiles/company/168506-47"
CBINSIGHTS = "https://www.cbinsights.com/company/notion"


class _Claim:
    """最小替身：`detect_conflicts` 只读 claim 与 source_url。"""

    def __init__(self, claim: str, source_url: str):
        self.claim = claim
        self.source_url = source_url


def _claims(*pairs: tuple[str, str]) -> list[_Claim]:
    return [_Claim(c, u) for c, u in pairs]


# ------------------------------------------------------------------ 检出行为

def test_real_report_conflict_is_detected() -> None:
    conflicts = detect_conflicts(_claims(
        ("Notion was founded in 2013.", PITCHBOOK),
        ("Notion was founded in 2014.", CBINSIGHTS),
    ))
    assert len(conflicts) == 1
    assert conflicts[0].slot == "founded_year"
    assert [v.display for v in conflicts[0].values] == ["2013", "2014"]
    assert conflicts[0].values[0].source_urls == (PITCHBOOK,)


def test_single_value_is_not_a_conflict() -> None:
    assert detect_conflicts(_claims(("Notion was founded in 2013.", PITCHBOOK))) == []


def test_same_year_from_two_sources_is_not_a_conflict() -> None:
    assert detect_conflicts(_claims(
        ("Notion was founded in 2013.", PITCHBOOK),
        ("Notion, founded in 2013, is private.", CBINSIGHTS),
    )) == []


def test_headquarters_wording_difference_is_not_a_conflict() -> None:
    """`London` 与 `London, England` 是同一个地方，不能报冲突。"""
    assert detect_conflicts(_claims(
        ("Acme is headquartered in London, England.", "u1"),
        ("Acme is headquartered in London, UK.", "u2"),
    )) == []


def test_headquarters_real_conflict_is_detected() -> None:
    conflicts = detect_conflicts(_claims(
        ("Acme is headquartered in San Francisco, California.", "u1"),
        ("Acme is headquartered in London, England.", "u2"),
    ))
    assert [c.slot for c in conflicts] == ["headquarters"]


def test_employee_count_within_tolerance_is_not_a_conflict() -> None:
    """同一公司不同时点员工数本就不同，5% 差异不算冲突。"""
    assert detect_conflicts(_claims(
        ("Acme has 1,000 employees.", "u1"),
        ("Acme has 1,050 employees.", "u2"),
    )) == []


def test_employee_count_large_gap_is_detected() -> None:
    conflicts = detect_conflicts(_claims(
        ("Acme has 1,000 employees.", "u1"),
        ("Acme has 5,000 employees.", "u2"),
    ))
    assert [(c.slot, [v.display for v in c.values]) for c in conflicts] == [
        ("employee_count", ["1,000", "5,000"])
    ]


def test_founded_verb_with_a_later_year_is_not_misread() -> None:
    """`founded by X, who in 2019 moved` 里的 2019 不是成立年份。"""
    assert detect_conflicts(_claims(("Acme was founded by Jane, who in 2019 moved to Berlin.", "u1"))) == []


def test_render_carries_citation_numbers_and_tolerates_trailing_slash() -> None:
    conflicts = detect_conflicts(_claims(
        ("Notion was founded in 2013.", PITCHBOOK),
        ("Notion was founded in 2014.", CBINSIGHTS),
    ))
    line = conflicts[0].render({PITCHBOOK: 6, CBINSIGHTS: 4})
    assert line.startswith("**来源冲突**：成立年份出现 2 个取值")
    assert "2013 [6]" in line and "2014 [4]" in line
    assert "未判定哪个正确" in line

    # HttpUrl 的 str() 会补尾斜杠，索引却按去尾斜杠存 —— 两边都要能对上
    assert "[6]" in conflicts[0].render({PITCHBOOK + "/": 6, CBINSIGHTS + "/": 4})
    assert "[6]" in conflicts[0].render({PITCHBOOK: 6, CBINSIGHTS: 4})


# ------------------------------------------------------------------ 报告接入

def _state() -> dict[str, Any]:
    urls = [PITCHBOOK, CBINSIGHTS]
    return {
        **initial_state(COMPANY),
        "curated_data": {
            u: {"url": u, "title": f"来源 {i}", "score": 0.9, "content": "x", "section": "company"}
            for i, u in enumerate(urls)
        },
        "references": {u: {"title": f"来源 {i}", "score": 0.9, "used_by": ["company"]}
                       for i, u in enumerate(urls)},
        "degraded_sections": [],
    }


def _brief() -> SectionBrief:
    return SectionBrief(
        section="company",
        facts=[
            Fact(claim="Notion was founded in 2013.", source_url=HttpUrl(PITCHBOOK), confidence=0.72),
            Fact(claim="Notion was founded in 2014.", source_url=HttpUrl(CBINSIGHTS), confidence=0.77),
        ],
    )


def _render(**overrides: Any) -> dict[str, Any]:
    settings = apply_overrides(get_settings(), overrides) if overrides else get_settings()
    backend = BriefingBackend(chain=RunnableLambda(lambda _p: _brief()), mode="test", seen=[])
    return asyncio.run(make_briefing_node(settings, backend=backend)(_state()))


def test_report_annotates_conflict_with_citations() -> None:
    """R3 迁移：拼装器把段落里的 conflicts 渲染成引用块。

    冲突的**检测**在子图/R4；这里测报告层的渲染契约。
    """
    from graph.nodes.assemble import assemble_report

    para = {
        "key": "company", "status": "ok",
        "facts": [{"claim": "Notion 成立于 2013", "source_url": PITCHBOOK}],
        "references": {PITCHBOOK: {"title": "A", "score": 0.9},
                       CBINSIGHTS: {"title": "B", "score": 0.8}},
        "conflicts": ["成立年份出现 2 个取值：2013 / 2014"],
    }
    report, _ = assemble_report(COMPANY, [para], get_settings())
    block = [line for line in report.splitlines() if line.startswith("> ")]
    assert len(block) == 1
    assert "成立年份出现 2 个取值" in block[0]
    assert "2013" in block[0] and "2014" in block[0]


def test_conflict_line_is_not_a_factual_bullet() -> None:
    """冲突行不能以 `- ` 开头，否则会被「每条 bullet 必须有引用」的统计误算。"""
    out = _render()
    for line in out["report"].splitlines():
        if "来源冲突" in line:
            assert not line.startswith("- ")
            assert line.startswith("> ")


def test_briefing_records_structured_conflict() -> None:
    """R3 迁移：拼装器把段落 conflicts 原样记进 briefings（结构化留痕）。"""
    from graph.nodes.assemble import assemble_report

    conflict = {"slot": "founded_year", "values": [{"value": "2013"}, {"value": "2014"}]}
    para = {
        "key": "company", "status": "ok", "facts": [],
        "references": {}, "conflicts": [conflict],
    }
    _, briefings = assemble_report(COMPANY, [para], get_settings())
    conflicts = briefings["company"]["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["slot"] == "founded_year"
    assert [v["value"] for v in conflicts[0]["values"]] == ["2013", "2014"]


def test_annotation_only_adds_lines_never_rewrites_them() -> None:
    """关掉标注后，报告应当恰好等于开启版去掉 `> ` 行 —— 证明「只标注、不改写」。"""
    on_report = _render()["report"]
    off_report = _render(**{"features.conflict_annotation": False})["report"]
    stripped = "\n".join(l for l in on_report.split("\n") if not l.startswith("> "))
    assert stripped == off_report


def test_switch_off_produces_no_conflict_note() -> None:
    out = _render(**{"features.conflict_annotation": False})
    assert not [line for line in out["report"].splitlines() if "来源冲突" in line]
    assert out["briefings"]["company"]["conflicts"] == []


def test_no_conflict_keeps_report_untouched() -> None:
    """没有冲突时，报告里不该凭空多出一行。"""
    single = SectionBrief(
        section="company",
        facts=[Fact(claim="Notion was founded in 2013.", source_url=HttpUrl(PITCHBOOK), confidence=0.72)],
    )
    backend = BriefingBackend(chain=RunnableLambda(lambda _p: single), mode="test", seen=[])
    settings = get_settings()
    state = _state()
    state["curated_data"].pop(CBINSIGHTS)
    state["references"].pop(CBINSIGHTS)
    out = asyncio.run(make_briefing_node(settings, backend=backend)(state))
    assert not [line for line in out["report"].splitlines() if "来源冲突" in line]
    assert out["briefings"]["company"]["conflicts"] == []


@pytest.mark.parametrize("section", ["company", "industry", "financial", "news"])
def test_briefing_always_has_a_conflicts_key(section: str) -> None:
    """结构稳定：无论有没有冲突，briefings 都有 conflicts 字段，下游不用做 None 判断。"""
    out = _render()
    assert "conflicts" in out["briefings"][section]
