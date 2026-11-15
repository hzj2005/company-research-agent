"""S8.0 / S8.1：真实实测准备度与 dry-run 预演（0 次真实调用）。

**本文件 0 次真实 Tavily / 模型调用、0 次网络请求、0 credits 消耗。**
所有 live 配置都用 `load_settings(environ=...)` 显式构造，不依赖也不修改进程环境，
不读取用户级 TAVILY_API_KEY。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import socket
import tempfile
from pathlib import Path
from typing import Any

import pytest
from tavily import AsyncTavilyClient

import evals.live_dryrun as dryrun
from capabilities.retrieval import build_live_query, make_document_tool
from capabilities.tavily_retriever import (
    CallBudget,
    DryRunSentinel,
    LiveRetrievalDisabled,
    cache_key,
)
from config.loader import load_settings
from evals.run_eval import eval_offline_guard


def _dry_settings(**overrides: str) -> Any:
    return load_settings(environ={**dryrun.DRY_RUN_ENV, **overrides})


def _real_settings(**overrides: str) -> Any:
    return load_settings(
        environ={
            "APP_MODE": "live",
            "TAVILY_LIVE_ENABLED": "true",
            "TAVILY_MAX_CALLS": "3",
            "TAVILY_DRY_RUN": "false",
            "FEATURES_STRUCTURED_OUTPUT": "false",
            **overrides,
        }
    )


# ---------------------------------------------------------------- 缺陷回归：dry-run 无 key

def test_dry_run_runs_without_any_api_key() -> None:
    """修复前这里抛 MissingTavilyCredentials，.env.example 的承诺是空的。"""
    s = _dry_settings()
    budget = CallBudget(0, dry_run=True)
    with tempfile.TemporaryDirectory() as td:
        tool = make_document_tool(s, budget=budget, cache_dir=Path(td))
        out = asyncio.run(
            tool.ainvoke({"company": "Notion", "sections": ["company", "news"], "round_no": 0})
        )
    assert out == {"company": [], "news": []}
    assert budget.calls_made == 0
    assert budget.dry_runs == 2
    assert len(budget.queries) == 2
    assert all(q["executed"] is False and q["dry_run"] is True for q in budget.queries)


def test_dry_run_query_list_comes_from_production_code() -> None:
    """预演清单必须与 build_live_query / cache_key 逐条对得上，不许脚本另造。"""
    s = _dry_settings()
    budget = CallBudget(0, dry_run=True)
    with tempfile.TemporaryDirectory() as td:
        tool = make_document_tool(s, budget=budget, cache_dir=Path(td))
        for round_no in (0, 1):
            asyncio.run(
                tool.ainvoke({"company": "Notion", "sections": ["financial"], "round_no": round_no})
            )
    assert len(budget.queries) == 2
    for q, round_no in zip(budget.queries, (0, 1)):
        expected = build_live_query("Notion", "financial", round_no)
        assert q["query"] == expected
        assert q["cache_key"] == cache_key(
            expected, section="financial", max_results=5,
            search_depth="advanced", topic="finance",
        )
        assert q["section"] == "financial"


def test_dry_run_sentinel_explodes_if_ever_called() -> None:
    with pytest.raises(AssertionError, match="不应调用任何 Tavily client"):
        asyncio.run(DryRunSentinel().search(query="x"))


def test_dry_run_rejects_injected_real_budget() -> None:
    """反向：拿真实预算跑预演必须被拒，防止配置被误改后偷偷出网。"""
    s = _dry_settings()
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(LiveRetrievalDisabled, match="必须也是 dry_run=True"):
            make_document_tool(s, budget=CallBudget(3, dry_run=False), cache_dir=Path(td))


def test_dry_run_overrides_injected_real_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """双保险：即使误传 client，dry-run 里也必须被哨兵替换且不被调用。

    用探针监视传给 build_live_retrievers 的 client，全程不构造真实 SDK。
    """
    import capabilities.retrieval as retrieval_module

    s = _dry_settings()
    budget = CallBudget(0, dry_run=True)
    seen: list[Any] = []
    original = retrieval_module.build_live_retrievers

    def spy(settings: Any, *, client: Any, budget: Any, cache_dir: Any) -> Any:
        seen.append(client)
        return original(settings, client=client, budget=budget, cache_dir=cache_dir)

    monkeypatch.setattr(retrieval_module, "build_live_retrievers", spy)

    class WouldExplode:
        async def search(self, **kwargs: Any) -> Any:
            raise AssertionError("注入的 client 不该在 dry-run 里被调用")

    with tempfile.TemporaryDirectory() as td:
        tool = make_document_tool(
            s, budget=budget, cache_dir=Path(td), live_client=WouldExplode()
        )
        assert asyncio.run(
            tool.ainvoke({"company": "Notion", "sections": ["company"], "round_no": 0})
        ) == {"company": []}
    assert len(seen) == 1 and isinstance(seen[0], DryRunSentinel)
    assert budget.calls_made == 0
    assert budget.dry_runs == 1


def test_real_call_optins_are_not_relaxed() -> None:
    """真实调用仍需三重 opt-in：修 dry-run 不能顺手放开额度闸门。"""
    for overrides in (
        {"TAVILY_LIVE_ENABLED": "false"},
        {"TAVILY_MAX_CALLS": "0"},
    ):
        with pytest.raises(LiveRetrievalDisabled):
            make_document_tool(_real_settings(**overrides))


def test_fixture_mode_still_wins() -> None:
    s = load_settings(environ={"APP_MODE": "fixture", "TAVILY_DRY_RUN": "true"})
    tool = make_document_tool(s)
    out = asyncio.run(
        tool.ainvoke({"company": "Notion", "sections": ["company"], "round_no": 0})
    )
    assert out["company"][0]["source"] != "tavily"


# ---------------------------------------------------------------- SDK 静态签名核对

def test_tavily_sdk_signature_matches_retriever_call() -> None:
    """SDK 升级改了签名时立刻失败，而不是等 S8.2 真实调用时白扣额度。"""
    sig = inspect.signature(AsyncTavilyClient.search)
    assert inspect.iscoroutinefunction(AsyncTavilyClient.search)
    params = sig.parameters
    for name in ("query", "max_results", "search_depth", "topic"):
        assert name in params, f"SDK 缺少参数 {name}"
    s = _dry_settings()
    depth_literals = set(inspect.signature(AsyncTavilyClient.search)
                        .parameters["search_depth"].annotation.__args__)
    topic_literals = set(inspect.signature(AsyncTavilyClient.search)
                        .parameters["topic"].annotation.__args__)
    assert s.retrieval.search_depth in depth_literals
    assert set(s.retrieval.topics.values()) <= topic_literals
    assert "general" in topic_literals  # 未配置栏目的默认值


# ---------------------------------------------------------------- 完整图 dry-run 报告

def test_live_dryrun_report_is_clean_and_reproducible() -> None:
    a, b = dryrun.build_report(), dryrun.build_report()
    assert a == b, "两次独立预演必须逐字一致（不含时间戳/绝对路径）"
    assert a["budget"]["calls_made"] == 0
    assert a["budget"]["dry_runs"] == a["budget"]["query_count"] == 12
    assert a["guard"]["blocked_connection_attempts"] == 0
    assert a["guard"]["socket_connect_restored"] is True
    cred = a["credentials"]
    assert cred["tavily_key_resolutions"] == 0
    assert cred["llm_key_resolutions"] == 0
    assert cred["async_tavily_client_constructions"] == 0
    assert a["graph"]["research_runs"] == 3
    assert "degrade" in a["graph"]["node_trace"]
    assert all(q["executed"] is False for q in a["queries"])
    assert a["queries"] == sorted(a["queries"], key=lambda q: (
        q["query"], q["section"], q["cache_key"]
    ))


def test_committed_dryrun_json_matches_fresh_run() -> None:
    """CI 可核对提交产物不是手写/过期的。"""
    committed = json.loads(dryrun.OUTPUT.read_text(encoding="utf-8"))
    assert committed == dryrun.build_report()


def test_credit_estimate_is_derived_not_invented() -> None:
    r = dryrun.build_report()
    est = r["credit_estimate"]
    assert est["per_search_credits"] == 2  # advanced，官方计费页
    assert est["worst_case_credits_per_company"] == (
        est["would_be_requests_without_cache"] * 2
    )
    assert est["source"] == "https://docs.tavily.com/documentation/api-credits"
    assert "实际扣 0" in est["note"]


def test_unknown_search_depth_does_not_invent_credits(monkeypatch: pytest.MonkeyPatch) -> None:
    """官方未列单价的 depth 必须标 null，不许沿用 advanced 的数字。"""
    real_load = load_settings
    s = real_load(environ=dryrun.DRY_RUN_ENV)
    data = s.model_dump()
    data["retrieval"]["search_depth"] = "fast"
    from config.loader import Settings
    monkeypatch.setattr(dryrun, "load_settings", lambda environ=None: Settings.model_validate(data))
    r = dryrun.build_report()
    assert r["credit_estimate"]["worst_case_credits_per_company"] is None
    assert "拒绝猜测" in r["credit_estimate"]["unknown_reason"]


def test_offline_guard_blocks_non_loopback_and_restores() -> None:
    original = socket.socket.connect
    with eval_offline_guard("S8 test") as attempts:
        s = socket.socket()
        try:
            with pytest.raises(AssertionError, match="S8 test 禁止外部连接"):
                s.connect(("93.184.216.34", 80))
        finally:
            s.close()
    assert len(attempts) == 1
    assert socket.socket.connect is original


def test_credential_probe_restores_module_globals() -> None:
    import capabilities.llm as llm_module
    import capabilities.retrieval as retrieval_module
    import tavily

    before = (
        retrieval_module.resolve_tavily_credentials,
        llm_module.resolve_llm_credentials,
        tavily.AsyncTavilyClient,
    )
    with dryrun.credential_probe() as counts:
        assert all(v == 0 for v in counts.values())
    after = (
        retrieval_module.resolve_tavily_credentials,
        llm_module.resolve_llm_credentials,
        tavily.AsyncTavilyClient,
    )
    assert before == after
