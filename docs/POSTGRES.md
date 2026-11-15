# Postgres 运行手册（S12）

> 一句话：图的存档与任务台账都可以放 Postgres；**测试和离线复现仍然用 SQLite**。
> 两者二选一，不会同时写两份。

## 1. 什么时候需要

| 场景 | 用哪个 |
|---|---|
| 跑测试、离线复现、`--verify` 出处表 | SQLite（默认，零运维） |
| 多进程/多实例、想证明「重启还能查」 | Postgres |

## 2. 三步起起来

```bash
# 1) 起库（只起数据库，不牵引整个应用）
docker compose -f docker-compose.postgres.yml up -d
docker compose -f docker-compose.postgres.yml ps        # 等 STATUS 变 healthy

# 2) 建表（幂等；checkpoint 4 张 + 台账 2 张）
uv run python -m persistence.setup_postgres

# 3) 在 .env 里选后端
#    CHECKPOINTER=postgres
#    POSTGRES_DSN=postgresql://postgres:devpass@localhost:5432/research
#    JOB_STORE=postgres
```

建表成功会打印六张表：

```
checkpoint_blobs, checkpoint_migrations, checkpoint_writes, checkpoints, jobs, reports
```

## 3. 跑服务（Windows 有个坑）

**Windows 上不能直接用 `uvicorn application:app`**：psycopg 的异步模式不支持 Windows 默认的
`ProactorEventLoop`，会抛 `psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop'`。

```bash
# 方式 A：显式指定事件循环（推荐，稳定）
uv run uvicorn application:app --port 8000 --loop persistence.pg_compat:selector_loop

# 方式 B：带 --reload（uvicorn 在子进程模式下自己会用 Selector）
uv run uvicorn application:app --reload --port 8000
```

Linux/macOS 无此问题，正常 `uvicorn application:app` 即可。

## 4. 验证真的落库了

```bash
# 接口侧：提交 → 立刻查台账（旧版这里是 501）
curl -s -X POST localhost:8000/research -H 'Content-Type: application/json' -d '{"company":"Notion"}'
curl -s localhost:8000/research/<job_id>

# 库侧：行数 + 最新任务
docker exec pj-pg psql -U postgres -d research \
  -c "select (select count(*) from checkpoints) cp, (select count(*) from jobs) jobs;"
```

**重启服务再查同一个 job_id** —— 还能查到，才算真的持久化（内存版会 404）。

## 5. 迁移旧 SQLite 存档

```bash
uv run python -m persistence.migrate_sqlite_to_pg            # 干跑，只报告
uv run python -m persistence.migrate_sqlite_to_pg --apply    # 真写
uv run python -m persistence.migrate_sqlite_to_pg --apply --force   # 目标已存在则覆盖
```

脚本用 saver 接口复制（`alist()` 读、`aput()/aput_writes()` 写），不手工解 msgpack；
每迁一个线程都会校验「存档点数 / 最新状态值 / 字段集合」三项一致。

**限制**：目标库的 `checkpoint_id` 会重新生成，父链按写入顺序重建——语义一致，但 id 不能两边对照。
线程名里带 job_id，所以迁过去主要用于「历史可追溯」，不是「接着昨天的活干」。

## 6. 边界（没做的部分，别当成做了）

- **SSE 实时进度仍在进程内存**（`job_status`），所以多 worker 时：台账查得到，进度流可能对不上。
  这条是明确留下的，不是 bug。
- **评测产物、检索缓存、PDF 文件不进库**：它们是证据，要能 `git diff`、能离线回放、能被出处表引用。
- **SQLite 不会被删除**：它是测试后端与迁移对照，`data/checkpoints.db` 留着。

## 7. 回滚到 SQLite

```bash
# .env 里改回
CHECKPOINTER=sqlite
JOB_STORE=memory
```

Postgres 里的数据不清也不影响；想清空：

```bash
docker compose -f docker-compose.postgres.yml down -v   # 连数据卷一起删
```
