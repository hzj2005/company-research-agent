"""真实持久化 checkpointer（S2）。

- 使用 `AsyncSqliteSaver`（aiosqlite 驱动）落盘，配合 async 节点与 `ainvoke`；
  同步 `SqliteSaver` 的 `aget_tuple` 会抛 NotImplementedError，不能用于 async 图。
- 进程重启后可从同一 db 文件恢复；禁止用 InMemorySaver 冒充持久化。
- `interrupt()` / `Command(resume=...)` 的恢复能力由这里提供，S6 直接依赖。

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

from config.loader import Settings, get_settings, resolve_checkpoint_path

if TYPE_CHECKING:  # pragma: no cover
    from langgraph.graph.state import CompiledStateGraph, StateGraph


class CheckpointSession(AbstractAsyncContextManager["CheckpointSession"]):
    """管理 AsyncSqliteSaver 生命周期；退出时正确关闭底层连接。

    传入 path 可指向临时文件（测试用）；不传则按 config/settings.yaml 的 dsn 解析。
    """

    def __init__(self, settings: Settings | None = None, path: Path | str | None = None):
        self._settings = settings or get_settings()
        self.path = Path(path) if path is not None else resolve_checkpoint_path(self._settings)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cm: Any = None
        self.saver: AsyncSqliteSaver | None = None

    async def __aenter__(self) -> "CheckpointSession":
        self._cm = AsyncSqliteSaver.from_conn_string(str(self.path))
        self.saver = await self._cm.__aenter__()
        return self

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
