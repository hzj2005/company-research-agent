"""S8.1 dry-run 预演：0 key、0 请求、0 额度，跑一遍**完整图**。

    uv run python -m evals.live_dryrun

产出 `evals/live_dryrun.json`：一次真实图运行会向 Tavily 发出哪些 query、
每条的 sha256 cache key、预算计数、图轨迹与禁网守卫证据。query 清单由
`CallBudget.queries` 从生产代码路径采集（`TavilyRetriever._aget_relevant_documents`），
**不是**本脚本另写一套 query 生成器冒充预演。

硬约束：
1. 只构造 `APP_MODE=live + TAVILY_DRY_RUN=true`，显式 `environ` 覆盖，不读 `.env`、
   不读也不打印任何 key；`FEATURES_STRUCTURED_OUTPUT=false` 让 briefing 走模板分支
   （否则 live 构造 `ChatOpenAI` 会要求模型 key）。
2. `make_document_tool` 在 dry-run 下强制使用 `DryRunSentinel`，绝不实例化
   `AsyncTavilyClient`；注入的 `CallBudget(dry_run=True)` 记录每一条 query。
3. 整次运行包在禁网守卫里：非回环 `socket.connect` 立即抛错并作废结果。
4. 输出不含时间戳 / 绝对路径 / 凭据，跨机器可复现。

本脚本不属于 S7 评测台：它不产出分数，也**不能**用于简历里的效果数字；
真实返回结构、延迟、成本需要 S8.2 之后用户明确放行才测。
"""

from __future__ import annotations

import asyncio
import json
import socket
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import capabilities.llm as llm_module
import capabilities.retrieval as retrieval_module
import tavily

from capabilities.retrieval import make_document_tool
from capabilities.tavily_retriever import CallBudget
from config.loader import ROOT, load_settings
from evals.run_eval import eval_offline_guard
from graph.run import run_research

OUTPUT = ROOT / "evals" / "live_dryrun.json"
SCHEMA_VERSION = 1

# Tavily 官方计费（https://docs.tavily.com/documentation/api-credits）：
# 只有 basic = 1 credit/次、advanced = 2 credits/次 有明确依据；免费 1000 credits/月。
# fast / ultra-fast 的单价官方本页未列出，**不猜测**，出估算时明确标注 unknown。
# 项目 config/settings.yaml 的 retrieval.search_depth 默认 advanced。
CREDITS_PER_SEARCH_BY_DEPTH = {"basic": 1, "advanced": 2}
CREDIT_SOURCE = "https://docs.tavily.com/documentation/api-credits"

DRY_RUN_ENV: dict[str, str] = {
    "APP_MODE": "live",
    "TAVILY_LIVE_ENABLED": "false",   # dry-run 是独立路径，不需要放行额度
    "TAVILY_MAX_CALLS": "0",           # 真实预算为 0：即使护栏失效也调不动
    "TAVILY_DRY_RUN": "true",
    "FEATURES_STRUCTURED_OUTPUT": "false",
    "FEATURES_HUMAN_REVIEW": "false",
    "CHECKPOINTER": "sqlite",
    "LOG_LEVEL": "WARNING",
}


def _settings_snapshot(settings: Any) -> dict[str, Any]:
    return {
        "app_mode": settings.app.mode,
        "search_depth": settings.retrieval.search_depth,
        "max_results_per_query": settings.retrieval.max_results_per_query,
        "topics": dict(settings.retrieval.topics),
        "max_retry": settings.graph.max_retry,
        "sections": list(settings.graph.sections),
        "structured_output": settings.features.structured_output,
        "live_enabled": settings.retrieval.live.enabled,
        "live_max_calls_per_run": settings.retrieval.live.max_calls_per_run,
        "live_dry_run": settings.retrieval.live.dry_run,
    }


@contextmanager
def credential_probe() -> Iterator[dict[str, int]]:
    """把「读 key / 构造真实 SDK」三个点换成计数器，用证据代替口头声明。

    只统计、不真正解析；若生产代码在 dry-run 里调用了其中任何一个，计数会 > 0，
    `main()` 会把结果判为失败。
    """
    counts = {
        "tavily_key_resolutions": 0,
        "llm_key_resolutions": 0,
        "async_tavily_client_constructions": 0,
    }
    saved = (
        retrieval_module.resolve_tavily_credentials,
        llm_module.resolve_llm_credentials,
        tavily.AsyncTavilyClient,
    )

    def fake_tavily(*_a: Any, **_k: Any) -> Any:
        counts["tavily_key_resolutions"] += 1
        raise AssertionError("dry-run 不应解析 TAVILY_API_KEY")

    def fake_llm(*_a: Any, **_k: Any) -> Any:
        counts["llm_key_resolutions"] += 1
        raise AssertionError("dry-run 不应解析模型 key")

    class FakeAsyncTavilyClient:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            counts["async_tavily_client_constructions"] += 1
            raise AssertionError("dry-run 不应构造 AsyncTavilyClient")

    retrieval_module.resolve_tavily_credentials = fake_tavily  # type: ignore[assignment]
    llm_module.resolve_llm_credentials = fake_llm  # type: ignore[assignment]
    tavily.AsyncTavilyClient = FakeAsyncTavilyClient  # type: ignore[assignment]
    try:
        yield counts
    finally:
        (
            retrieval_module.resolve_tavily_credentials,
            llm_module.resolve_llm_credentials,
            tavily.AsyncTavilyClient,
        ) = saved


def build_report() -> dict[str, Any]:
    """跑一次完整图并返回可序列化报告；任何外部连接都会让本函数抛错。"""
    settings = load_settings(environ=DRY_RUN_ENV)
    assert settings.app.mode == "live" and settings.retrieval.live.dry_run, (
        "S8.1 必须处于 live + dry_run，否则拒绝出报告"
    )

    budget = CallBudget(0, dry_run=True)
    original_connect = socket.socket.connect
    with tempfile.TemporaryDirectory(prefix="s8-dryrun-") as tmp:
        tmp_path = Path(tmp)
        with credential_probe() as creds_used, eval_offline_guard("S8 dry-run") as attempts:
            tool = make_document_tool(settings, budget=budget, cache_dir=tmp_path / "cache")
            state, trace = asyncio.run(
                run_research(
                    "Notion", settings, tmp_path / "checkpoints.db",
                    collect_trace=True, document_tool=tool,
                )
            )
        blocked = list(attempts)

    # 4 个 analyst 由 Send 并行派发，实际到达顺序受调度影响；按稳定键排序，
    # 保证 scorecard 一样跨机器逐字可复现。执行顺序本身不是指标。
    queries = sorted(
        (dict(q) for q in budget.queries),
        key=lambda q: (q["query"], q["section"], q["cache_key"]),
    )
    credential_counts = dict(creds_used)
    credits_per_search = CREDITS_PER_SEARCH_BY_DEPTH.get(settings.retrieval.search_depth)
    planned = sum(1 for q in queries if not q["cache_hit"])
    credit_estimate: dict[str, Any] = {
        "per_search_credits": credits_per_search,
        "search_depth": settings.retrieval.search_depth,
        "would_be_requests_without_cache": planned,
        "worst_case_credits_per_company": (
            planned * credits_per_search if credits_per_search is not None else None
        ),
        "free_tier_credits_per_month": 1000,
        "source": CREDIT_SOURCE,
        "note": (
            "按官方计费规则推算，不是实测扣费；本次运行实际扣 0 credits。"
            "缓存命中不扣额度，真实次数以 CallBudget.calls_made 为准。"
        ),
    }
    if credits_per_search is None:
        credit_estimate["unknown_reason"] = (
            f"官方计费页未列出 {settings.retrieval.search_depth!r} 单价，拒绝猜测，"
            "最坏情况标注为 null；真实消耗以 S8.2 后控制台账单为准"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "provenance": (
            "S8.1 synthetic-free dry-run: 完整 LangGraph 运行，0 次真实 Tavily/模型调用，"
            "query 清单采集自生产检索路径 CallBudget.queries；不是检索结果、不是评测分数"
        ),
        "settings": _settings_snapshot(settings),
        "credentials": {
            **credential_counts,
            "api_keys_printed": 0,
            "note": (
                "三个入口（Tavily key / 模型 key / AsyncTavilyClient 构造）已替换为计数器探针，"
                "计数全 0 才说明 dry-run 真的没碰凭据；不是口头声明"
            ),
        },
        "budget": {
            "max_calls": budget.max_calls,
            "calls_made": budget.calls_made,
            "cache_hits": budget.cache_hits,
            "dry_runs": budget.dry_runs,
            "query_count": len(queries),
        },
        "queries": queries,
        "queries_sorted_by": ["query", "section", "cache_key"],
        "graph": {
            "company": state.get("company"),
            "evidence_verdict": state.get("evidence_verdict"),
            "retry_count": state.get("retry_count"),
            "degraded": state.get("degraded"),
            "degraded_sections": state.get("degraded_sections"),
            "report_chars": len(state.get("report", "")),
            "node_trace": trace,
            "research_runs": trace.count("research") if trace else 0,
        },
        "guard": {
            "label": "S8 dry-run",
            "blocked_connection_attempts": len(blocked),
            "socket_connect_restored": socket.socket.connect is original_connect,
            "rule": "仅放行 127.* / ::1 / localhost，其余连接记录并抛错",
        },
        "credit_estimate": credit_estimate,
        "not_measured": [
            "AsyncTavilyClient.search() 的真实返回结构与字段名",
            "score 实际分布 / content 长度 / 异常形态",
            "真实 p95 延迟、单次成本、真实准确率与幻觉率",
            "真实检索结果落盘缓存后的复用率",
        ],
    }


def main() -> int:
    report = build_report()
    cred = report["credentials"]
    unsafe = (
        report["budget"]["calls_made"] != 0
        or report["guard"]["blocked_connection_attempts"] != 0
        or not report["guard"]["socket_connect_restored"]
        or any(cred[k] != 0 for k in (
            "tavily_key_resolutions",
            "llm_key_resolutions",
            "async_tavily_client_constructions",
        ))
    )
    if unsafe:
        print("[FAIL] dry-run 出现真实调用 / 外部连接 / 凭据读取 / 守卫未还原，结果作废")
        return 1
    if not report["queries"]:
        print("[FAIL] 未采集到任何 query，预演无意义")
        return 1
    OUTPUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] S8.1 dry-run -> {OUTPUT.relative_to(ROOT)}")
    print(
        f"  queries={report['budget']['query_count']}  "
        f"calls_made={report['budget']['calls_made']}  "
        f"dry_runs={report['budget']['dry_runs']}  "
        f"blocked={report['guard']['blocked_connection_attempts']}"
    )
    est = report["credit_estimate"]
    print(
        f"  最坏情况（无缓存）：{est['would_be_requests_without_cache']} 次请求 × "
        f"{est['per_search_credits']} credits = {est['worst_case_credits_per_company']} credits/公司"
        f"（推算值，实际扣 0；免费额度 1000/月）"
    )
    print(f"  node_trace={report['graph']['node_trace']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
