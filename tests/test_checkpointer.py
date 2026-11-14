"""S2：Checkpointer 必须是真持久化，且 thread_id 隔离。

验收口径（docs/ACTION_PLAN.md S2）：进程重启后能恢复同一 thread 的 State；
并行写回不互相覆盖；恢复前后 State 一致。
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from config.loader import build_thread_id, load_settings
from graph.state import ResearchState, initial_state
from persistence.checkpointer import CheckpointSession


def _build_graph() -> StateGraph:
    async def write(state: ResearchState) -> dict[str, Any]:
        return {
            "company_data": {f"u-{state['company']}": {"score": 0.9}},
            "messages": [AIMessage(content="wrote")],
            "report": "ok",
        }

    b = StateGraph(ResearchState)
    b.add_node("write", write)
    b.add_edge(START, "write")
    b.add_edge("write", END)
    return b


@pytest.mark.asyncio
async def test_restart_recovers_state_and_threads_are_isolated(tmp_path) -> None:
    db = tmp_path / "checkpoints.db"
    settings = load_settings(environ={"APP_MODE": "fixture"})
    tid = build_thread_id("Notion", settings=settings)

    # 第一次「进程」
    async with CheckpointSession(settings=settings, path=db) as s1:
        g1 = s1.compile(_build_graph())
        cfg = s1.config_for(tid)
        out = await g1.ainvoke(initial_state("Notion"), config=cfg)
        assert out["report"] == "ok"
        snap1 = await g1.aget_state(cfg)
        assert snap1.values["company_data"] == {"u-Notion": {"score": 0.9}}

    assert db.exists() and db.stat().st_size > 0, "checkpoint 必须落盘，不能用内存 saver"

    # 第二次「进程」：重新打开同一个文件，模拟重启恢复
    async with CheckpointSession(settings=settings, path=db) as s2:
        g2 = s2.compile(_build_graph())
        snap2 = await g2.aget_state(s2.config_for(tid))
        assert snap2.values["report"] == "ok"
        assert snap2.values["company_data"] == {"u-Notion": {"score": 0.9}}
        assert [m.content for m in snap2.values["messages"]] == ["wrote"]

        # 另一个 thread_id 看不到 Notion 的状态
        other = await g2.aget_state(s2.config_for("OtherCompany:2026-01-01"))
        assert not other.values or "report" not in other.values


@pytest.mark.asyncio
async def test_same_thread_continues_and_accumulates_messages(tmp_path) -> None:
    """同一 thread 再跑一次，add_messages reducer 应累加而非覆盖。"""
    db = tmp_path / "checkpoints.db"
    settings = load_settings(environ={"APP_MODE": "fixture"})
    tid = build_thread_id("Notion", settings=settings)

    async with CheckpointSession(settings=settings, path=db) as s:
        g = s.compile(_build_graph())
        cfg = s.config_for(tid)
        await g.ainvoke(initial_state("Notion"), config=cfg)
        await g.ainvoke(initial_state("Notion"), config=cfg)
        snap = await g.aget_state(cfg)
        assert [m.content for m in snap.values["messages"]] == ["wrote", "wrote"]
