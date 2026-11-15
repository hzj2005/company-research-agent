"""Windows 上的事件循环兼容层。

psycopg 3 的**异步**模式不支持 Windows 默认的 `ProactorEventLoop`，一连接就抛：

    psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async mode.

两处会撞上，处置方式不同：

1. **CLI 脚本**（建表 / 迁移）：`asyncio.run()` 之前调 `ensure_selector_policy()` 即可；
2. **uvicorn**：它不看全局策略，而是自己传 loop factory
   （`Server.run()` → `asyncio_run(..., loop_factory=config.get_loop_factory())`），
   没开 reload/workers 时在 Windows 上固定给 Proactor。所以要显式指：

       uv run uvicorn application:app --loop persistence.pg_compat:selector_loop

Linux/macOS 不受影响，本模块的函数会原样返回。
"""

from __future__ import annotations

import asyncio
import sys


def is_windows() -> bool:
    return sys.platform == "win32"


def ensure_selector_policy() -> str:
    """把全局事件循环策略切到 Selector（仅 Windows），返回一句可打印的说明。"""
    if not is_windows():
        return "非 Windows，保持默认事件循环"
    selector_policy = asyncio.WindowsSelectorEventLoopPolicy  # type: ignore[attr-defined]
    if isinstance(asyncio.get_event_loop_policy(), selector_policy):
        return "已是 SelectorEventLoop，无需切换"
    asyncio.set_event_loop_policy(selector_policy())
    return "Windows 默认 Proactor 不被 psycopg 异步支持，已切换为 SelectorEventLoop"


def selector_loop(use_subprocess: bool = False) -> asyncio.AbstractEventLoop:
    """给 uvicorn 的 `--loop` 用：调用后必须**返回循环实例**，不是返回类。

    uvicorn 对自定义 loop 的约定是「可调用对象，调用一次得到一个 loop」；
    返回类会变成 `set_debug() missing 1 required positional argument` 那种怪错。
    """
    return asyncio.SelectorEventLoop()
