"""S5-B 硬保证：完整跑一次图，全程不建立任何外部网络连接。

不是「我以为没调」——把 `socket.socket.connect` 换成守卫：本地回环放行
（Windows 的 asyncio ProactorEventLoop 用 socketpair 做 self-pipe），任何非回环
地址一律记录并抛错。Tavily / 真实模型 API 一旦被触发就会立刻失败。
"""

from __future__ import annotations

import asyncio
import socket
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

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
    assert len(state["report"]) == 772
    assert trace.count("research") == 1
    assert socket.socket.connect is original, "守卫必须被还原"


def test_research_endpoint_makes_zero_external_connections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """补强 8.4 验收：真发 POST /research 也在禁外网守卫下完成。

    CLI 路径的守卫只证明 `run_research` 离网；长驻 FastAPI 入口同样要能自证
    0 次外部连接，否则「全程 0 次调用」只是配置层面的推断。
    """
    import application
    from backend.classes.state import job_status
    from fastapi.testclient import TestClient

    original_connect = socket.socket.connect
    original_process = application.process_research
    attempts: list[object] = []

    async def _with_temp_db(job_id: str, data: object, db_path: Path | None = None, **kw: object) -> None:
        await original_process(job_id, data, db_path=tmp_path / "api.db", **kw)

    def guarded(self: socket.socket, address: object, *args: object, **kwargs: object) -> object:
        host = str(address[0]) if isinstance(address, tuple) and address else str(address)
        if host.startswith("127.") or host in ("::1", "localhost"):
            return original_connect(self, address, *args, **kwargs)
        attempts.append(address)
        raise AssertionError(f"外部连接 {address!r}：/research 应 0 次外部调用")

    monkeypatch.setattr(application, "process_research", _with_temp_db)
    with patch.object(socket.socket, "connect", guarded):
        with TestClient(application.app) as client:
            response = client.post("/research", json={"company": "Notion"})
            assert response.status_code == 200, response.text
            jid = response.json()["job_id"]
            state: dict = {}
            for _ in range(80):
                state = dict(job_status.get(jid, {}))
                if state.get("status") in ("completed", "failed"):
                    break
                time.sleep(0.1)

    assert state.get("status") == "completed", state
    assert len(state["report"]) == 772
    assert attempts == [], "任何外部连接都意味着消耗了 Tavily/模型额度"
    assert socket.socket.connect is original_connect, "守卫必须被还原"
