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

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

T = TypeVar("T")


async def _retry_once(op: Callable[[], Awaitable[T]]) -> T:
    """连接被服务端断开时重试一次。

    场景很具体：Postgres 重启（换数据目录、改配置、容器重建）后，池子里还留着
    **已经断开的旧连接**；第一次拿到它的请求会抛
    `OperationalError: could not receive data from server`，接口直接 500。
    psycopg_pool 会在归还时丢弃坏连接，所以重试一次就能拿到新连接——但必须有人重试。
    """
    try:
        return await op()
    except psycopg.OperationalError:
        await asyncio.sleep(0.05)  # 给池子一点时间把坏连接丢掉
        return await op()

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
                conninfo=self.dsn,
                open=False,
                # 起步只要一条连接：默认 min_size=4 时，若单次连接偏慢（Windows 上
                # `localhost` 先走 IPv6 能慢到 8 秒），4 条就把 30 秒初始化预算吃光。
                min_size=1,
                max_size=8,
                timeout=10,  # 连不上就早点报错，别让启动挂 30 秒
                kwargs={"row_factory": dict_row},
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
        async def op() -> None:
            async with self.pool.connection() as conn:
                await conn.execute(
                    "insert into jobs (job_id, company, status, inputs) values (%s, %s, %s, %s)"
                    " on conflict (job_id) do nothing",
                    (job_id, str(payload.get("company", "")), "pending",
                     json.dumps(payload, ensure_ascii=False)),
                )

        await _retry_once(op)

    async def update_job(self, job_id: str, **fields: Any) -> None:
        unknown = set(fields) - _UPDATABLE
        if unknown:
            raise ValueError(f"jobs 表没有这些字段：{sorted(unknown)}")
        if not fields:
            return
        assignments = ", ".join(f"{name} = %s" for name in fields)
        values = list(fields.values())

        async def op() -> None:
            async with self.pool.connection() as conn:
                await conn.execute(
                    f"update jobs set {assignments}, updated_at = now() where job_id = %s",
                    (*values, job_id),
                )

        await _retry_once(op)

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        async def op() -> dict[str, Any] | None:
            async with self.pool.connection() as conn:
                cur = await conn.execute(
                    "select job_id, company, status, current_step, error, inputs,"
                    " created_at, updated_at from jobs where job_id = %s",
                    (job_id,),
                )
                return await cur.fetchone()

        return await _retry_once(op)

    async def store_report(self, job_id: str, report: str) -> None:
        async def op() -> None:
            async with self.pool.connection() as conn:
                await conn.execute(
                    "insert into reports (job_id, report) values (%s, %s)"
                    " on conflict (job_id) do update set report = excluded.report",
                    (job_id, report),
                )

        await _retry_once(op)

    async def get_report(self, job_id: str) -> dict[str, Any] | None:
        async def op() -> dict[str, Any] | None:
            async with self.pool.connection() as conn:
                cur = await conn.execute(
                    "select job_id, report, created_at from reports where job_id = %s", (job_id,)
                )
                row = await cur.fetchone()
            return {"report": row["report"]} if row else None

        return await _retry_once(op)

    async def list_jobs(
        self, limit: int = 20, company: str | None = None
    ) -> list[dict[str, Any]]:
        """按时间倒序列出历史任务，附带「有没有报告」和报告字数。

        `company` 用模糊匹配（ilike），大小写和前后空格都不敏感 —— 用户搜过
        `Nvidia` 和 `英伟达`，写死等值匹配会漏掉一半记录。
        """
        limit = max(1, min(int(limit), 100))
        sql = (
            "select j.job_id, j.company, j.status, j.current_step, j.error,"
            " j.created_at, j.updated_at,"
            " (r.job_id is not null) as has_report,"
            " coalesce(length(r.report), 0) as report_chars"
            " from jobs j left join reports r on r.job_id = j.job_id"
        )
        params: list[Any] = []
        if company:
            sql += " where j.company ilike %s"
            params.append(f"%{company.strip()}%")
        sql += " order by j.created_at desc limit %s"
        params.append(limit)
        async def op() -> list[dict[str, Any]]:
            async with self.pool.connection() as conn:
                cur = await conn.execute(sql, params)
                return list(await cur.fetchall())

        return await _retry_once(op)

    async def interrupt_stale(
        self, reason: str, job_ids: list[str] | None = None
    ) -> int:
        """把「进程早没了、状态还停在 pending/processing/reviewing」的任务收尾。

        `job_status` 是进程内字典，所以只要进程重启过，库里所有非终态任务就已经没人
        推进了；不收尾的话历史列表里会永远挂着 pending（12.30 记录过两条这样的脏数据）。
        本方法只在**单 worker** 前提下成立：多 worker 时一个进程启动会误杀另一个进程
        正在跑的任务，这条限制写在 docs/POSTGRES.md §7。

        `waiting_review` 不在收尾范围：它等人来提交决定，是**有意停住**的终态前状态，
        收了等于把用户的复核请求作废。

        `job_ids` 只用于定向收尾（测试不想动别人的行）；启动时传 None = 全表。
        """
        sql = (
            "update jobs set status = 'failed', error = %s, updated_at = now()"
            " where status in ('pending', 'processing', 'reviewing')"
        )
        params: list[Any] = [reason]
        if job_ids is not None:
            if not job_ids:
                return 0
            sql += " and job_id = any(%s)"
            params.append(list(job_ids))

        async def op() -> int:
            async with self.pool.connection() as conn:
                cur = await conn.execute(sql, tuple(params))
                return cur.rowcount

        return await _retry_once(op)


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
