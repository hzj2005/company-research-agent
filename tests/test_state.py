"""S2：State 契约与 reducer 的回归测试。

覆盖 docs/BASELINE.md 第 3 节发现的两个缺陷：
- typing.TypedDict 导致 schema 内省失败
- 并行节点写同一字段时旧证据被覆盖
以及 S3 前复查发现的「回退写回覆盖其他 section」缺口。
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
        "retry_count", "references", "report", "degraded",
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


def test_retry_writes_preserve_other_sections() -> None:
    """S3 前置：回退节点只写自己负责的 section，其他 section 的状态不能被整体覆盖。

    S2 初版只给文档字典配了 reducer，evidence_verdict / retry_count /
    rewrite_queries / briefings / review_notes 都是裸 dict/list，第二轮 update
    会把第一轮结果冲掉。这里用两轮顺序写回模拟回退回路。
    """

    async def round_one(state: ResearchState) -> dict[str, Any]:
        return {
            "evidence_verdict": {"company": "insufficient", "industry": "sufficient"},
            "retry_count": {"company": 1, "industry": 0},
            "rewrite_queries": {"company": ["q1"]},
            "briefings": {"industry": {"text": "industry draft"}},
            "review_notes": [{"round": 1, "note": "company 证据不足"}],
            "degraded_sections": ["company"],
        }

    async def round_two(state: ResearchState) -> dict[str, Any]:
        return {
            "evidence_verdict": {"company": "sufficient"},
            "retry_count": {"company": 2},
            "rewrite_queries": {"company": ["q1", "q2"]},
            "briefings": {"company": {"text": "company draft"}},
            "review_notes": [{"round": 2, "note": "company 已补足"}],
            "degraded_sections": ["company"],
        }

    builder = StateGraph(ResearchState)
    builder.add_node("round_one", round_one)
    builder.add_node("round_two", round_two)
    builder.add_edge(START, "round_one")
    builder.add_edge("round_one", "round_two")
    builder.add_edge("round_two", END)

    result = asyncio.run(builder.compile().ainvoke(initial_state("Notion")))
    assert result["evidence_verdict"] == {"company": "sufficient", "industry": "sufficient"}
    assert result["retry_count"] == {"company": 2, "industry": 0}
    assert result["rewrite_queries"] == {"company": ["q1", "q2"]}
    assert set(result["briefings"]) == {"company", "industry"}
    assert len(result["review_notes"]) == 2, "复核备注被覆盖，reducer 未生效"
    assert result["degraded_sections"] == ["company"], "降级栏目未去重"
    assert result["degraded"] is False
