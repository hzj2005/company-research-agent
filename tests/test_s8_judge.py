"""S8.4 语义 judge 的离线护栏（0 次真实模型 / Tavily 调用）。

真实判定由 `evals/judge.py --live` 单独执行并落在 evals/live_score.json；
本文件只锁死纯逻辑与红线，避免用「本地模拟的分」冒充实测结论。
"""

from __future__ import annotations

import json
import sys
from typing import Any

import pytest

from evals import judge

REPORT = """# Notion Research Report

## Company Overview

- Notion was founded in 2013. [6]
- Notion was founded in 2014. [4]
- Notion's headquarters is located at 51 Lloyd Baker Street, London. [4]

## References

[4] https://example.org/a
[6] https://example.org/b
"""

CLAIMS: list[dict[str, Any]] = [
    {
        "id": "notion:company:0",
        "expected_text": "Notion 于 2013 年创办",
        "report_section": "Company Overview",
        "source_url": "https://secret.example/should-not-leak",
        "source_content": "Launched: 2013",
        "ai_note": "内部核对备注，禁止进 prompt",
        "human_note": "人工备注，禁止进 prompt",
        "original_fact": "旧草稿，禁止进 prompt",
    },
    {
        "id": "notion:company:1",
        "expected_text": "Notion 总部位于旧金山",
        "report_section": "Company Overview",
        "source_url": "https://another-secret.example/",
    },
]


def _judged(*items: judge.ClaimJudgement) -> judge.JudgeOutput:
    return judge.JudgeOutput(judgements=list(items))


def _assemble(judged: judge.JudgeOutput, report: str = REPORT) -> dict[str, Any]:
    return judge.assemble(
        CLAIMS,
        report,
        judged,
        status="ok",
        is_real_judge=True,
        usage=None,
        config=None,
        error=None,
        skipped_claims=20,
        company="Notion",
        elapsed_ms=1.0,
        isolation={"llm_requests_cap": 1, "tavily_client_search_calls": 0},
    )


# --- 红线 1：不泄漏出处 ------------------------------------------------------


def test_payload_contains_only_id_and_expected_text() -> None:
    payload = judge.build_payload(CLAIMS, REPORT, "Notion")
    data = json.loads(payload)
    assert data["company"] == "Notion"
    assert data["report"] == REPORT
    assert data["golden_claims"] == [
        {"claim_id": c["id"], "expected_text": c["expected_text"]} for c in CLAIMS
    ]
    for leaked in (
        "source_url",
        "source_content",
        "ai_note",
        "human_note",
        "original_fact",
        "secret.example",
        "内部核对备注",
    ):
        assert leaked not in payload, f"prompt 泄漏了 {leaked}"


def test_withheld_fields_declared_in_artifact() -> None:
    r = _assemble(_judged())
    assert r["dataset"]["claim_fields_sent_to_judge"] == ["claim_id", "expected_text"]
    assert "source_url" in r["dataset"]["claim_fields_withheld_from_judge"]
    assert "ai_note" in r["dataset"]["claim_fields_withheld_from_judge"]


# --- 红线 2：证据句必须逐字可核 ----------------------------------------------


def test_verbatim_quote_with_citation_marker_matches() -> None:
    assert judge.quote_in_report("Notion was founded in 2013.", REPORT)
    assert judge.quote_in_report("  Notion   was founded in 2013. [6] ", REPORT)


def test_reference_title_cannot_impersonate_body_evidence() -> None:
    """修复前：References 里的标题能骗过 quote_in_report。"""
    body, sep, refs = REPORT.partition("## References")
    assert sep
    title = "[4] https://example.org/a"
    assert title in refs and title not in body
    assert judge.quote_in_report("https://example.org/a", REPORT) is False
    assert judge.report_body(REPORT) == body


@pytest.mark.parametrize(
    "fake",
    [
        "Notion 于 2013 年创办",  # 中文翻译，不是报告原文
        "Notion was founded in 2012.",  # 编造的年份
        "This sentence was invented by the judge.",  # 整句编造
        "",  # 空引文
    ],
)
def test_fabricated_or_translated_quote_is_rejected(fake: str) -> None:
    assert judge.quote_in_report(fake, REPORT) is False


def test_supported_with_fabricated_quote_is_flagged_unreliable() -> None:
    r = _assemble(
        _judged(
            judge.ClaimJudgement(
                claim_id="notion:company:0",
                verdict="supported",
                evidence_quotes=["Notion was founded in 2012."],
                reason="编造证据测试",
            )
        )
    )
    v = r["judgements"][0]
    assert v["quotes_verified"] is False
    assert v["quote_check_failed"] is True
    assert v["unverified_quotes"] == ["Notion was founded in 2012."]
    assert r["summary"]["quote_check_failed"] == 1
    assert r["summary"]["unjudged"] == 1  # 另一条未返回，如实留空
    assert r["judgements"][1]["quote_check_failed"] is None  # 未判定 ≠ 证据核对失败


def test_self_conflicting_report_keeps_both_verbatim_quotes() -> None:
    r = _assemble(
        _judged(
            judge.ClaimJudgement(
                claim_id="notion:company:0",
                verdict="refuted",
                evidence_quotes=[
                    "Notion was founded in 2013.",
                    "Notion was founded in 2014.",
                ],
                self_conflict=True,
                reason="同一报告给出两个成立年份",
            )
        )
    )
    v = r["judgements"][0]
    assert v["quotes_verified"] is True
    assert v["quote_check_failed"] is False
    assert v["self_conflict"] is True
    assert r["summary"]["self_conflict"] == 1


def test_not_mentioned_does_not_require_evidence() -> None:
    r = _assemble(
        _judged(
            judge.ClaimJudgement(
                claim_id=CLAIMS[0]["id"],
                verdict="not_mentioned",
                evidence_quotes=[],
                reason="报告未提及",
            ),
            judge.ClaimJudgement(
                claim_id=CLAIMS[1]["id"],
                verdict="refuted",
                evidence_quotes=["Notion's headquarters is located at 51 Lloyd Baker Street, London."],
                reason="报告写伦敦",
            ),
        )
    )
    assert r["summary"] == {
        "scored_claims": 2,
        "supported": 0,
        "refuted": 1,
        "not_mentioned": 1,
        "unjudged": 0,
        "self_conflict": 0,
        "quote_check_failed": 0,
    }
    assert r["judgements"][0]["quotes_verified"] is False
    assert r["judgements"][0]["quote_check_failed"] is False


def test_not_mentioned_with_fabricated_quote_is_flagged() -> None:
    """修复前：not_mentioned 塞编造引文，unverified_quotes 有值却不算失败。"""
    r = _assemble(
        _judged(
            judge.ClaimJudgement(
                claim_id=CLAIMS[0]["id"],
                verdict="not_mentioned",
                evidence_quotes=["THIS IS INVENTED BY JUDGE"],
                reason="不该给引文",
            ),
            judge.ClaimJudgement(
                claim_id=CLAIMS[1]["id"],
                verdict="not_mentioned",
                evidence_quotes=[],
                reason="正常",
            ),
        )
    )
    assert r["judgements"][0]["quote_check_failed"] is True
    assert r["judgements"][0]["unverified_quotes"] == ["THIS IS INVENTED BY JUDGE"]
    assert r["judgements"][1]["quote_check_failed"] is False
    assert r["summary"]["quote_check_failed"] == 1


# --- schema 对齐 -------------------------------------------------------------


def test_missing_unknown_and_duplicate_ids_are_reported_not_silently_fixed() -> None:
    r = _assemble(
        _judged(
            judge.ClaimJudgement(
                claim_id="notion:company:0", verdict="not_mentioned", reason="x"
            ),
            judge.ClaimJudgement(
                claim_id="notion:company:0", verdict="refuted", reason="duplicate"
            ),
            judge.ClaimJudgement(claim_id="ghost", verdict="supported", reason="unknown"),
        )
    )
    s = r["schema_check"]
    assert s["ok"] is False
    assert s["missing_claim_ids"] == ["notion:company:1"]
    assert s["unknown_claim_ids"] == ["ghost"]
    assert s["duplicate_claim_ids"] == ["notion:company:0"]
    assert len(r["judgements"]) == 2  # 不凭空多造条目


def test_incomplete_schema_downgrades_status_to_partial() -> None:
    """修复前：模型少返回 4 条，产物 status 仍写 ok。"""
    r = _assemble(
        _judged(
            judge.ClaimJudgement(
                claim_id=CLAIMS[0]["id"], verdict="not_mentioned", reason="only one"
            )
        )
    )
    assert r["status"] == "partial"
    assert r["schema_check"]["ok"] is False
    assert r["summary"]["unjudged"] == len(CLAIMS) - 1


def test_verdict_enum_rejects_invalid_value() -> None:
    with pytest.raises(ValueError):
        judge.ClaimJudgement(claim_id="x", verdict="correct", reason="bad")


# --- 红线 3：1 次请求 / 0 检索 -----------------------------------------------


def test_tavily_guard_blocks_calls_and_restores_original() -> None:
    from tavily import AsyncTavilyClient

    original = AsyncTavilyClient.search
    with judge.tavily_guard() as calls:
        with pytest.raises(AssertionError, match="禁止调用 Tavily"):
            AsyncTavilyClient.search(None, query="should not run")
    assert calls == [1]
    assert AsyncTavilyClient.search is original, "守卫必须还原，不能污染同进程后续调用"


def test_source_locks_one_request_and_no_retry() -> None:
    src = open(judge.__file__, encoding="utf-8").read()
    assert '"models.max_retries": 0' in src
    assert '"llm_requests_cap": 1' in src
    assert '"document_tool_constructed": False' in src
    # 真实调用只能出现在 main() 的显式放行分支，模块导入路径不得自动发起
    assert src.count("r = run_live()") == 1
    assert '"tavily_credits_used": 0' in src
    assert "if not wants_live:\n        r = run_dry()" in src


def test_real_run_requires_both_flag_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["judge.py", "--live"])
    monkeypatch.delenv(judge.OPT_IN_VAR, raising=False)
    called: list[str] = []
    monkeypatch.setattr(judge, "run_live", lambda: called.append("live") or {})
    with pytest.raises(SystemExit, match="不发起任何模型请求"):
        judge.main()
    assert called == [], "缺 opt-in 时绝不能发起真实请求"


def test_preflight_failure_leaves_successful_artifact_untouched(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    success = tmp_path / "live_score.json"
    success.write_text('{"status": "ok"}', encoding="utf-8")
    failed = tmp_path / "live_score_failed.json"
    monkeypatch.setattr(judge, "OUTPUT", success)
    monkeypatch.setattr(judge, "PREFLIGHT_OUTPUT", failed)
    monkeypatch.setattr(judge, "run_live", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(sys, "argv", ["judge.py", "--live"])
    monkeypatch.setenv(judge.OPT_IN_VAR, "1")

    assert judge.main() == 1
    assert json.loads(success.read_text(encoding="utf-8"))["status"] == "ok"
    d = json.loads(failed.read_text(encoding="utf-8"))
    assert d["status"] == "failed" and d["phase"] == "preflight"
    assert d["llm_requests"] == 0 and d["tavily_credits_used"] == 0
    assert d["is_real_judge"] is False


def test_preflight_failure_masks_api_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(judge, "PREFLIGHT_OUTPUT", tmp_path / "failed.json")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "SUPERSECRET123")
    d = judge.write_preflight_failure(RuntimeError("bad key SUPERSECRET123"))
    assert "SUPERSECRET123" not in json.dumps(d, ensure_ascii=False)
    assert "整体屏蔽" in d["error"]


def test_fingerprints_cover_inputs_and_track_changes(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    golden = tmp_path / "g.jsonl"
    report = tmp_path / "r.json"
    golden.write_text("a", encoding="utf-8")
    report.write_text("b", encoding="utf-8")
    monkeypatch.setattr(judge, "GOLDEN", golden)
    monkeypatch.setattr(judge, "REPORT", report)
    a = judge.fingerprints("payload-A")
    b = judge.fingerprints("payload-B")
    for k in (
        "golden_live_jsonl_sha256",
        "live_run_json_sha256",
        "judge_py_sha256",
        "system_prompt_sha256",
        "payload_sha256",
    ):
        assert len(a[k]) == 64, k
    assert a["recorded_at"] == "runtime"
    assert a["payload_sha256"] != b["payload_sha256"]
    golden.write_text("changed", encoding="utf-8")
    assert (
        judge.fingerprints("payload-A")["golden_live_jsonl_sha256"]
        != a["golden_live_jsonl_sha256"]
    )


# --- 红线 4：不冒充人工 / 不冒充指标 ----------------------------------------


def test_artifact_declares_ai_judge_not_human_and_not_metric() -> None:
    r = _assemble(_judged())
    assert r["is_human_adjudicated"] is False
    assert r["usable_as_resume_metric"] is False
    assert "AI judge" in r["method"]
    boundary = r["metric_boundary"]
    assert "准确率" in boundary["must_not_be_called"]
    assert "幻觉率" in boundary["must_not_be_called"]
    assert any("1 家公司 5 条" in x for x in boundary["reasons"])
    assert r["dataset"]["skipped_claims"] == 20


def test_dry_run_is_zero_call_and_explicitly_not_a_result(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judge, "DRYRUN_OUTPUT", tmp_path / "dry.json")
    r = judge.run_dry()
    assert r["status"] == "dry_run"
    assert r["is_real_judge"] is False
    assert r["must_not_be_used_as_metric"] is True
    assert r["isolation"]["llm_requests"] == 0
    assert r["isolation"]["tavily_client_search_calls"] == 0
    assert r["summary"]["not_mentioned"] == len(r["judgements"])  # 全占位，不伪造判定
    assert (tmp_path / "dry.json").exists()


def test_scorable_claims_only_come_from_real_report() -> None:
    claims, skipped = judge.load_scorable_claims()
    assert len(claims) == 5
    assert skipped == 20
    assert {c["case"] for c in claims} == {"notion"}
    assert all(c["has_real_report_to_score"] is True for c in claims)


# --- 真实产物完整性：只有跑过真机才检查，没跑过就诚实跳过 --------------------

LIVE_SCORE = judge.ROOT / "evals" / "live_score.json"


@pytest.mark.skipif(
    not LIVE_SCORE.exists(), reason="本地未执行过真实 judge，不伪造真实产物断言"
)
def test_real_score_artifact_is_auditable_and_verifiable() -> None:
    d = json.loads(LIVE_SCORE.read_text(encoding="utf-8"))
    assert d["status"] == "ok"
    assert d["is_real_judge"] is True
    assert d["is_human_adjudicated"] is False
    assert d["usable_as_resume_metric"] is False
    assert d["usage"]["successful_requests"] == 1, "放行的额度就是 1 次请求"
    assert d["usage"]["total_cost_usd"] is None, "qwen-plus 单价未核实，不得编造成本"
    assert d["isolation"]["tavily_client_search_calls"] == 0
    assert d["isolation"]["tavily_credits_used"] == 0
    assert d["dataset"]["scored_claims"] == 5
    assert d["dataset"]["skipped_claims"] == 20
    assert d["schema_check"]["ok"] is True

    s = d["summary"]
    assert s["supported"] + s["refuted"] + s["not_mentioned"] + s["unjudged"] == len(
        d["judgements"]
    )
    assert s["supported"] == sum(v["verdict"] == "supported" for v in d["judgements"])

    report = json.loads(
        (judge.ROOT / "evals" / "live_run.json").read_text(encoding="utf-8")
    )["report"]
    body = judge.report_body(report)
    assert len(body) < len(report), "真实报告必须有独立的 References 段"
    for v in d["judgements"]:
        assert v["quote_check_failed"] is not True, f"{v['claim_id']} 证据句核不上"
        for q in v["evidence_quotes"]:
            # 双层：精确逐字 + 必须落在正文（不能来自 References 标题）
            assert q in report, f"{v['claim_id']} 的引文不是报告原文逐字片段：{q[:60]}"
            assert q in body, f"{v['claim_id']} 的引文来自 References 而非正文：{q[:60]}"
