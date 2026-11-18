"""R8-P2：子集派发 + 只渲染选中栏目的契约测试。

这层锁的是最容易"看起来像 bug"的行为：
**未请求 ≠ 证据不足**——只选了财务时，报告里不能出现另外三栏的拒答话术。

同时锁住追问分支：需要追问时一个子图都不跑（不花检索额度）。
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path
from typing import Any

from config.loader import get_settings
from graph.orchestrator import pending_sections, selected_sections
from graph.run import run_research

ALL_SECTIONS = ["company", "industry", "financial", "news"]
UNREQUESTED_TITLES = ("公司概况", "行业概况", "新闻动态")


def _run(message: str, company: str = "Notion") -> tuple[dict[str, Any], list[str]]:
    settings = get_settings()
    with tempfile.TemporaryDirectory() as td:
        return asyncio.run(
            run_research(
                company, settings, Path(td) / "p.db",
                user_message=message, collect_trace=True,
            )
        )


def _headings(report: str) -> list[str]:
    return re.findall(r"^## (.+)$", report, flags=re.MULTILINE)


# ---------- 派发：只在选中集合内 ----------


def test_dispatch_narrows_to_requested_sections() -> None:
    state, _ = _run("Notion 的财务数据")

    assert state["requested_sections"] == ["financial"]
    assert state["financial_paragraph"], "选中的栏目必须真的跑了"
    for key in ("company", "industry", "news"):
        assert not state.get(f"{key}_paragraph"), f"{key} 未请求却被派发了"


def test_degraded_sections_only_counts_requested() -> None:
    state, _ = _run("Notion 的财务数据")
    assert state["degraded_sections"] == [], "未请求栏目不得被算成降级"


def test_pending_sections_respects_request_intersect_whitelist() -> None:
    settings = get_settings()
    state = {"requested_sections": ["financial", "news"], "sections_to_research": ["news"]}
    assert pending_sections(state, settings) == ["news"], "重试白名单只能在选中集合内收窄"

    state = {"requested_sections": ["financial"], "sections_to_research": []}
    assert pending_sections(state, settings) == ["financial"]

    # 没有路由信息（旧调用/直连子图）→ 保持旧行为全选
    assert pending_sections({}, settings) == ALL_SECTIONS


def test_selected_sections_is_empty_when_clarify_required() -> None:
    settings = get_settings()
    state = {"requested_sections": [], "route_meta": {"need_clarify": True}}
    assert selected_sections(state, settings) == [], "要追问时不该派发任何子图"


# ---------- 报告：只渲染选中栏目 ----------


def test_report_renders_only_requested_section() -> None:
    state, _ = _run("Notion 的财务数据")
    headings = _headings(state["report"])

    assert headings == ["财务概况", "References"]
    for title in UNREQUESTED_TITLES:
        assert title not in state["report"], f"{title} 不该出现在报告里"


def test_unrequested_sections_do_not_emit_abstain_text() -> None:
    """核心契约：未请求 ≠ 答不出来。不能补拒答话术。"""
    state, _ = _run("Notion 的财务数据")
    abstain = get_settings().graph.degrade.message
    assert state["report"].count(abstain) == 0


def test_references_only_come_from_requested_section() -> None:
    state, _ = _run("Notion 的财务数据")
    paragraph = state["financial_paragraph"]
    allowed = {
        str(f.get("source_url"))
        for f in paragraph.get("facts", [])
        if f.get("source_url")
    } | set(paragraph.get("references") or {})

    # References 行格式：`[n] 标题 — URL`
    refs = re.findall(r"^\[\d+\]\s+.+?\s+—\s+(\S+)$", state["report"], flags=re.MULTILINE)
    assert refs, "选中栏目有事实，References 不该为空"
    assert set(refs) <= {u.rstrip("/") for u in allowed}, "References 混入了未请求栏目的来源"


def test_two_sections_keep_config_order() -> None:
    state, _ = _run("Notion 的融资和最近新闻")
    assert state["requested_sections"] == ["financial", "news"]
    assert _headings(state["report"]) == ["财务概况", "新闻动态", "References"]


# ---------- 追问：不跑子图 ----------


def test_clarify_skips_all_subgraphs() -> None:
    state, trace = _run("帮我查一下 Notion")

    assert "research" not in trace, "要追问时不能启动四张子图（会白花检索额度）"
    assert trace == ["grounding", "route", "briefing"]
    assert state["clarify"]["kind"] == "scope"
    assert state["report"] == state["clarify"]["question"]
    assert state["report"].endswith("？")


# ---------- 回归：没有自然语言输入时仍是完整报告 ----------


def test_full_report_unchanged_when_no_message() -> None:
    settings = get_settings()
    with tempfile.TemporaryDirectory() as td:
        state, _ = asyncio.run(
            run_research("Notion", settings, Path(td) / "p.db", collect_trace=True)
        )
    assert state["requested_sections"] == ALL_SECTIONS
    assert _headings(state["report"]) == [
        "公司概况", "行业概况", "财务概况", "新闻动态", "References",
    ]
