"""S2：State 契约与 reducer 的回归测试。

覆盖 docs/BASELINE.md 第 3 节发现的两个缺陷：
- typing.TypedDict 导致 schema 内省失败
- 并行节点写同一字段时旧证据被覆盖
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from graph.state import ResearchState, initial_state, merge_docs


def test_merge_docs_keeps_old_and_overrides_same_url() -> None:
    left = {"u1": {"title": "old"}, "u2": {"title": "keep"}}
    right = {"u1": {"title": "new"}, "u3": {"title": "fresh"}}
    got = merge_docs(left, right)
    assert got == {
        "u1": {"title": "new"},
        "u2": {"title": "keep"},
        "u3": {"title": "fresh"},
    }
    assert merge_docs(None, None) == {}


def test_state_schema_is_introspectable() -> None:
    """原版在这里抛 PydanticUserError；改用 typing_extensions.TypedDict 后必须通过。"""
    builder = StateGraph(ResearchState)

    async def noop(state: ResearchState) -> dict[str, Any]:
        return {}

    builder.add_node("noop", noop)
    builder.add_edge(START, "noop")
    builder.add_edge("noop", END)
    compiled = builder.compile()
    # LangGraph 1.2 中 get_input_schema() 只列外部输入 channel；这里必须能调用且不抛
    # PydanticUserError（原版的缺陷），完整字段用 get_output_schema() 断言。
    compiled.get_input_schema().model_json_schema()
    schema = compiled.get_output_schema().model_json_schema()
    props = set(schema.get("properties", {}))
    assert {
        "company", "messages", "company_data", "industry_data",
        "financial_data", "news_data", "evidence_verdict",
        "retry_count", "references", "report",
    } <= props


def test_parallel_writes_are_merged_by_reducer() -> None:
    async def node_a(state: ResearchState) -> dict[str, Any]:
        return {
            "company_data": {"u1": {"title": "A"}},
            "messages": [AIMessage(content="from-a")],
        }

    async def node_b(state: ResearchState) -> dict[str, Any]:
        return {
            "company_data": {"u2": {"title": "B"}},
            "messages": [AIMessage(content="from-b")],
        }

    async def join(state: ResearchState) -> dict[str, Any]:
        return {"report": "done"}

    builder = StateGraph(ResearchState)
    builder.add_node("a", node_a)
    builder.add_node("b", node_b)
    builder.add_node("join", join)
    builder.add_edge(START, "a")
    builder.add_edge(START, "b")
    builder.add_edge(["a", "b"], "join")
    builder.add_edge("join", END)

    result = asyncio.run(builder.compile().ainvoke(initial_state("Notion")))
    assert set(result["company_data"]) == {"u1", "u2"}, "并行写回被覆盖，reducer 未生效"
    assert {m.content for m in result["messages"]} == {"from-a", "from-b"}
    assert result["report"] == "done"
