"""S10-B 批量语义批改：把 `evals/live_batch.json` 里每家公司各自的报告分开判。

与 S8.4 的 `evals/judge.py` 的关系：

| | `judge.py`（S8.4） | 本脚本（S10-B） |
|---|---|---|
| 卷子 | `live_run.json` 里那 1 份 | `live_batch.json` 里的 N 份 |
| 请求数 | 1 次 | **每家公司 1 次** |
| 产物 | `live_score.json`（保持不变） | `live_score_batch.json` |

**为什么每家公司单独发一次**：一份 prompt 里塞 4 份报告 + 20 条标准答案，模型很容易
把 A 公司的证据句安到 B 公司头上，而证据句逐字校验也救不了这种跨卷串味。分开判、
分开核验，出错只影响一家。

**沿用 S8.4 的四条红线**（不重复实现，直接复用 `judge.py` 的函数）：
不送出处、证据句必须能在正文里逐字核到、`max_retries=0` 且不做重试、不冒充人工评分。
本脚本额外挂 `tavily_guard()`：批改阶段一次检索都不许发。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from langchain_community.callbacks import get_openai_callback
from langchain_core.prompts import ChatPromptTemplate

from capabilities.llm import make_chat_model
from config.loader import ROOT, apply_overrides, load_settings, resolve_llm_credentials
from evals.judge import (
    _SYSTEM_PROMPT,
    GOLDEN,
    JudgeOutput,
    LIVE_ENV,
    assemble,
    build_payload,
    tavily_guard,
)

BATCH = ROOT / "evals" / "live_batch.json"
OUTPUT = ROOT / "evals" / "live_score_batch.json"
PREFLIGHT_OUTPUT = ROOT / "evals" / "live_score_batch_failed.json"


def load_claims_by_company(path: Any = GOLDEN) -> dict[str, list[dict[str, Any]]]:
    """按公司分组 **全部** 人工核验过的标准答案。

    与 S8.4 的 `load_scorable_claims` 的区别：那边只取 `has_real_report_to_score=true`
    的 5 条（当时只有 Notion 有报告）；这里既然每家都真跑了，就用该公司的全部条目。
    """
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("kind") != "claim":
            continue
        grouped.setdefault(str(row.get("company") or ""), []).append(row)
    return grouped


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _judge_companies(
    chain: Any,
    runs: list[dict[str, Any]],
    grouped: dict[str, list[dict[str, Any]]],
    *,
    key: str,
    creds: Any,
    judge_settings: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[int]]:
    """在**同一个事件循环**里逐家批改。

    v1 把 `asyncio.run(chain.ainvoke(...))` 放在 for 里，第 2、4 家报
    `APIConnectionError: Connection error.` —— 和 `batch_live` 同样的坑：
    `ChatOpenAI` 内部的 httpx 连接池绑在第一次创建的循环上，循环一关就废。
    """
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    with tavily_guard() as tavily_calls:
        for run in runs:
            company = str(run.get("company") or "")
            report = str(run.get("report") or "")
            claims = grouped.get(company, [])
            if not report or not claims:
                skipped.append(
                    {
                        "company": company,
                        "reason": "没有报告正文" if not report else "该公司的标准答案不在 golden 里",
                    }
                )
                continue

            payload = build_payload(claims, report, company)
            for marker in ("source_url", "source_content", "ai_note", "human_note", "original_fact"):
                if f'"{marker}"' in payload:
                    raise RuntimeError(f"{company} 的 prompt 疑似泄漏字段 {marker}，拒绝发起请求")

            started = time.perf_counter()
            judged: JudgeOutput | None = None
            error: str | None = None
            usage: dict[str, Any] = {}
            try:
                with get_openai_callback() as cb:
                    judged = await chain.ainvoke({"payload": payload})
                usage = {
                    "successful_requests": cb.successful_requests,
                    "total_tokens": cb.total_tokens,
                    "prompt_tokens": cb.prompt_tokens,
                    "completion_tokens": cb.completion_tokens,
                    "total_cost_usd": None,
                    "cost_note": "qwen-plus 不在 OpenAI 价目表内，不套用、不编造成本数字",
                }
            except Exception as exc:  # 一家判失败不影响其它公司
                error = f"{type(exc).__name__}: {str(exc)[:300]}"
                if key in error:
                    error = "错误信息中疑似含密钥，已整体屏蔽"
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

            if judged is None:
                judged = JudgeOutput(judgements=[])
            single = assemble(
                claims,
                report,
                judged,
                status="ok" if error is None else "failed",
                is_real_judge=error is None,
                usage=usage,
                config={
                    "provider": creds.provider,
                    "model": judge_settings.models.roles["briefing"],
                    "max_retries_in_judge": 0,
                    "structured_output_method": "function_calling",
                },
                error=error,
                skipped_claims=0,
                company=company,
                elapsed_ms=elapsed_ms,
                isolation={"llm_requests_cap": 1, "tavily_client_search_calls": 0},
            )
            results.append(
                {
                    "company": company,
                    "status": single["status"],
                    "error": error,
                    "summary": single["summary"],
                    "schema_check": single["schema_check"],
                    "judgements": single["judgements"],
                    "usage": usage,
                    "elapsed_ms": elapsed_ms,
                    "report_checks": run.get("report_checks"),
                    "entity_guard": run.get("entity_guard", []),
                    "dataset": {"report_chars": len(report), "scored_claims": len(claims)},
                }
            )
    return results, skipped, tavily_calls


def run_live() -> dict[str, Any]:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "缺少 DASHSCOPE_API_KEY。请从 Windows 用户级变量 SYSTEM_ALIYUN_APIKEY "
            "映射到本进程内存后运行，不要把密钥写进 .env 或命令行参数。"
        )
    if not BATCH.exists():
        raise RuntimeError(f"{BATCH.name} 不存在，先跑 `uv run python -m evals.batch_live`")

    env = {**LIVE_ENV, "DASHSCOPE_API_KEY": key}
    settings = load_settings(environ=env)
    if settings.models.roles["briefing"] != "qwen-plus":
        raise RuntimeError(
            f"模型名未锁定：{settings.models.roles['briefing']!r}，拒绝白烧真实请求"
        )
    creds = resolve_llm_credentials(environ=env)
    if creds.provider != "dashscope":
        raise RuntimeError(f"provider 未锁定：{creds.provider!r}")

    judge_settings = apply_overrides(settings, {"models.max_retries": 0})
    model = make_chat_model(judge_settings, "briefing", credentials=creds)
    prompt = ChatPromptTemplate.from_messages(
        [("system", _SYSTEM_PROMPT), ("human", "{payload}")]
    )
    chain = prompt | model.with_structured_output(JudgeOutput, method="function_calling")

    batch = json.loads(BATCH.read_text(encoding="utf-8"))
    grouped = load_claims_by_company()
    results, skipped, tavily_calls = asyncio.run(
        _judge_companies(
            chain,
            batch.get("runs", []),
            grouped,
            key=key,
            creds=creds,
            judge_settings=judge_settings,
        )
    )

    aggregate = {
        field: sum(r["summary"][field] for r in results)
        for field in ("scored_claims", "supported", "refuted", "not_mentioned", "unjudged",
                      "self_conflict", "quote_check_failed")
    }
    aggregate["supported_share"] = (
        round(aggregate["supported"] / aggregate["scored_claims"], 4)
        if aggregate["scored_claims"]
        else None
    )

    statuses = {r["status"] for r in results}
    overall = "ok" if results and statuses <= {"ok"} else ("partial" if results else "failed")

    return {
        "purpose": "S10-B 批量语义批改：每家公司一份报告、一次请求、分开核验",
        "status": overall,
        "method": "AI judge (qwen-plus structured output)，非人工判定",
        "is_real_judge": bool(results) and all(r["status"] == "ok" for r in results),
        "is_human_adjudicated": False,
        "usable_as_resume_metric": False,
        "metric_boundary": {
            "may_be_called": "N 条人工核验标准答案的 AI 判定明细（可复核、附逐字证据句）",
            "must_not_be_called": "准确率 / 幻觉率 / 引用可追溯率 / p95 / 成本单价",
            "reasons": [
                "judge 是 AI 判定，未经人工抽检一致率校准；人出题、AI 批卷仍非人工评分",
                "not_mentioned 不等于系统答错：标准答案与报告栏目可能本来就不对应",
                "golden 的引用层（最终 URL 是否支撑事实）未核验，不能算引用类指标",
                "样本量小，且 5 家公司不是随机抽样，不能外推成「系统准确率」",
            ],
        },
        "dataset": {
            "golden_file": "evals/golden_live.jsonl",
            "batch_file": "evals/live_batch.json",
            "golden_sha256": _sha(GOLDEN),
            "batch_sha256": _sha(BATCH),
            "companies_scored": [r["company"] for r in results],
            "companies_skipped": skipped,
            "claim_fields_sent_to_judge": ["claim_id", "expected_text"],
        },
        "aggregate": aggregate,
        "companies": results,
        "isolation": {
            "llm_requests": len(results),
            "llm_requests_note": "每家公司 1 次，max_retries=0，失败不重试",
            "tavily_client_search_calls": len(tavily_calls),
            "tavily_credits_used": 0,
        },
        "verdict_note": (
            "supported 表示报告有支持该事实的陈述，不代表来源 URL 真的支持它；"
            "refuted 含报告自相矛盾的情形；not_mentioned 表示没写到，不等于答错。"
            "supported_share 是「标准答案被完整支持的比例」，**不是准确率**。"
        ),
        "credentials": {
            "api_key_env_var": "DASHSCOPE_API_KEY",
            "api_key_characters": len(key),
            "api_key_in_artifact": False,
        },
    }


def main() -> int:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    wants_live = "--live" in sys.argv[1:]
    if not wants_live:
        print("[S10-B judge] 未加 --live，不做任何请求")
        print("  真实批改需同时给 --live 和 JUDGE_LIVE=1")
        return 0
    if os.environ.get("JUDGE_LIVE") != "1":
        raise SystemExit("真实判定需同时给 --live 和 JUDGE_LIVE=1；本次不发起任何模型请求")
    try:
        result = run_live()
    except Exception as exc:
        error = f"{type(exc).__name__}: {str(exc)[:400]}"
        if key and key in error:
            error = "错误信息中疑似含密钥，已整体屏蔽"
        PREFLIGHT_OUTPUT.write_text(
            json.dumps(
                {"purpose": "S10-B judge 前置失败", "status": "failed",
                 "phase": "preflight", "error": error, "llm_requests": 0},
                ensure_ascii=False, indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        print(f"[S10-B judge] preflight failed -> evals/{PREFLIGHT_OUTPUT.name}")
        print(f"  error={error[:200]}")
        return 1

    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[S10-B judge] status={result['status']} -> {OUTPUT.relative_to(ROOT)}")
    print(f"  aggregate={result['aggregate']}")
    for company in result["companies"]:
        print(
            f"  - {company['company']:<10} {company['summary']} "
            f"tokens={company['usage'].get('total_tokens', 'n/a')}"
        )
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
