"""把 SQLite 里的历史 checkpoint 搬到 Postgres。

    uv run python -m persistence.migrate_sqlite_to_pg            # 干跑：只报告要迁什么
    uv run python -m persistence.migrate_sqlite_to_pg --apply    # 真写

## 为什么用 saver 接口而不是自己解 msgpack

SQLite 里存的是 msgpack 编码的整块 Checkpoint，还带 `channel_versions`、父链和
pending_writes。手工反序列化再拼 SQL，等于把 LangGraph 的内部结构复制一份到本项目里，
上游一旦改结构，这份代码就静默错。这里直接 `alist()` 读、`aput()/aput_writes()` 写，
序列化格式交给官方实现。

## 会迁走什么、不会迁走什么

- 迁：每个线程的全部 checkpoint（含父链）+ 每一步的 pending_writes；
- 不迁：`writes` 表里没有归属 checkpoint 的孤儿行（读不出来就不猜）；
- 不迁：任务台账（那本来就在内存里，没有历史可迁）。

## 限制（如实写在前面）

- checkpoint_id 会在目标库重新生成，父链按写入顺序重建。**语义上状态一致**，
  但两边 id 不同，不能拿 id 互相对照；
- 线程名里带 job_id，所以迁过去也基本不会再用到——它的价值是「历史可追溯」，
  不是「接着昨天的活干」；
- 同一线程在目标库已存在时默认跳过，避免重复写；确要覆盖用 `--force`（会先删目标线程）。
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
from pathlib import Path

from config.loader import get_settings, resolve_postgres_dsn
from persistence.pg_compat import ensure_selector_policy


def sqlite_threads(db: Path) -> list[str]:
    if not db.exists():
        return []
    with sqlite3.connect(db) as conn:
        return [r[0] for r in conn.execute("select distinct thread_id from checkpoints order by 1")]


async def pg_threads(dst) -> set[str]:
    # saver 的连接用的是 dict_row，取列名而不是下标
    async with dst.conn.cursor() as cur:  # type: ignore[union-attr]
        await cur.execute("select distinct thread_id from checkpoints")
        return {r["thread_id"] for r in await cur.fetchall()}


def _group_writes(pending: list[tuple]) -> dict[str, list[tuple[str, object]]]:
    """`[(task_id, channel, value), ...]` → `{task_id: [(channel, value), ...]}`。"""
    grouped: dict[str, list[tuple[str, object]]] = {}
    for row in pending:
        task_id, channel, value = row[0], row[1], row[2]
        grouped.setdefault(task_id, []).append((channel, value))
    return grouped


async def migrate_thread(src, dst, thread_id: str) -> dict[str, object]:
    cfg = {"configurable": {"thread_id": thread_id}}
    tuples = [t async for t in src.alist(cfg, limit=None)]
    for tup in tuples:
        versions = tup.checkpoint.get("channel_versions", {})
        await dst.aput(tup.config, tup.checkpoint, tup.metadata, versions)
        for task_id, writes in _group_writes(tup.pending_writes or []).items():
            await dst.aput_writes(tup.config, writes, task_id)
    return {"checkpoints": len(tuples)}


async def verify_thread(src, dst, thread_id: str) -> dict[str, object]:
    """三个口径一起看：存档点数、最新状态、下一步该跑什么。"""
    cfg = {"configurable": {"thread_id": thread_id}}
    src_tuples = [t async for t in src.alist(cfg, limit=None)]
    dst_tuples = [t async for t in dst.alist(cfg, limit=None)]
    src_state = await src.aget(cfg)
    dst_state = await dst.aget(cfg)
    src_values = (src_state or {}).get("channel_values", {})
    dst_values = (dst_state or {}).get("channel_values", {})
    return {
        "src_count": len(src_tuples),
        "dst_count": len(dst_tuples),
        "values_equal": src_values == dst_values,
        "keys_equal": sorted(src_values) == sorted(dst_values),
        # next 决定「还能不能接着跑」：值对了但 next 不同，等于迁了个死存档
        "next_equal": (src_state or {}).get("next") == (dst_state or {}).get("next"),
    }


async def run(apply: bool, force: bool) -> int:
    from config.loader import ROOT

    settings = get_settings()
    # 源路径始终从 dsn 解析：迁移时目标可能已经是 postgres，不能反过来依赖它
    raw = settings.graph.dsn.removeprefix("sqlite:///")
    db = Path(raw) if Path(raw).is_absolute() else (ROOT / raw).resolve()
    dsn = resolve_postgres_dsn(settings)

    threads = sqlite_threads(db)
    print(f"[迁移] 源：{db}（{len(threads)} 个线程）")
    print(f"[迁移] 目标：{dsn}")
    if not threads:
        print("[迁移] 源里没有 checkpoint，无事可做")
        return 0

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    failures = 0
    async with (
        AsyncSqliteSaver.from_conn_string(str(db)) as src,
        AsyncPostgresSaver.from_conn_string(dsn) as dst,
    ):
        existing = await pg_threads(dst)
        for tid in threads:
            if tid in existing and not force:
                print(f"[跳过] {tid} 目标库已存在（要覆盖加 --force）")
                continue
            if not apply:
                cfg = {"configurable": {"thread_id": tid}}
                n = len([t async for t in src.alist(cfg, limit=None)])
                print(f"[干跑] {tid}：将写入 {n} 个存档点")
                continue

            if tid in existing and force:
                await dst.adelete_thread(tid)
            await migrate_thread(src, dst, tid)
            report = await verify_thread(src, dst, tid)
            ok = (
                report["src_count"] == report["dst_count"]
                and report["values_equal"]
                and report["keys_equal"]
                and report["next_equal"]
            )
            mark = "OK" if ok else "MISMATCH"
            print(
                f"[{mark}] {tid}：存档点 {report['src_count']} -> {report['dst_count']}，"
                f"最新状态一致={report['values_equal']}，下一步一致={report['next_equal']}"
            )
            if not ok:
                failures += 1

    if not apply:
        print("[迁移] 干跑结束；确认后加 --apply 真正写入")
        return 0
    print(f"[迁移] 完成：{len(threads)} 个线程，{failures} 个校验不一致")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite → Postgres checkpoint 迁移")
    parser.add_argument("--apply", action="store_true", help="真正写入；不加则只干跑")
    parser.add_argument("--force", action="store_true", help="目标库已有同线程时先删再写")
    args = parser.parse_args()

    note = ensure_selector_policy()
    print(f"[迁移] 事件循环：{note}")
    return asyncio.run(run(apply=args.apply, force=args.force))


if __name__ == "__main__":
    raise SystemExit(main())
