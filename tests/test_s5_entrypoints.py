"""S5-B 8.4 验收：LangGraph Studio 与 FastAPI `/research` 都指向新图。

全程 fixture 模式、0 次真实 Tavily / 模型调用；`db_path` 注入让 checkpoint 落在
临时目录，不污染项目 `data/`。
"""

from __future__ import annotations

import asyncio
import importlib
import time
from pathlib import Path

import pytest

from backend.classes.state import job_status

EXPECTED_NODES = {
    "grounding", "research", "curate", "evidence_check",
    "rewrite_query", "degrade", "briefing",
}


def test_studio_entry_exports_the_new_graph() -> None:
    import langgraph_entry as entry

    nodes = set(entry.graph.get_graph().nodes.keys())
    assert EXPECTED_NODES <= nodes, "Studio 入口不能再是原版线性 DAG"
    assert not hasattr(entry, "Graph"), "不得再导出上游 backend.graph.Graph"
    # Server 注入 saver：顶层 compile 自身不带 checkpointer（AGENT.md 6.7 例外二）
    assert getattr(entry.graph, "checkpointer", None) is None


def test_studio_entry_reload_never_constructs_tavily_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """reload 会真的重新编译一次图；若碰了真实 SDK 应立刻失败。"""
    import tavily

    def _explode(*args: object, **kwargs: object) -> object:
        raise AssertionError("导入 Studio 入口不应构造 AsyncTavilyClient")

    monkeypatch.setattr(tavily, "AsyncTavilyClient", _explode)
    import langgraph_entry

    reloaded = importlib.reload(langgraph_entry)
    assert reloaded._settings.app.mode == "fixture"
    assert reloaded._settings.retrieval.live.enabled is False
    assert EXPECTED_NODES <= set(reloaded.graph.get_graph().nodes.keys())


def test_process_research_runs_new_graph_and_reports_progress(tmp_path: Path) -> None:
    import application

    jid = "s5-entry-direct-1"
    job_status[jid] = {"status": "pending", "company": "Notion"}
    req = application.ResearchRequest(
        company="Notion",
        # 请求体 key 明确不消费：不得出现在任何状态/日志字段里
        tavily_api_key="SHOULD_NOT_BE_USED",
        openrouter_api_key="SHOULD_NOT_BE_USED",
    )
    asyncio.run(application.process_research(jid, req, db_path=tmp_path / "p.db"))

    st = job_status[jid]
    assert st["status"] == "completed", st
    assert len(st["report"]) == 772, "fixture sufficient 报告应与 CLI 完全一致"
    assert st["current_step"] in EXPECTED_NODES
    assert "SHOULD_NOT_BE_USED" not in str(st), "请求体里的 key 不能被消费或外泄"


def test_research_endpoint_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """真发一次 POST /research，等后台任务完成，核对 job_status。"""
    from fastapi.testclient import TestClient

    import application

    original = application.process_research

    async def _with_temp_db(job_id: str, data: object, **kw: object) -> None:
        await original(job_id, data, db_path=tmp_path / "api.db", **kw)

    monkeypatch.setattr(application, "process_research", _with_temp_db)
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


def test_upstream_graph_not_used_by_entrypoints() -> None:
    """防回退：只匹配代码语句，不撞上 docstring 里对原版的文字说明。"""
    import re

    root = Path(__file__).resolve().parents[1]
    app_src = (root / "application.py").read_text(encoding="utf-8")
    entry_src = (root / "langgraph_entry.py").read_text(encoding="utf-8")
    both = app_src + entry_src
    assert not re.search(r"^\s*from backend\.graph import Graph", both, flags=re.M)
    assert not re.search(r"^\s*graph\s*=\s*Graph\(", entry_src, flags=re.M)
    assert not re.search(r"^\s*graph\s*=\s*Graph\(", app_src, flags=re.M)
    assert "build_graph(" in app_src and "build_graph(" in entry_src


def test_research_rejects_blank_company() -> None:
    """空公司名不能 200：否则会真的跑一次没有意义的调研，还在台账留一条记录。"""
    from fastapi.testclient import TestClient

    import application

    with TestClient(application.app) as client:
        for payload in ({"company": ""}, {"company": "   "}, {}):
            response = client.post("/research", json=payload)
            assert response.status_code == 422, f"{payload} -> {response.status_code}"


def test_research_strips_company_whitespace() -> None:
    """`  Notion  ` 存进台账的应该是 `Notion`，不是带空格的原文。"""
    import time

    from fastapi.testclient import TestClient

    import application
    from backend.classes.state import job_status

    with TestClient(application.app) as client:
        response = client.post("/research", json={"company": "  Notion  "})
        assert response.status_code == 200
        jid = response.json()["job_id"]
        assert job_status[jid]["company"] == "Notion"
        for _ in range(80):
            if job_status[jid].get("status") in ("completed", "failed"):
                break
            time.sleep(0.05)


def test_health_endpoints_answer() -> None:
    """/api/health 是给外部探活的别名，不能是 404。"""
    from fastapi.testclient import TestClient

    import application

    with TestClient(application.app) as client:
        for path in ("/health", "/api/health", "/"):
            response = client.get(path)
            assert response.status_code == 200, f"{path} -> {response.status_code}"


def test_config_reports_mode_and_key_requirements() -> None:
    """前端靠这两个字段决定要不要拦提交；fixture 模式不该要求任何 key。"""
    from fastapi.testclient import TestClient

    import application

    with TestClient(application.app) as client:
        config = client.get("/config").json()
    assert config["app_mode"] in ("fixture", "live")
    assert config["requires_llm_key"] is (config["app_mode"] == "live")
    for key in ("openrouter_configured", "openai_configured", "dashscope_configured", "tavily_configured"):
        assert isinstance(config[key], bool), key


def test_history_endpoint_lists_runs_and_filters_by_company() -> None:
    """历史列表：有记录能列出来，按公司筛能筛到，字段够前端渲染一张表。"""
    import time

    from fastapi.testclient import TestClient

    import application

    with TestClient(application.app) as client:
        # 先制造两条记录
        for name in ("HistoryProbe", "OtherProbe"):
            r = client.post("/research", json={"company": name})
            assert r.status_code == 200
        time.sleep(1.5)

        listed = client.get("/research", params={"limit": 50})
        assert listed.status_code == 200
        body = listed.json()
        assert body["source"] in ("postgres", "memory")
        names = [row["company"] for row in body["jobs"]]
        assert "HistoryProbe" in names and "OtherProbe" in names

        filtered = client.get("/research", params={"company": "historyprobe"}).json()
        assert [row["company"] for row in filtered["jobs"]] == ["HistoryProbe"]

        row = filtered["jobs"][0]
        for field in ("job_id", "company", "status", "created_at", "has_report", "report_chars"):
            assert field in row, field
