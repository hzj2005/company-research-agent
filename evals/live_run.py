"""S8.3 端到端真实报告：1 家公司，真检索 + 真模型 + 真 SQLite checkpoint。

额度护栏（对应用户放行的 20–50 credits）：
- `TAVILY_MAX_CALLS=12` 且显式注入 `CallBudget(12)`，双重硬上限；
- `search_depth=advanced` = 2 credits/次，最坏 24 credits；命中磁盘缓存不扣；
- 累计含 S8.2 的 2 credits 一并记账，超过 50 时脚本直接拒绝出报告。

产物只写结构统计 + 报告正文 + query 清单；不写密钥、不写 .env、不打印 key。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from langchain_community.callbacks import get_openai_callback

from capabilities.retrieval import make_document_tool
from capabilities.tavily_retriever import CallBudget
from config.loader import ROOT, load_settings, resolve_live_cache_dir
from graph.run import run_research

OUTPUT = ROOT / "evals" / "live_run.json"

COMPANY = "Notion"
MAX_CALLS = 12
CREDITS_PER_SEARCH = 2  # https://docs.tavily.com/documentation/api-credits: advanced = 2

# 额度一律以台账为准（evals/credits_ledger.json 的 total_credits 是唯一真相）。
# 2026-11-15 用户把上限从 50 放宽到 200；不要再写死 S8 时点的 50。
_CREDITS_LEDGER = ROOT / "evals" / "credits_ledger.json"


def _ledger_totals() -> tuple[int, int]:
    """返回 (已用 credits, 当前放行上限)；台账缺失时保守回落到 (0, 50)。"""
    if not _CREDITS_LEDGER.exists():
        return 0, 50
    data = json.loads(_CREDITS_LEDGER.read_text(encoding="utf-8"))
    return int(data.get("total_credits", 0)), int(data.get("ceiling", 50))


USER_CREDIT_CEILING, CREDITS_ALREADY_SPENT = _ledger_totals()[1], _ledger_totals()[0]

LIVE_ENV: dict[str, str] = {
    "APP_MODE": "live",
    "TAVILY_LIVE_ENABLED": "true",
    "TAVILY_MAX_CALLS": str(MAX_CALLS),
    "TAVILY_DRY_RUN": "false",
    "LLM_PROVIDER": "dashscope",
    "LLM_MODEL": "qwen-plus",
    "LLM_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "FEATURES_STRUCTURED_OUTPUT": "true",
    "FEATURES_HUMAN_REVIEW": "false",
}


def _state_summary(state: dict[str, Any]) -> dict[str, Any]:
    def plain(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [plain(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    keys = ("degraded", "degraded_sections", "retry_count", "review_notes", "company")
    return {k: plain(state[k]) for k in keys if k in state}


def _report_checks(report: str, settings: Any) -> dict[str, Any]:
    headings = re.findall(r"^## (.+)$", report, flags=re.MULTILINE)
    # [n] 同时出现在正文和 References 段；只数正文，否则同一个引用会被计两次。
    body, separator, refs = report.partition("## References")
    if not separator:
        refs = ""
    # 标题按配置取（中文），不要硬编码英文——报告输出一直是中文
    expected = list(settings.report.headings)
    return {
        "chars": len(report),
        "headings": headings,
        "inline_citation_markers": len(re.findall(r"\[\d+\]", body)),
        "reference_lines": len(re.findall(r"^\[\d+\]\s", refs, flags=re.MULTILINE)),
        "has_four_sections": all(h in headings for h in expected),
        "has_references_section": "References" in headings,
        # 拒答文案同样按配置取，避免与 graph.degrade.message 脱节
        "abstain_markers": report.count(settings.graph.degrade.message),
    }


def build_report() -> dict[str, Any]:
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

    env = {**LIVE_ENV, "TAVILY_API_KEY": tavily_key, "DASHSCOPE_API_KEY": llm_key}
    settings = load_settings(environ=env)
    if settings.app.mode != "live" or not settings.retrieval.live.enabled:
        raise RuntimeError("S8.3 必须处于 live + TAVILY_LIVE_ENABLED=true")
    if settings.retrieval.live.dry_run:
        raise RuntimeError("S8.3 是真实运行，TAVILY_DRY_RUN 必须为 false")
    if settings.models.roles["briefing"] != "qwen-plus":
        raise RuntimeError(
            f"模型名未锁定：{settings.models.roles['briefing']!r}；拒绝白烧一次真实请求"
        )
    if settings.retrieval.live.max_calls_per_run != MAX_CALLS:
        raise RuntimeError("配置里的预算与脚本硬预算不一致，拒绝运行")

    budget = CallBudget(MAX_CALLS, dry_run=False)
    started = time.perf_counter()
    error: str | None = None
    state: dict[str, Any] = {}
    trace: list[str] = []
    usage: dict[str, Any] = {}

    try:
        with tempfile.TemporaryDirectory(prefix="s8-live-") as tmp:
            tmp_path = Path(tmp)
            tool = make_document_tool(
                settings,
                budget=budget,
                cache_dir=resolve_live_cache_dir(settings),
            )
            with get_openai_callback() as cb:
                state, trace = asyncio.run(
                    run_research(
                        COMPANY,
                        settings,
                        tmp_path / "checkpoints.db",
                        collect_trace=True,
                        document_tool=tool,
                    )
                )
            usage = {
                "successful_requests": cb.successful_requests,
                "total_tokens": cb.total_tokens,
                "prompt_tokens": cb.prompt_tokens,
                "completion_tokens": cb.completion_tokens,
                "capture_note": (
                    "get_openai_callback 跨 asyncio.run 捕获；若为 0 表示未捕获到，"
                    "不能据此推断模型没被调用"
                ),
                "total_cost_usd": None,
                "cost_note": "qwen-plus 不在 OpenAI 价目表内，不套用、不编造成本数字",
            }
    except Exception as exc:  # 真实故障必须如实落盘
        error = f"{type(exc).__name__}: {str(exc)[:400]}"
        if tavily_key in error or llm_key in error:
            error = "错误信息疑似含密钥，已整体屏蔽"
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    spent = budget.calls_made * CREDITS_PER_SEARCH
    cumulative = spent + CREDITS_ALREADY_SPENT
    report_text = str(state.get("report", ""))

    result: dict[str, Any] = {
        "purpose": "S8.3 端到端真实报告（1 家公司）：真检索 + 真模型 + 真 checkpoint",
        "status": "ok" if error is None and report_text else "failed",
        "error": error,
        "company": COMPANY,
        "config": {
            "app_mode": settings.app.mode,
            "provider": "dashscope",
            "model": settings.models.roles["briefing"],
            "search_depth": settings.retrieval.search_depth,
            "structured_output": settings.features.structured_output,
            "human_review": settings.features.human_review,
            "sections": list(settings.graph.sections),
            "max_retry": settings.graph.max_retry,
        },
        "budget": {
            "max_calls": MAX_CALLS,
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
            "spent_in_s8_2": CREDITS_ALREADY_SPENT,
            "cumulative": cumulative,
            "user_ceiling": USER_CREDIT_CEILING,
            "within_ceiling": cumulative <= USER_CREDIT_CEILING,
            "source": "https://docs.tavily.com/documentation/api-credits",
            "note": "advanced=2 credits/次，按官方计费推算；缓存命中不扣，以 calls_made 为准",
        },
        "llm_usage": usage,
        "report": report_text,
        "report_checks": _report_checks(report_text, settings) if report_text else None,
        "graph": {
            "node_trace": trace,
            **_state_summary(state),
        },
        "timing": {
            "elapsed_ms": elapsed_ms,
            "note": "本机墙钟，含网络往返，非确定性字段，不代表 p95",
        },
        "credentials": {
            "keys_read": ["TAVILY_API_KEY", "DASHSCOPE_API_KEY"],
            "key_lengths": {"tavily": len(tavily_key), "dashscope": len(llm_key)},
            "keys_printed": 0,
            "keys_in_artifact": False,
            "note": "key 仅存在于进程内存；不写 .env、不进命令行、不进 git",
        },
    }
    if not result["credits"]["within_ceiling"]:
        result["status"] = "failed"
        result["error"] = "累计 credits 超出用户放行上限，结果作废"
    return result


def main() -> int:
    report = build_report()
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[S8.3 live run] status={report['status']} -> {OUTPUT.relative_to(ROOT)}")
    print(
        f"  tavily calls={report['budget']['calls_made']}/{MAX_CALLS} "
        f"cache_hits={report['budget']['cache_hits']} "
        f"credits=+{report['credits']['spent_this_run']} (cumulative {report['credits']['cumulative']})"
    )
    if report["report_checks"]:
        c = report["report_checks"]
        print(
            f"  report: {c['chars']} chars, {c['inline_citation_markers']} inline markers, "
            f"{c['reference_lines']} refs, four_sections={c['has_four_sections']}"
        )
    print(f"  llm: {report['llm_usage'].get('total_tokens', 'n/a')} tokens; elapsed={report['timing']['elapsed_ms']}ms")
    if report["error"]:
        print(f"  error={report['error'][:200]}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
