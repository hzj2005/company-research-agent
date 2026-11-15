"""S12.2：任务台账与报告落 Postgres。

替代两样东西：
1. 上游的 `MongoDBService`（可选、同步、没配就整个功能消失）；
2. `job_status` 进程内字典（重启即丢、多进程不共享）。

两张表就够，不搞 ORM：

- `jobs`：一次调研一行，记状态、当前节点、错误、入参；
- `reports`：报告正文单独一张表，避免每次查状态都把几十 KB 的正文拖出来。

写操作全部 async（psycopg 3），所以不会像同步 pymongo 那样堵住事件循环。
"""

from __future__ import annotations

import json
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

# 幂等：重复执行不会报错，也不会清数据
SCHEMA_SQL = """
create table if not exists jobs (
    job_id       text primary key,
    company      text not null,
    status       text not null,
    current_step text,
    error        text,
    inputs       jsonb not null default '{}'::jsonb,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);
create index if not exists jobs_created_at_idx on jobs (created_at desc);
create index if not exists jobs_status_idx on jobs (status);

create table if not exists reports (
    job_id     text primary key references jobs(job_id) on delete cascade,
    report     text not null,
    created_at timestamptz not null default now()
);
"""

# update_job 允许改的字段；白名单外的一律拒绝，避免拼 SQL 时被注入
_UPDATABLE = {"status", "current_step", "error", "company"}

REQUIRED_TABLES = ("jobs", "reports")


class PostgresJobStore:
    """连接池 + 四条语句。没有 ORM，也没有隐式建表。"""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._pool: AsyncConnectionPool | None = None

    async def open(self) -> "PostgresJobStore":
        if self._pool is None:
            self._pool = AsyncConnectionPool(
                conninfo=self.dsn, open=False, kwargs={"row_factory": dict_row}
            )
            await self._pool.open()
            await self._pool.wait()
        return self

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> AsyncConnectionPool:
        if self._pool is None:
            raise RuntimeError("PostgresJobStore 必须先 await open()")
        return self._pool

    async def create_job(self, job_id: str, payload: dict[str, Any]) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "insert into jobs (job_id, company, status, inputs) values (%s, %s, %s, %s)"
                " on conflict (job_id) do nothing",
                (job_id, str(payload.get("company", "")), "pending", json.dumps(payload, ensure_ascii=False)),
            )

    async def update_job(self, job_id: str, **fields: Any) -> None:
        unknown = set(fields) - _UPDATABLE
        if unknown:
            raise ValueError(f"jobs 表没有这些字段：{sorted(unknown)}")
        if not fields:
            return
        assignments = ", ".join(f"{name} = %s" for name in fields)
        values = list(fields.values())
        async with self.pool.connection() as conn:
            await conn.execute(
                f"update jobs set {assignments}, updated_at = now() where job_id = %s",
                (*values, job_id),
            )

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "select job_id, company, status, current_step, error, inputs,"
                " created_at, updated_at from jobs where job_id = %s",
                (job_id,),
            )
            return await cur.fetchone()

    async def store_report(self, job_id: str, report: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "insert into reports (job_id, report) values (%s, %s)"
                " on conflict (job_id) do update set report = excluded.report",
                (job_id, report),
            )

    async def get_report(self, job_id: str) -> dict[str, Any] | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "select job_id, report, created_at from reports where job_id = %s", (job_id,)
            )
            row = await cur.fetchone()
        return {"report": row["report"]} if row else None

    async def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        """按时间倒序列出最近的任务，用来验收「重启后还查得到」。"""
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "select job_id, company, status, created_at from jobs"
                " order by created_at desc limit %s",
                (limit,),
            )
            return list(await cur.fetchall())


async def setup_schema(store: PostgresJobStore) -> None:
    async with store.pool.connection() as conn:
        await conn.execute(SCHEMA_SQL)


async def table_counts(store: PostgresJobStore) -> dict[str, int]:
    """建表后回读一次行数：让「建成功了」有可验证的证据，而不是只看日志。"""
    out: dict[str, int] = {}
    async with store.pool.connection() as conn:
        for table in REQUIRED_TABLES:
            cur = await conn.execute(f"select count(*) as n from {table}")
            row = await cur.fetchone()
            out[table] = int(row["n"]) if row else 0
    return out


async def missing_tables(store: PostgresJobStore) -> list[str]:
    """哪些表还不存在。

    启动时查一次，比等第一个请求 500 强：`to_regclass` 对不存在的表返回 null，
    不用去 catch UndefinedTable，也不会把「库连上了但没建表」当成连接问题。
    """
    missing: list[str] = []
    async with store.pool.connection() as conn:
        for table in REQUIRED_TABLES:
            cur = await conn.execute("select to_regclass(%s) as reg", (f"public.{table}",))
            row = await cur.fetchone()
            if row is None or row["reg"] is None:
                missing.append(table)
    return missing
