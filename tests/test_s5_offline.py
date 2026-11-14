"""S5-B 硬保证：完整跑一次图，全程不建立任何外部网络连接。

不是「我以为没调」——把 `socket.socket.connect` 换成守卫：本地回环放行
（Windows 的 asyncio ProactorEventLoop 用 socketpair 做 self-pipe），任何非回环
地址一律记录并抛错。Tavily / 真实模型 API 一旦被触发就会立刻失败。
"""

from __future__ import annotations

import asyncio
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

from config.loader import get_settings
from graph.run import run_research


def test_full_graph_makes_zero_external_connections() -> None:
    original = socket.socket.connect
    external_attempts: list[object] = []

    def guarded(self: socket.socket, address: object, *args: object, **kwargs: object) -> object:
        host = str(address[0]) if isinstance(address, tuple) and address else str(address)
        if host.startswith("127.") or host in ("::1", "localhost"):
            return original(self, address, *args, **kwargs)
        external_attempts.append(address)
        raise AssertionError(f"检测到外部连接 {address!r}：真实调用应为 0 次")

    with patch.object(socket.socket, "connect", guarded):
        with tempfile.TemporaryDirectory() as td:
            state, trace = asyncio.run(
                run_research("Notion", get_settings(), Path(td) / "p.db", collect_trace=True)
            )

    assert external_attempts == [], "任何外部连接都意味着消耗了 Tavily/模型额度"
    assert len(state["report"]) == 822
    assert trace.count("research") == 1
    assert socket.socket.connect is original, "守卫必须被还原"
