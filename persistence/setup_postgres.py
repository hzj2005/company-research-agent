"""一次性建表：Postgres 的 checkpoint 三张表 + 任务台账两张表。

    uv run python -m persistence.setup_postgres

幂等：重复跑不会报错，也不会清数据。

之所以做成**显式一条命令**而不是「连接时自动建表」：
自动建表会让每次启动多一次往返，而且把「库还没准备好」这类问题藏起来；
显式命令失败时你能直接看到是哪一步、哪张表。
"""

from __future__ import annotations

import asyncio

import psycopg
from psycopg.rows import dict_row

from config.loader import get_settings, resolve_postgres_dsn
from persistence.job_store import PostgresJobStore, setup_schema, table_counts


async def list_tables(dsn: str) -> list[str]:
    async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as conn:
        cur = await conn.execute(
            "select tablename from pg_tables where schemaname = 'public' order by tablename"
        )
        return [row["tablename"] for row in await cur.fetchall()]


async def setup(dsn: str) -> dict[str, object]:
    # 1) checkpoint 三张表由官方 saver 自己建，不手写 DDL
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        await saver.setup()

    # 2) 任务台账两张表由我们自己的 DDL 建
    store = await PostgresJobStore(dsn).open()
    try:
        await setup_schema(store)
        counts = await table_counts(store)
    finally:
        await store.close()

    return {"tables": await list_tables(dsn), "rows": counts}


def main() -> int:
    from persistence.pg_compat import ensure_selector_policy

    note = ensure_selector_policy()
    settings = get_settings()
    dsn = resolve_postgres_dsn(settings)
    result = asyncio.run(setup(dsn))
    tables = result["tables"]
    rows = result["rows"]
    print(f"[S12] 事件循环：{note}")
    print(f"[S12] 建表完成 -> {len(tables)} 张表：{', '.join(tables)}")
    print(f"[S12] 当前行数：{rows}（新库应全为 0）")
    print("[S12] 下一步：.env 里设 CHECKPOINTER=postgres、JOB_STORE=postgres")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
