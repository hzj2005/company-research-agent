"""S8.4 语义 judge：把「人工核验的中文标准答案」与「系统写的英文报告」对齐。

为什么要这一步：S7 的 `evals/metrics.py` 是逐字/词法匹配，中文答案对英文报告
必然全判 0 分，测出来的不是事实准确率而是编码差异。本脚本一次批量请求让
`qwen-plus` 对每条标准答案判 supported / refuted / not_mentioned，并给出
**报告里的逐字证据句**，供人复核。

四条红线（对应 AGENT.md / GOLDEN_LIVE.md）：
1. **不泄漏出处**：送进 prompt 的只有 `claim_id` + `expected_text`；
   `source_url` / `source_content` / `ai_note` / `human_note` 一律不送，
   否则 judge 会拿标准答案的出处替报告脑补证据。
2. **证据句可机器核验**：模型给的 evidence_quotes 必须能在报告正文里逐字
   （归一化空白与 `[n]` 标记后）找到；核不到的标 `quote_check_failed`，
   不作为可靠判定依据，绝不静默采信。
3. **1 次请求 / 0 credits**：`max_retries=0` 且不做任何重试；给
   `AsyncTavilyClient.search` 装哨兵，被调用即抛错；不构造 document_tool。
   真实调用需同时满足 `--live` + `JUDGE_LIVE=1` + `DASHSCOPE_API_KEY`，
   否则只跑 0 调用的 dry-run，产物明确标 `is_real_judge=false`。
4. **不冒充人工、不冒充指标**：结果标 `is_human_adjudicated=false`、
   `usable_as_resume_metric=false`。样本仅 1 家 5 条，AI judge 未经人工抽检
   一致率校准，引用层未核验 —— 这里的计数只能叫「判定明细」，不是准确率。

失败如实落盘（status=failed + error），不吞异常、不自动烧第 2 次请求。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from typing import Any, Iterator, Literal

from langchain_community.callbacks import get_openai_callback
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, ConfigDict, Field

from capabilities.llm import make_chat_model
from config.loader import ROOT, apply_overrides, load_settings, resolve_llm_credentials

GOLDEN = ROOT / "evals" / "golden_live.jsonl"
REPORT = ROOT / "evals" / "live_run.json"
OUTPUT = ROOT / "evals" / "live_score.json"
DRYRUN_OUTPUT = ROOT / "evals" / "live_score_dryrun.json"

VERDICTS = ("supported", "refuted", "not_mentioned")
OPT_IN_VAR = "JUDGE_LIVE"

# 与 S8.3 探针一致：显式锁定百炼端点与模型名，绝不用 settings.yaml 里上游的
# google/gemini-3.8-flash 去打 DashScope（会白烧一次请求）。
LIVE_ENV: dict[str, str] = {
    "APP_MODE": "live",
    "LLM_PROVIDER": "dashscope",
    "LLM_MODEL": "qwen-plus",
    "LLM_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}

_SYSTEM_PROMPT = """你是「公司调研报告」的评测判卷员。只依据 <payload> 里的 report 文字判卷。

规则：
- 禁止使用 report 之外的任何知识，包括你对这些公司的既有了解、常识或外部资料。
- 逐条判定 golden_claims，claim_id 必须原样回传，不得增删、不得改拼写。
- 允许中英文同义改写：答案写「2013 年创办」，报告写 "founded in 2013" 即视为一致。
- 三态定义：
  * supported：report 中有明确且无冲突的陈述与标准答案一致。
  * refuted：report 中有明确陈述与标准答案矛盾；或 report 对同一事实给出
    互相冲突的取值（自相矛盾），此时 self_conflict 置 true。
  * not_mentioned：report 未提及，或只有零散信息不足以确认。
- evidence_quotes：必须是 report 中**逐字出现**的片段，可省略行尾 [n] 引用标记；
  禁止翻译、改写、拼接或编造。supported / refuted 至少给 1 条；
  报告自相矛盾时把所有冲突句都列进去；not_mentioned 给空数组。
- References 段落只是来源清单，其中的标题文字不计入事实陈述。
- reason 用一句话说明判定的依据，不得引用 report 之外的内容。
- 输出必须符合 JudgeOutput schema。
"""


class ClaimJudgement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    verdict: Literal["supported", "refuted", "not_mentioned"]
    evidence_quotes: list[str] = Field(default_factory=list)
    self_conflict: bool = False
    reason: str


class JudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    judgements: list[ClaimJudgement]


# ---------------------------------------------------------------------------
# 纯逻辑：可在 0 调用下被测试覆盖
# ---------------------------------------------------------------------------


def load_scorable_claims(path: Any = GOLDEN) -> tuple[list[dict[str, Any]], int]:
    """只取有真实报告可比的标准答案，返回 (可评条目, 跳过条数)。"""
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    claims = [r for r in rows if r.get("kind") == "claim"]
    scorable = [r for r in claims if r.get("has_real_report_to_score") is True]
    return scorable, len(claims) - len(scorable)


def load_report(path: Any = REPORT) -> tuple[str, dict[str, Any]]:
    data = json.loads(open(path, encoding="utf-8").read())
    report = str(data.get("report", ""))
    if not report:
        raise RuntimeError(f"{path} 里没有报告正文，拒绝把空卷子送去批改")
    return report, data


def build_payload(claims: list[dict[str, Any]], report: str, company: str) -> str:
    """只送 claim_id + expected_text；出处/AI 备注/人工备注一律不进 prompt。"""
    return json.dumps(
        {
            "company": company,
            "golden_claims": [
                {"claim_id": c["id"], "expected_text": c["expected_text"]} for c in claims
            ],
            "report": report,
        },
        ensure_ascii=False,
    )


def normalise(text: str) -> str:
    text = re.sub(r"\[\d+\]", " ", text)  # 行内引用编号不属于事实文字
    return re.sub(r"\s+", " ", text).strip().casefold()


def quote_in_report(quote: str, report: str) -> bool:
    q = normalise(quote)
    return bool(q) and q in normalise(report)


def assemble(
    claims: list[dict[str, Any]],
    report: str,
    judged: JudgeOutput,
    *,
    status: str,
    is_real_judge: bool,
    usage: dict[str, Any] | None,
    config: dict[str, Any] | None,
    error: str | None,
    skipped_claims: int,
    company: str,
    elapsed_ms: float,
    isolation: dict[str, Any],
) -> dict[str, Any]:
    """把模型输出与可机器核验的校验结果合成最终产物。"""
    by_id = {c["id"]: c for c in claims}
    seen: dict[str, ClaimJudgement] = {}
    duplicates: list[str] = []
    for j in judged.judgements:
        if j.claim_id in seen:
            duplicates.append(j.claim_id)
        seen[j.claim_id] = j
    missing = [c["id"] for c in claims if c["id"] not in seen]
    unknown = [k for k in seen if k not in by_id]
    schema_ok = not (missing or unknown or duplicates)

    verdicts: list[dict[str, Any]] = []
    for c in claims:
        j = seen.get(c["id"])
        if j is None:
            verdicts.append(
                {
                    "claim_id": c["id"],
                    "expected_text": c["expected_text"],
                    "report_section": c.get("report_section"),
                    "verdict": None,
                    "self_conflict": None,
                    "evidence_quotes": [],
                    "quotes_verified": None,
                    "unverified_quotes": [],
                    "reason": "judge 未返回该条，如实留空，不补判",
                    # 未判定 ≠ 证据句核对失败；用 None 区分，别把它混进失败计数
                    "quote_check_failed": None,
                }
            )
            continue
        unverified = [q for q in j.evidence_quotes if not quote_in_report(q, report)]
        quotes_verified = bool(j.evidence_quotes) and not unverified
        # supported / refuted 必须有可核验的逐字证据，否则判定不可靠
        quote_check_failed = j.verdict in ("supported", "refuted") and not quotes_verified
        verdicts.append(
            {
                "claim_id": c["id"],
                "expected_text": c["expected_text"],
                "report_section": c.get("report_section"),
                "verdict": j.verdict,
                "self_conflict": j.self_conflict,
                "evidence_quotes": j.evidence_quotes,
                "quotes_verified": quotes_verified,
                "unverified_quotes": unverified,
                "reason": j.reason,
                "quote_check_failed": quote_check_failed,
            }
        )

    summary = {
        "scored_claims": len(claims),
        "supported": sum(v["verdict"] == "supported" for v in verdicts),
        "refuted": sum(v["verdict"] == "refuted" for v in verdicts),
        "not_mentioned": sum(v["verdict"] == "not_mentioned" for v in verdicts),
        "unjudged": sum(v["verdict"] is None for v in verdicts),
        "self_conflict": sum(v["self_conflict"] is True for v in verdicts),
        "quote_check_failed": sum(v["quote_check_failed"] is True for v in verdicts),
    }
    return {
        "purpose": "S8.4 语义批改：人工核验的中文标准答案 vs 系统生成的英文真实报告",
        "status": status,
        "error": error,
        "method": "AI judge (qwen-plus structured output)，非人工判定",
        "is_real_judge": is_real_judge,
        "is_human_adjudicated": False,
        "usable_as_resume_metric": False,
        "metric_boundary": {
            "may_be_called": "5 条标准答案的 AI 判定明细（可复核、附逐字证据句）",
            "must_not_be_called": "准确率 / 幻觉率 / 引用可追溯率 / p95 / 成本单价",
            "reasons": [
                "样本仅 1 家公司 5 条标准答案，其余 20 条没有真实报告可比",
                "judge 是 AI 判定，未经人工抽检一致率校准；人出题、AI 批卷仍非人工评分",
                "golden 的引用层（最终 URL 是否支撑事实）未核验，不能算引用类指标",
            ],
        },
        "dataset": {
            "golden_file": "evals/golden_live.jsonl",
            "report_file": "evals/live_run.json",
            "company": company,
            "total_claims_in_golden": len(claims) + skipped_claims,
            "scored_claims": len(claims),
            "skipped_claims": skipped_claims,
            "skipped_reason": "其余公司没有真实报告可比，不得凭空生成卷子",
            "report_chars": len(report),
            "claim_fields_sent_to_judge": ["claim_id", "expected_text"],
            "claim_fields_withheld_from_judge": [
                "source_url",
                "source_content",
                "evidence_quote_from_ai_check",
                "ai_check",
                "ai_note",
                "human_note",
                "original_fact",
            ],
        },
        "config": config,
        "usage": usage,
        "schema_check": {
            "ok": schema_ok,
            "missing_claim_ids": missing,
            "unknown_claim_ids": unknown,
            "duplicate_claim_ids": sorted(set(duplicates)),
            "verdict_values_allowed": list(VERDICTS),
        },
        "judgements": verdicts,
        "summary": summary,
        "verdict_note": (
            "supported 表示报告有支持该事实的陈述，不代表该陈述的来源 URL 真的支持它；"
            "refuted 含报告自相矛盾的情形；not_mentioned 表示未写到，不等于系统答错。"
            "quote_check_failed=true 的条目证据句未能在报告中逐字核到，判定不可靠；"
            "quote_check_failed=null 表示 judge 未返回该条，单独计入 unjudged。"
        ),
        "isolation": isolation,
        "elapsed_ms": elapsed_ms,
        "elapsed_note": "本机墙钟，非确定性字段，不参与 CI 比对",
    }


# ---------------------------------------------------------------------------
# 执行路径
# ---------------------------------------------------------------------------


@contextmanager
def tavily_guard() -> Iterator[list[int]]:
    """judge 不允许检索；被调用即抛错，退出时还原，不污染同进程后续调用。"""
    calls: list[int] = []
    try:
        from tavily import AsyncTavilyClient
    except ImportError:
        yield calls
        return
    original = AsyncTavilyClient.search

    def _sentinel(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        raise AssertionError("S8.4 judge 禁止调用 Tavily 检索")

    AsyncTavilyClient.search = _sentinel  # type: ignore[assignment]
    try:
        yield calls
    finally:
        AsyncTavilyClient.search = original  # type: ignore[assignment]


def common_inputs() -> tuple[list[dict[str, Any]], int, str, str]:
    claims, skipped = load_scorable_claims()
    if not claims:
        raise RuntimeError("没有 has_real_report_to_score=true 的标准答案，拒绝空判")
    report, data = load_report()
    company = str(data.get("company") or "unknown")
    return claims, skipped, report, company


def run_dry() -> dict[str, Any]:
    """0 调用链路自检：用固定占位输出验证 assemble/证据句校验/产物结构。"""
    claims, skipped, report, company = common_inputs()
    placeholder = JudgeOutput(
        judgements=[
            ClaimJudgement(
                claim_id=c["id"],
                verdict="not_mentioned",
                evidence_quotes=[],
                self_conflict=False,
                reason="dry-run 占位，不是模型判定",
            )
            for c in claims
        ]
    )
    result = assemble(
        claims,
        report,
        placeholder,
        status="dry_run",
        is_real_judge=False,
        usage=None,
        config=None,
        error=None,
        skipped_claims=skipped,
        company=company,
        elapsed_ms=0.0,
        isolation={
            "llm_requests": 0,
            "tavily_client_search_calls": 0,
            "document_tool_constructed": False,
        },
    )
    result["dry_run_note"] = (
        "占位判定，全部为 not_mentioned；仅用于验证 0 调用链路，"
        "must_not_be_used_as_metric=true，不得写入简历或文档当作评测结果"
    )
    result["must_not_be_used_as_metric"] = True
    DRYRUN_OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def run_live() -> dict[str, Any]:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "缺少 DASHSCOPE_API_KEY。请从 Windows 用户级变量 SYSTEM_ALIYUN_APIKEY "
            "映射到本进程内存后运行，不要把密钥写进 .env 或命令行参数。"
        )
    env = {**LIVE_ENV, "DASHSCOPE_API_KEY": key}
    settings = load_settings(environ=env)
    if settings.models.roles["briefing"] != "qwen-plus":
        raise RuntimeError(
            f"模型名未锁定：briefing={settings.models.roles['briefing']!r}，拒绝白烧一次真实请求"
        )
    creds = resolve_llm_credentials(environ=env)
    if creds.provider != "dashscope":
        raise RuntimeError(f"provider 未锁定：{creds.provider!r}")

    # 关闭重试：生产 settings 的 max_retries=1，这里把模型请求硬锁定在 1 次。
    judge_settings = apply_overrides(settings, {"models.max_retries": 0})
    model = make_chat_model(judge_settings, "briefing", credentials=creds)
    prompt = ChatPromptTemplate.from_messages(
        [("system", _SYSTEM_PROMPT), ("human", "{payload}")]
    )
    chain = prompt | model.with_structured_output(JudgeOutput, method="function_calling")

    claims, skipped, report, company = common_inputs()
    payload = build_payload(claims, report, company)
    for marker in ("source_url", "source_content", "ai_note", "human_note", "original_fact"):
        if f'"{marker}"' in payload:
            raise RuntimeError(f"prompt 疑似泄漏字段 {marker}，拒绝发起真实请求")

    started = time.perf_counter()
    judged: JudgeOutput | None = None
    error: str | None = None
    usage: dict[str, Any] = {}
    with tavily_guard() as tavily_calls:
        try:
            with get_openai_callback() as cb:
                judged = asyncio.run(chain.ainvoke({"payload": payload}))
            usage = {
                "successful_requests": cb.successful_requests,
                "total_tokens": cb.total_tokens,
                "prompt_tokens": cb.prompt_tokens,
                "completion_tokens": cb.completion_tokens,
                "total_cost_usd": None,
                "cost_note": (
                    "get_openai_callback 的价目表只覆盖 OpenAI 官方模型；"
                    "qwen-plus 单价不在此表内，故不套用、不编造成本数字"
                ),
            }
        except Exception as exc:  # 真实故障如实落盘，绝不吞、绝不重试
            error = f"{type(exc).__name__}: {str(exc)[:400]}"
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    tavily_call_count = len(tavily_calls)

    if error and key in error:
        error = "错误信息中疑似含密钥，已整体屏蔽"

    if judged is None:
        # 失败也要留一份可审计的空判定，不能假装跑过
        judged = JudgeOutput(judgements=[])
    status = "ok" if error is None else "failed"
    result = assemble(
        claims,
        report,
        judged,
        status=status,
        is_real_judge=error is None,
        usage=usage,
        config={
            "provider": creds.provider,
            "model": judge_settings.models.roles["briefing"],
            "base_url": creds.base_url,
            "temperature": judge_settings.models.temperature,
            "max_retries_in_judge": 0,
            "max_retries_in_production": settings.models.max_retries,
            "structured_output_method": "function_calling",
            "role_slot_reused": "briefing",
        },
        error=error,
        skipped_claims=skipped,
        company=company,
        elapsed_ms=elapsed_ms,
        isolation={
            "llm_requests_cap": 1,
            "llm_requests_cap_note": "max_retries=0，脚本不做任何重试；失败即 failed",
            "tavily_client_search_calls": tavily_call_count,
            "document_tool_constructed": False,
            "tavily_credits_used": 0,
        },
    )
    result["credentials"] = {
        "api_key_env_var": "DASHSCOPE_API_KEY",
        "api_key_characters": len(key),
        "api_key_printed": 0,
        "api_key_in_artifact": False,
        "note": "key 仅存在于本进程内存；产物不写值、不写 .env、不进 git",
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    wants_live = "--live" in sys.argv[1:]
    opted_in = os.environ.get(OPT_IN_VAR) == "1"
    if wants_live and not opted_in:
        raise SystemExit(
            f"真实判定需同时给 --live 和 {OPT_IN_VAR}=1；本次不发起任何模型请求"
        )
    if not wants_live:
        r = run_dry()
        print(f"[S8.4 judge dry-run] 0 调用 -> {DRYRUN_OUTPUT.relative_to(ROOT)}")
        print(f"  scored={r['summary']['scored_claims']} skipped={r['dataset']['skipped_claims']}")
        print("  这是占位判定，不是评测结果；不得写进简历")
        return 0
    r = run_live()
    print(f"[S8.4 judge live] status={r['status']} -> {OUTPUT.relative_to(ROOT)}")
    print(
        f"  usage={r['usage'].get('total_tokens', 'n/a')} tokens, "
        f"requests={r['usage'].get('successful_requests', 'n/a')}, "
        f"tavily_calls={r['isolation']['tavily_client_search_calls']}"
    )
    print(f"  summary={r['summary']}")
    if r["error"]:
        print(f"  error={r['error'][:200]}")
    return 0 if r["status"] == "ok" and r["schema_check"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
