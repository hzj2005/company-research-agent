"""真实持久化 checkpointer（S2 / S12）。

两种后端，**二选一**，靠 `CHECKPOINTER` 环境变量切换：

- `sqlite`（默认）：`AsyncSqliteSaver` 落盘到 `data/checkpoints.db`，零运维，
  测试和离线复现都用它；
- `postgres`：`AsyncPostgresSaver` 落到 `POSTGRES_DSN` 指向的库，多进程/多实例
  共享同一份存档。

两者对外接口完全一样（`compile()` / `config_for()`），所以调用方不需要知道用的是哪个。
**不静默退回**：选了 postgres 却没配 DSN、或表没建，一律抛错并给出下一步命令。

为什么 async：图里是 async 节点 + `ainvoke`，同步 `SqliteSaver` 的 `aget_tuple`
会抛 NotImplementedError；同理 Postgres 也必须用 `aio` 版本。

用法：
    async with CheckpointSession() as session:
        compiled = session.compile(workflow)
        await compiled.ainvoke(state, config=session.config_for(thread_id))
        snapshot = await compiled.aget_state(session.config_for(thread_id))
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any, TYPE_CHECKING

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from config.loader import (
    Settings,
    get_settings,
    resolve_checkpoint_path,
    resolve_postgres_dsn,
)

if TYPE_CHECKING:  # pragma: no cover
    from langgraph.graph.state import CompiledStateGraph, StateGraph

# 同一进程里只探一次 schema：每来一个请求就查一次系统表是白花的往返
_SCHEMA_READY: set[str] = set()


def _looks_like_missing_schema(exc: BaseException) -> bool:
    """把「表不存在」和「连不上库」区分开——两者的处置完全不同。

    只用字符串匹配会误伤：`database "research" does not exist` 也含
    「does not exist」，但它要找的是建库，不是建表。所以先看异常类型，
    再看是不是在说 relation。
    """
    try:
        import psycopg

        if isinstance(exc, psycopg.errors.UndefinedTable):
            return True
    except Exception:  # pragma: no cover - psycopg 缺失时退化为字符串判断
        pass
    text = str(exc).lower()
    return "relation" in text and "does not exist" in text


class CheckpointSession(AbstractAsyncContextManager["CheckpointSession"]):
    """按配置管理 SQLite 或 Postgres saver 的生命周期。

    - 显式传 `path` 时**强制走 SQLite**：测试用它注入临时文件，不该被本机 .env 带走。
    - 不传 `path` 时按 `settings.graph.checkpointer` 决定。
    """

    def __init__(
        self,
        settings: Settings | None = None,
        path: Path | str | None = None,
        backend: str | None = None,
    ):
        self._settings = settings or get_settings()
        self._explicit_path = Path(path) if path is not None else None
        chosen = backend or self._settings.graph.checkpointer
        if chosen not in {"sqlite", "postgres"}:
            raise ValueError(f"未知的 checkpointer 后端：{chosen!r}（只支持 sqlite / postgres）")
        self.backend = "sqlite" if self._explicit_path else chosen
        self._cm: Any = None
        self.saver: Any = None
        self.dsn: str | None = None
        if self.backend == "sqlite":
            self.path = self._explicit_path or resolve_checkpoint_path(self._settings)
            self.path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.path = None
            self.dsn = resolve_postgres_dsn(self._settings)

    async def __aenter__(self) -> "CheckpointSession":
        if self.backend == "postgres":
            # 延迟导入：不用 Postgres 的人不该为它付 import 代价
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            self._cm = AsyncPostgresSaver.from_conn_string(self.dsn or "")
            self.saver = await self._cm.__aenter__()
            try:
                await self._require_schema()
            except BaseException:
                # 建表没做就退出时，别把半开的连接留在池子里
                await self._cm.__aexit__(None, None, None)
                self._cm, self.saver = None, None
                raise
        else:
            self._cm = AsyncSqliteSaver.from_conn_string(str(self.path))
            self.saver = await self._cm.__aenter__()
        return self

    async def _require_schema(self) -> None:
        """表没建时给一句能照做的报错，而不是让 psycopg 的 UndefinedTable 冒到用户脸上。"""
        assert self.dsn is not None
        if self.dsn in _SCHEMA_READY:
            return
        try:
            await self.saver.aget_tuple({"configurable": {"thread_id": "__schema_probe__"}})
        except Exception as exc:
            if _looks_like_missing_schema(exc):
                raise RuntimeError(
                    "Postgres 里还没有 checkpoint 表。先跑一次（幂等，可重复执行）："
                    "`uv run python -m persistence.setup_postgres`"
                ) from exc
            raise
        _SCHEMA_READY.add(self.dsn)

    async def __aexit__(self, *exc_info: object) -> bool | None:
        try:
            return await self._cm.__aexit__(*exc_info)
        finally:
            self.saver = None
            self._cm = None

    def compile(self, workflow: "StateGraph") -> "CompiledStateGraph":
        """带 checkpointer 编译；裸 compile() 只允许出现在 baseline 采集脚本里。"""
        if self.saver is None:
            raise RuntimeError("CheckpointSession 必须在 async with 块内使用")
        return workflow.compile(checkpointer=self.saver)

    def config_for(self, thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}
