"""R8-P3：`/chat` 接口与多轮会话测试。

三条约定必须成立：
1. 追问**不建任务**（不花检索额度）；
2. 判定后锁定路由（`route_locked`），图里不再重复调一次模型；
3. 多轮继承公司——「那新闻呢」不必重复公司名。

HTTP 层用 TestClient；后台任务替换成 no-op，避免测试真的跑图写库。
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import application
from config.loader import get_settings
from graph.nodes.router import decide_route
from graph.run import run_research


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(application, "process_research", _noop)
    return TestClient(application.app)


# ---------- 判定层（复用节点逻辑，不重复实现） ----------


def test_decide_route_reuses_node_logic() -> None:
    d = asyncio.run(decide_route("Notion 的融资和新闻", "", get_settings()))
    assert (d["company"], d["sections"]) == ("Notion", ["financial", "news"])
    assert d["need_clarify"] is False


def test_decide_route_uses_session_company_as_hint() -> None:
    """多轮：本句没说公司时，用会话里的公司当提示。"""
    d = asyncio.run(decide_route("那新闻呢", "Notion", get_settings()))
    assert d["company"] == "Notion"
    assert d["sections"] == ["news"]
    assert d["need_clarify"] is False


# ---------- HTTP：受理 / 追问 / 继承 ----------


def test_chat_accepts_and_returns_scope(client: TestClient) -> None:
    body = client.post("/chat", json={"message": "Notion 的财务数据"}).json()

    assert body["type"] == "accepted"
    assert body["company"] == "Notion"
    assert body["sections"] == ["financial"]
    assert body["stream"] == f"/research/{body['job_id']}/stream"
    assert body["thread_id"]


def test_chat_clarifies_without_creating_job(client: TestClient) -> None:
    body = client.post("/chat", json={"message": "帮我查一下 Notion"}).json()

    assert body["type"] == "clarify"
    assert body["clarify_kind"] == "scope"
    assert "Notion" in body["question"]
    assert "job_id" not in body, "追问不该建任务"
    assert [o["key"] for o in body["options"]] == [
        "company", "industry", "financial", "news", "all",
    ]


def test_chat_followup_after_clarify_keeps_company(client: TestClient) -> None:
    first = client.post("/chat", json={"message": "帮我查一下 Notion"}).json()
    second = client.post(
        "/chat",
        json={"message": "财务", "thread_id": first["thread_id"]},
    ).json()

    assert second["type"] == "accepted"
    assert second["company"] == "Notion", "追问后的下一句必须记得是哪家公司"
    assert second["sections"] == ["financial"]


def test_chat_multi_turn_inherits_company(client: TestClient) -> None:
    first = client.post("/chat", json={"message": "Notion 的财务"}).json()
    second = client.post(
        "/chat",
        json={"message": "那它的新闻呢", "thread_id": first["thread_id"]},
    ).json()

    assert second["type"] == "accepted"
    assert second["company"] == "Notion"
    assert second["sections"] == ["news"], "换范围不该把上一轮的栏目一起带上"


def test_chat_rejects_empty_message(client: TestClient) -> None:
    assert client.post("/chat", json={"message": "   "}).status_code == 422


# ---------- 锁定路由：图里不重复调模型 ----------


def test_locked_route_does_not_re_decide() -> None:
    settings = get_settings()
    with tempfile.TemporaryDirectory() as td:
        state, _ = asyncio.run(
            run_research(
                "Notion", settings, Path(td) / "p.db",
                user_message="Notion 的财务数据",
                requested_sections=["financial"],
                route_locked=True,
                collect_trace=True,
            )
        )

    assert state["route_meta"]["source"] == "locked"
    assert state["requested_sections"] == ["financial"]
    assert state["report"].count("## ") == 2, "只渲染财务 + References"
