"""S12 护栏：Postgres 后端必须和 SQLite 过同样的三关。

- 跨会话（≈换进程）读回状态；
- 同 thread 累加而不是覆盖；
- 真实 7 节点业务图的完整 State 能恢复；
- `interrupt()` 停下、`Command(resume=...)` 继续。

没有可用数据库时整组跳过：CI 和离线环境不该因为「没装 PG」而红，
但**装了就必须真跑**——跳过和通过必须能区分开。
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import psycopg
import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from capabilities.retrieval import load_fixture_store, make_document_tool
from config.loader import build_thread_id, load_settings, resolve_postgres_dsn
from graph.builder import build_graph
from graph.state import ResearchState, initial_state
from persistence.checkpointer import CheckpointSession

DSN = os.getenv("POSTGRES_DSN", "postgresql://postgres:devpass@localhost:5432/research")


def _pg_ready() -> bool:
    """连得上 **且** 表已建，才算可用——否则会变成一堆难读的 UndefinedTable。"""
    try:
        with psycopg.connect(DSN, connect_timeout=2) as conn:
            conn.execute("select 1 from checkpoints limit 1")
        return True
    except Exception:
        return False


requires_pg = pytest.mark.skipif(
    not _pg_ready(),
    reason=f"没有可用的 Postgres（{DSN}）；先 `uv run python -m persistence.setup_postgres`",
)


def _settings():
    return load_settings(
        environ={"APP_MODE": "fixture", "CHECKPOINTER": "postgres", "POSTGRES_DSN": DSN}
    )


def _tid(tag: str) -> str:
    """每个用例独立 thread，互不干扰，也方便跑完就删。"""
    return f"{tag}:{uuid.uuid4().hex[:8]}"


async def _drop(session: CheckpointSession, tid: str) -> None:
    await session.saver.adelete_thread(tid)


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


def _build_gated_graph() -> StateGraph:
    """带人工闸门的图：不 resume 就永远停在 gate 前。"""

    async def draft(state: ResearchState) -> dict[str, Any]:
        return {"report": "draft"}

    async def gate(state: ResearchState) -> dict[str, Any]:
        decision = interrupt({"question": "approve?"})
        return {"report": "approved" if decision == "yes" else "rejected"}

    b = StateGraph(ResearchState)
    b.add_node("draft", draft)
    b.add_node("gate", gate)
    b.add_edge(START, "draft")
    b.add_edge("draft", "gate")
    b.add_edge("gate", END)
    return b


@pytest.mark.asyncio
@requires_pg
async def test_pg_recovers_state_across_sessions() -> None:
    settings = _settings()
    tid = _tid("PGProbe")
    async with CheckpointSession(settings=settings) as s1:
        assert s1.backend == "postgres"
        g1 = s1.compile(_build_graph())
        cfg = s1.config_for(tid)
        await g1.ainvoke(initial_state("PGProbe"), config=cfg)
        try:
            # 第二个会话 = 换一次连接，等价于「进程重启」
            async with CheckpointSession(settings=settings) as s2:
                g2 = s2.compile(_build_graph())
                snap = await g2.aget_state(s2.config_for(tid))
                assert snap.values["report"] == "ok"
                assert snap.values["company_data"] == {"u-PGProbe": {"score": 0.9}}
                assert [m.content for m in snap.values["messages"]] == ["wrote"]
        finally:
            await _drop(s1, tid)


@pytest.mark.asyncio
@requires_pg
async def test_pg_threads_are_isolated_and_same_thread_accumulates() -> None:
    settings = _settings()
    tid = _tid("PGAccum")
    other = _tid("PGOther")
    async with CheckpointSession(settings=settings) as s:
        g = s.compile(_build_graph())
        cfg = s.config_for(tid)
        try:
            await g.ainvoke(initial_state("PGAccum"), config=cfg)
            await g.ainvoke(initial_state("PGAccum"), config=cfg)
            snap = await g.aget_state(cfg)
            assert [m.content for m in snap.values["messages"]] == ["wrote", "wrote"]

            isolated = await g.aget_state(s.config_for(other))
            assert not isolated.values or "report" not in isolated.values
        finally:
            await _drop(s, tid)
            await _drop(s, other)


@pytest.mark.asyncio
@requires_pg
async def test_pg_business_graph_state_survives_restart() -> None:
    """1 节点图只证明 saver 能用；这里换成 S3 的真实 7 节点业务图。"""
    settings = _settings()
    company = load_fixture_store(settings).case_by_key("sufficient")["company"]
    tid = _tid(company)
    async with CheckpointSession(settings=settings) as s1:
        g1 = s1.compile(build_graph(settings, make_document_tool(settings)))
        out = await g1.ainvoke(initial_state(company), config=s1.config_for(tid))
        try:
            async with CheckpointSession(settings=settings) as s2:
                g2 = s2.compile(build_graph(settings, make_document_tool(settings)))
                snap = await g2.aget_state(s2.config_for(tid))
                for field in ("report", "references", "evidence_verdict", "briefings", "retry_count"):
                    assert snap.values[field] == out[field], f"{field} 未在重启后恢复"
        finally:
            await _drop(s1, tid)


@pytest.mark.asyncio
@requires_pg
async def test_pg_interrupt_then_resume() -> None:
    """人工复核的底座：停下 → 换会话 → resume 继续，结果要接得上。"""
    settings = _settings()
    tid = _tid("PGGate")
    async with CheckpointSession(settings=settings) as s1:
        g1 = s1.compile(_build_gated_graph())
        cfg = s1.config_for(tid)
        try:
            await g1.ainvoke(initial_state("PGGate"), config=cfg)
            snap = await g1.aget_state(cfg)
            assert snap.next, "图应该在 gate 前停住"
            assert snap.values["report"] == "draft"

            async with CheckpointSession(settings=settings) as s2:
                g2 = s2.compile(_build_gated_graph())
                out = await g2.ainvoke(Command(resume="yes"), config=s2.config_for(tid))
                assert out["report"] == "approved"
        finally:
            await _drop(s1, tid)


def test_missing_dsn_fails_loudly() -> None:
    """选了 postgres 却没配 DSN：必须报错并指路，不许静默退回 SQLite。"""
    s = load_settings(environ={"APP_MODE": "fixture", "CHECKPOINTER": "postgres", "POSTGRES_DSN": ""})
    with pytest.raises(ValueError) as exc:
        resolve_postgres_dsn(s)
    assert "POSTGRES_DSN" in str(exc.value)


def test_explicit_path_keeps_tests_on_sqlite(tmp_path) -> None:
    """测试注入临时文件时，不被本机 .env 里的 postgres 带走。"""
    s = _settings()
    sess = CheckpointSession(settings=s, path=tmp_path / "c.db")
    assert sess.backend == "sqlite"
    assert sess.path == tmp_path / "c.db"


@requires_pg
def test_postgres_has_expected_tables() -> None:
    """建表命令真的建出了这几张，而不是只打印了一行成功。"""
    with psycopg.connect(DSN, connect_timeout=2) as conn:
        rows = conn.execute(
            "select tablename from pg_tables where schemaname='public'"
        ).fetchall()
    names = {r[0] for r in rows}
    assert {"checkpoints", "checkpoint_writes", "checkpoint_blobs", "jobs", "reports"} <= names


# --- S12.2 任务台账 ---


@requires_pg
def test_job_store_roundtrip() -> None:
    """建任务 → 查 → 改状态 → 存报告 → 取报告，全走真库。"""
    import asyncio

    from persistence.job_store import PostgresJobStore

    jid = f"test-{uuid.uuid4().hex[:8]}"

    async def flow() -> None:
        store = await PostgresJobStore(DSN).open()
        try:
            await store.create_job(jid, {"company": "Notion", "industry": "SaaS"})
            job = await store.get_job(jid)
            assert job is not None and job["status"] == "pending"
            assert job["company"] == "Notion"
            assert job["inputs"]["industry"] == "SaaS"

            await store.update_job(jid, status="completed")
            await store.store_report(jid, "# 报告正文")
            assert (await store.get_job(jid))["status"] == "completed"
            assert (await store.get_report(jid))["report"] == "# 报告正文"

            # 覆盖写而不是插重复行
            await store.store_report(jid, "# 新正文")
            assert (await store.get_report(jid))["report"] == "# 新正文"

            ids = [r["job_id"] for r in await store.list_jobs(limit=50)]
            assert jid in ids
        finally:
            async with store.pool.connection() as conn:
                await conn.execute("delete from jobs where job_id = %s", (jid,))
            await store.close()

    asyncio.run(flow())


@requires_pg
def test_job_store_rejects_unknown_column() -> None:
    """update_job 只认白名单字段：拼 SQL 的入口必须收口。"""
    import asyncio

    async def flow() -> None:
        from persistence.job_store import PostgresJobStore

        store = await PostgresJobStore(DSN).open()
        try:
            with pytest.raises(ValueError):
                # 白名单外（含明显的注入尝试）一律拒绝，不拼进 SQL
                await store.update_job("whatever", **{"status": "x", "notes": "y"})
        finally:
            await store.close()

    asyncio.run(flow())


# --- S12.3 旧存档迁移 ---


@requires_pg
def test_migration_copies_thread_between_backends(tmp_path) -> None:
    """SQLite 跑一遍 → 迁到 PG → 三口径一致（点数 / 状态值 / 字段集合）。"""
    import asyncio

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from persistence import migrate_sqlite_to_pg as m

    db = tmp_path / "src.db"
    tid = _tid("Migrate")

    async def flow() -> None:
        sqlite_settings = load_settings(
            environ={"APP_MODE": "fixture", "CHECKPOINTER": "sqlite", "POSTGRES_DSN": ""}
        )
        # 用 SQLite 产生两个存档点（跑两次同一线程）
        async with CheckpointSession(settings=sqlite_settings, path=db) as s:
            g = s.compile(_build_graph())
            await g.ainvoke(initial_state("M1"), config=s.config_for(tid))
            await g.ainvoke(initial_state("M1"), config=s.config_for(tid))

        async with (
            AsyncSqliteSaver.from_conn_string(str(db)) as src,
            AsyncPostgresSaver.from_conn_string(DSN) as dst,
        ):
            try:
                assert tid in m.sqlite_threads(db)
                await m.migrate_thread(src, dst, tid)
                report = await m.verify_thread(src, dst, tid)
                assert report["src_count"] == report["dst_count"] >= 2
                assert report["values_equal"] is True
                assert report["keys_equal"] is True
            finally:
                await dst.adelete_thread(tid)

    asyncio.run(flow())
