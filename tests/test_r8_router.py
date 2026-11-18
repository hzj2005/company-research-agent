"""R8-P1：意图路由节点测试。

覆盖三条路径：
- 无自然语言输入 → 四栏全选、不调模型（保护旧路径与评测基线）；
- 规则兜底（fixture / 无 key / LLM 失败）——确定性，0 调用；
- LLM 路径（注入）——验证输出校验与降级。

真实 LLM 不在这层测：`llm_route` 可注入，测试用假函数代替。
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from config.loader import get_settings
from graph.nodes.router import (
    RouteDecision,
    make_router_node,
    rule_route,
    rule_sections,
)


def _run(node: Any, state: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(node(state))


# ---------- 无输入：完整报告，零模型调用 ----------


def test_no_message_defaults_to_all_four_without_llm() -> None:
    async def boom(*_args: Any, **_kwargs: Any) -> RouteDecision:
        raise AssertionError("没有自然语言输入时不该调模型")

    node = make_router_node(get_settings(), llm_route=boom)
    out = _run(node, {"company": "Notion"})

    assert out["requested_sections"] == ["company", "industry", "financial", "news"]
    assert out["route_meta"]["source"] == "default_full"
    assert out["clarify"] == {}


# ---------- 规则路径 ----------


def test_rule_single_section() -> None:
    d = rule_route("只看特斯拉的财报")
    assert d.company == "特斯拉"
    assert d.sections == ["financial"]
    assert d.need_clarify is False


def test_rule_multi_section_keeps_config_order() -> None:
    d = rule_route("Notion 的融资和最近新闻")
    assert d.sections == ["financial", "news"], "按配置顺序输出，不按用户语序"


def test_rule_exclusion_is_not_a_positive_pick() -> None:
    picked, excluded, wants_all = rule_sections("看看 Notion，不要新闻")
    assert excluded == ["news"]
    assert picked == ["company", "industry", "financial"]
    assert wants_all is False


def test_rule_all_words() -> None:
    d = rule_route("全面调研 Notion")
    assert d.sections == ["company", "industry", "financial", "news"]


def test_rule_asks_scope_when_only_company_given() -> None:
    """用户决策 2026-11-18：只给公司不猜范围，先追问。"""
    d = rule_route("帮我查一下 Notion")
    assert d.need_clarify is True
    assert d.clarify_kind == "scope"
    assert d.sections == []
    assert "Notion" in d.question


def test_rule_asks_company_when_pronoun_only() -> None:
    d = rule_route("帮我查一下那家公司")
    assert d.need_clarify is True
    assert d.clarify_kind == "company"
    assert d.company is None


def test_rule_does_not_mistake_question_words_for_company() -> None:
    """「我们最近要看什么」里的「什么」不是公司名。"""
    d = rule_route("我们最近要看什么")
    assert d.need_clarify is True
    assert d.clarify_kind == "company"


def test_rule_extracts_chinese_company_without_verb() -> None:
    d = rule_route("字节跳动最近有什么新闻")
    assert d.company == "字节跳动"
    assert d.sections == ["news"]


# ---------- LLM 路径（注入，0 真实调用） ----------


def test_llm_decision_is_validated_and_normalized() -> None:
    async def fake(_message: str, _company: str, _settings: Any) -> RouteDecision:
        # 故意给非法 key、重复、乱序
        return RouteDecision(
            company="Notion",
            sections=["news", "bogus", "financial", "news"],
            reason="模型判的",
        )

    node = make_router_node(get_settings(), llm_route=fake)
    out = _run(node, {"company": "", "user_message": "Notion 的融资和新闻"})

    assert out["requested_sections"] == ["financial", "news"], "非法 key 丢弃、按配置顺序"
    assert out["company"] == "Notion", "原 state 没有公司时回写"
    assert out["route_meta"]["source"] == "llm"


def test_llm_empty_sections_becomes_clarify() -> None:
    """模型给了空集合却忘了标追问：必须兜住，绝不派发 0 个栏目。"""

    async def fake(_message: str, _company: str, _settings: Any) -> RouteDecision:
        return RouteDecision(company="Notion", sections=[], need_clarify=False)

    node = make_router_node(get_settings(), llm_route=fake)
    out = _run(node, {"company": "Notion", "user_message": "Notion 怎么样"})

    assert out["requested_sections"] == []
    assert out["clarify"]["kind"] == "scope"
    assert out["review_notes"][0]["need_clarify"] is True


def test_llm_failure_falls_back_to_rules() -> None:
    async def broken(_message: str, _company: str, _settings: Any) -> RouteDecision:
        raise RuntimeError("connection error")

    node = make_router_node(get_settings(), llm_route=broken)
    out = _run(node, {"company": "Notion", "user_message": "Notion 的财务"})

    assert out["requested_sections"] == ["financial"], "降级后仍应给出可用结果"
    assert out["route_meta"]["source"] == "rules"
    assert any(n.get("status") == "failed" for n in out["review_notes"])


def test_clarify_payload_has_clickable_options() -> None:
    node = make_router_node(get_settings())
    out = _run(node, {"company": "Notion", "user_message": "帮我查一下 Notion"})
    keys = [o["key"] for o in out["clarify"]["options"]]
    assert keys == ["company", "industry", "financial", "news", "all"]


def test_llm_missing_company_is_recovered_from_message() -> None:
    """实测：模型对「帮我查一下 Notion」回了 scope，但 company=null。

    节点必须用启发式补回公司名，否则追问话术里没有主体、下一轮接不上。
    """

    async def fake(_message: str, _company: str, _settings: Any) -> RouteDecision:
        return RouteDecision(
            company=None, sections=[], need_clarify=True,
            clarify_kind="scope", question="想看哪几块？",
        )

    node = make_router_node(get_settings(), llm_route=fake)
    out = _run(node, {"company": "", "user_message": "帮我查一下 Notion"})

    assert out["company"] == "Notion"
    assert out["clarify"]["kind"] == "scope"
    assert "Notion" in out["clarify"]["question"]


def test_llm_says_company_missing_but_message_has_one() -> None:
    async def fake(_message: str, _company: str, _settings: Any) -> RouteDecision:
        return RouteDecision(
            company=None, sections=[], need_clarify=True,
            clarify_kind="company", question="你想调研哪家公司？",
        )

    node = make_router_node(get_settings(), llm_route=fake)
    out = _run(node, {"company": "", "user_message": "特斯拉最近有什么新闻"})

    assert out["company"] == "特斯拉"
    assert out["clarify"]["kind"] == "scope", "能猜出公司就不该再问公司"


# ---------- 接线：图里真的跑了这个节点，且派发未被改动 ----------


def test_graph_runs_route_node_and_keeps_full_report_by_default() -> None:
    from graph.run import run_research

    settings = get_settings()
    with tempfile.TemporaryDirectory() as td:
        state, trace = asyncio.run(
            run_research("Notion", settings, Path(td) / "p.db", collect_trace=True)
        )

    assert "route" in trace, "主图必须实际执行路由节点"
    assert state["route_meta"]["source"] == "default_full"
    assert state["requested_sections"] == ["company", "industry", "financial", "news"]
    # P1 只写 state，不改派发：四段仍齐全，基线与旧行为一致
    assert all(state.get(f"{s}_paragraph") for s in ("company", "industry", "financial", "news"))
