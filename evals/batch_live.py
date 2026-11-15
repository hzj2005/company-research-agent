"""S10-B 批量真实调研：一次跑多家公司，产出「可以批改」的样本。

与 S8.3 的 `evals/live_run.py` 的区别：

| | `live_run.py`（S8.3） | 本脚本（S10-B） |
|---|---|---|
| 输入 | 硬编码 1 家公司 | 命令行给一串公司 |
| 产物 | `evals/live_run.json`（保持不变） | `evals/live_batch.json` |
| 预算 | 每家一个 `CallBudget(12)` | **所有公司共享一个全局预算** |
| 用途 | 单次快照，供 S8.4–S8.6 引用 | 攒样本，供 `judge_batch.py` 批量批改 |

**为什么预算必须全局共享**：`CallBudget(12)` 是「一次运行」的上限，4 家公司各发一个
就是 48 次调用 = 96 credits，远超用户放行的 50。这里改成进程内一个预算，先到先得，
所以排在前面的公司优先拿到额度；被额度挡住的公司在产物里如实记 `budget_exhausted`，
不会静默降级成「没找到信息」。

**额度纪律**：`TAVILY_MAX_CALLS` 与 `CallBudget` 双保险；累计 credits（含 S8.2 的 2 与
S8.3 的 6）超过用户上限时，整份产物判 `failed`，不出报告。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from langchain_community.callbacks import get_openai_callback

from capabilities.retrieval import make_document_tool
from capabilities.tavily_retriever import CallBudget, TavilyBudgetExceeded
from config.loader import ROOT, load_settings, resolve_live_cache_dir
from evals.live_run import LIVE_ENV, USER_CREDIT_CEILING, _report_checks
from graph.run import run_research

OUTPUT = ROOT / "evals" / "live_batch.json"

# 用户 2026-11-15 拍板：跑 3 家，留回退余量（12 必调 + 4 补搜 = 16 次 = 32 credits）
# `Notion` 排在最前是刻意的：它的 4 条 query 全部命中 S8.3 留下的磁盘缓存，**0 credits**，
# 于是能用同一套 golden 拿到「修复后的报告」，与 `live_run.json`（修复前）做同题对比。
DEFAULT_COMPANIES = ["Notion", "Figma", "Stripe", "Airbnb"]
GLOBAL_MAX_CALLS = 16          # 16 次 × 2 credits = 32；与已用的 8 相加共 40 / 50
CREDITS_PER_SEARCH = 2         # https://docs.tavily.com/documentation/api-credits: advanced = 2

# 已经真实花掉、且不会重算的额度记在独立台账里。
# v1 有个真 bug：每家包一层 `asyncio.run`，第 2 家 `Event loop is closed`，
# Stripe 的 4 次检索发出去了却没拿到报告、也没写缓存。那 8 credits 是真花掉的，
# 所以 v1 产物永久留档并计入台账 —— **失败也要记账**。
#
# 早于台账的两次（S8.2 探针 2 + S8.3 端到端 6）已回填进 `evals/credits_ledger.json`。
LEDGER = ROOT / "evals" / "credits_ledger.json"


def credits_already_spent() -> int:
    """已花 credits 只从台账读，不在代码里另写一个会漂移的常数。"""
    if not LEDGER.exists():
        return 0
    data = json.loads(LEDGER.read_text(encoding="utf-8"))
    return int(data.get("total_credits", 0))


def append_ledger(entry: dict[str, Any]) -> None:
    """跑完追加一条，并重算 total。失败也追加 —— 额度纪律不接受「没出报告就不算花」。"""
    data = (
        json.loads(LEDGER.read_text(encoding="utf-8"))
        if LEDGER.exists()
        else {"ceiling": USER_CREDIT_CEILING, "entries": []}
    )
    data.setdefault("entries", []).append(entry)
    data["total_credits"] = sum(int(e.get("credits", 0)) for e in data["entries"])
    LEDGER.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _state_summary(state: dict[str, Any]) -> dict[str, Any]:
    """只留可审计字段，且把不可 JSON 化的对象转成 str。"""
    def plain(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [plain(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    keys = ("degraded", "degraded_sections", "retry_count", "company")
    return {k: plain(state[k]) for k in keys if k in state}


def _guard_notes(state: dict[str, Any]) -> list[dict[str, Any]]:
    """把实体消歧的留痕单独拎出来 —— 这是本阶段最想看的真实证据。"""
    return [
        n for n in state.get("review_notes", []) if isinstance(n, dict) and n.get("node") == "entity_guard"
    ]


async def _run_companies(
    companies: list[str],
    settings: Any,
    tool: Any,
    tmp_path: Path,
) -> list[dict[str, Any]]:
    """在**同一个事件循环**里逐家跑。

    v1 写成「每家包一层 `asyncio.run`」，第 2 家直接 `RuntimeError: Event loop is closed`
    —— `AsyncTavilyClient` 只构造一次，它的连接池绑在第一个循环上，循环一关就废。
    串行 await 既避开这个坑，也保留「一家失败不带崩整批」的隔离。
    """
    runs: list[dict[str, Any]] = []
    for index, company in enumerate(companies):
        started = time.perf_counter()
        state: dict[str, Any] = {}
        trace: list[str] = []
        usage: dict[str, Any] = {}
        error: str | None = None
        try:
            with get_openai_callback() as cb:
                state, trace = await run_research(
                    company,
                    settings,
                    tmp_path / f"ckpt_{index}.db",
                    collect_trace=True,
                    document_tool=tool,
                )
            usage = {
                "successful_requests": cb.successful_requests,
                "total_tokens": cb.total_tokens,
                "prompt_tokens": cb.prompt_tokens,
                "completion_tokens": cb.completion_tokens,
            }
        except TavilyBudgetExceeded as exc:
            error = f"budget_exhausted: {str(exc)[:300]}"
        except Exception as exc:  # 一家失败不能带崩整批
            error = f"{type(exc).__name__}: {str(exc)[:300]}"

        report_text = str(state.get("report", ""))
        runs.append(
            {
                "company": company,
                "status": "ok" if error is None and report_text else "failed",
                "error": error,
                "report": report_text,
                "report_checks": _report_checks(report_text) if report_text else None,
                "graph": {**_state_summary(state), "node_trace": trace},
                "entity_guard": _guard_notes(state),
                "llm_usage": usage,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        )
    return runs


def build_batch(companies: list[str], *, max_calls: int = GLOBAL_MAX_CALLS) -> dict[str, Any]:
    tavily_key = os.environ.get("TAVILY_API_KEY", "").strip()
    llm_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    missing = [
        name
        for name, value in (("TAVILY_API_KEY", tavily_key), ("DASHSCOPE_API_KEY", llm_key))
        if not value
    ]
    if missing:
        raise RuntimeError(
            f"缺少 {', '.join(missing)}。请从 Windows 用户级变量映射进本进程内存后运行，"
            "不要把密钥写进 .env 或命令行参数。"
        )

    env = {
        **LIVE_ENV,
        "TAVILY_API_KEY": tavily_key,
        "DASHSCOPE_API_KEY": llm_key,
        "TAVILY_MAX_CALLS": str(max_calls),
        "FEATURES_ENTITY_GUARD": "true",
        "FEATURES_CONFLICT_ANNOTATION": "true",
    }
    settings = load_settings(environ=env)
    if settings.app.mode != "live" or not settings.retrieval.live.enabled:
        raise RuntimeError("批量真实调研必须处于 live + TAVILY_LIVE_ENABLED=true")
    if settings.retrieval.live.dry_run:
        raise RuntimeError("这是真实运行，TAVILY_DRY_RUN 必须为 false")
    if settings.models.roles["briefing"] != "qwen-plus":
        raise RuntimeError(
            f"模型名未锁定：{settings.models.roles['briefing']!r}；拒绝白烧真实请求"
        )

    budget = CallBudget(max_calls, dry_run=False)
    tool = make_document_tool(settings, budget=budget, cache_dir=resolve_live_cache_dir(settings))

    started_all = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="s10-batch-") as tmp:
        runs = asyncio.run(_run_companies(companies, settings, tool, Path(tmp)))

    for run in runs:  # 单家异常里也可能带出凭据片段，统一再扫一遍
        if run["error"] and (tavily_key in run["error"] or llm_key in run["error"]):
            run["error"] = "错误信息疑似含密钥，已整体屏蔽"

    spent = budget.calls_made * CREDITS_PER_SEARCH
    before = credits_already_spent()
    cumulative = spent + before
    ok_runs = [r for r in runs if r["status"] == "ok"]

    result: dict[str, Any] = {
        "purpose": "S10-B 批量真实调研：用已人工核验的 golden 攒可批改样本",
        "status": "ok" if ok_runs else "failed",
        "companies": companies,
        "config": {
            "app_mode": settings.app.mode,
            "provider": "dashscope",
            "model": settings.models.roles["briefing"],
            "search_depth": settings.retrieval.search_depth,
            "structured_output": settings.features.structured_output,
            "entity_guard": settings.features.entity_guard,
            "conflict_annotation": settings.features.conflict_annotation,
            "sections": list(settings.graph.sections),
            "max_retry": settings.graph.max_retry,
        },
        "budget": {
            "global_max_calls": max_calls,
            "calls_made": budget.calls_made,
            "cache_hits": budget.cache_hits,
            "remaining": budget.remaining,
            "executed_queries": [
                {k: q[k] for k in ("query", "section", "cache_hit", "executed") if k in q}
                for q in budget.queries
            ],
        },
        "credits": {
            "credits_per_search": CREDITS_PER_SEARCH,
            "spent_this_run": spent,
            "spent_before": before,
            "cumulative": cumulative,
            "user_ceiling": USER_CREDIT_CEILING,
            "within_ceiling": cumulative <= USER_CREDIT_CEILING,
            "note": "advanced=2 credits/次；缓存命中不扣，以 calls_made 为准",
        },
        "summary": {
            "runs": len(runs),
            "ok": len(ok_runs),
            "failed": len(runs) - len(ok_runs),
            "entity_guard_rejections": sum(
                len(v.get("rejected", []))
                for r in runs
                for v in r.get("entity_guard", [])
            ),
        },
        "runs": runs,
        "timing": {
            "elapsed_ms": round((time.perf_counter() - started_all) * 1000, 1),
            "note": "本机墙钟，含网络往返，非确定性字段，不代表 p95",
        },
        "credentials": {
            "keys_read": ["TAVILY_API_KEY", "DASHSCOPE_API_KEY"],
            "keys_printed": 0,
            "keys_in_artifact": False,
        },
    }
    if not result["credits"]["within_ceiling"]:
        result["status"] = "failed"
        result["error"] = "累计 credits 超出用户放行上限，结果作废"
    return result


def main() -> int:
    companies = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not companies:
        companies = DEFAULT_COMPANIES

    # 本次预算 = min(设计上限, 用户额度剩余)。这样「重跑多少次都不会越过 50」这件事
    # 由算术保证，而不是靠人记住之前花过多少。
    already = credits_already_spent()
    max_calls = min(GLOBAL_MAX_CALLS, max(0, (USER_CREDIT_CEILING - already) // CREDITS_PER_SEARCH))
    if max_calls <= 0:
        raise SystemExit(
            f"额度已用尽：已花 {already} / {USER_CREDIT_CEILING}，本次不发起任何真实请求"
        )
    print(
        f"[S10-B batch] 已花 {already} credits，本次最多 {max_calls} 次 = "
        f"{max_calls * CREDITS_PER_SEARCH} credits，累计上限 {USER_CREDIT_CEILING}"
    )

    report = build_batch(companies, max_calls=max_calls)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["credits"]["spent_this_run"] > 0:
        append_ledger(
            {
                "stage": f"S10-B batch（{len(companies)} 家）",
                "credits": report["credits"]["spent_this_run"],
                "calls": report["budget"]["calls_made"],
                "artifact": "evals/live_batch.json",
                "note": f"companies={','.join(companies)}; ok={report['summary']['ok']}/{report['summary']['runs']}",
            }
        )

    print(f"[S10-B batch] status={report['status']} -> {OUTPUT.relative_to(ROOT)}")
    print(
        f"  tavily calls={report['budget']['calls_made']}/{report['budget']['global_max_calls']} "
        f"cache_hits={report['budget']['cache_hits']} "
        f"credits=+{report['credits']['spent_this_run']} (cumulative {report['credits']['cumulative']})"
    )
    for run in report["runs"]:
        checks = run["report_checks"] or {}
        print(
            f"  - {run['company']:<10} {run['status']:<6} "
            f"{checks.get('chars', 0):>5} chars / {checks.get('reference_lines', 0):>2} refs / "
            f"guard_rejected={sum(len(v.get('rejected', [])) for v in run['entity_guard'])}"
        )
        if run["error"]:
            print(f"      error={run['error'][:180]}")
    if report.get("error"):
        print(f"  error={report['error']}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
