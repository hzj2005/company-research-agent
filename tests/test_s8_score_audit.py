"""S8.4 事后审计脚本的离线护栏（0 次模型 / Tavily 调用）。

审计只读既有产物，不重新判定、不覆盖原始 live_score.json。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from evals import audit_score

AUDIT = audit_score.ROOT / "evals" / "live_score_audit.json"
SCORE = audit_score.ROOT / "evals" / "live_score.json"

REPORT = """# Notion Research Report

## Company Overview

- Notion was founded in 2013. [6]

## References

[8] Notion Reaches $10 Billion Valuation — https://www.forbes.com/example
"""


def _score(quotes: list[str], verdict: str = "supported") -> dict[str, Any]:
    return {
        "judgements": [
            {
                "claim_id": "x:0",
                "verdict": verdict,
                "evidence_quotes": quotes,
                "quote_check_failed": False,
                "reason": "fixture",
            }
        ]
    }


def test_recheck_accepts_body_quote_and_reports_no_delta() -> None:
    r = audit_score.recheck(_score(["Notion was founded in 2013."]), REPORT)
    assert r["delta_vs_original"] == []
    assert r["rows"][0]["quotes_present_and_all_in_body"] is True
    assert r["rows"][0]["quote_check_failed_recomputed"] is False
    assert r["verdicts_changed"] == []


def test_recheck_rejects_reference_only_quote() -> None:
    """审计必须能抓出「引文只在 References 里」的伪造证据。"""
    r = audit_score.recheck(_score(["Notion Reaches $10 Billion Valuation"]), REPORT)
    row = r["rows"][0]
    assert row["quotes_present_and_all_in_body"] is False
    assert row["unverified_quotes_under_fixed_rule"] == ["Notion Reaches $10 Billion Valuation"]
    assert row["quote_check_failed_recomputed"] is True
    assert r["delta_vs_original"] == [
        {"claim_id": "x:0", "original": False, "recomputed": True}
    ]


def test_recheck_never_changes_verdicts() -> None:
    r = audit_score.recheck(_score(["INVENTED"], verdict="refuted"), REPORT)
    assert r["verdicts_changed"] == []
    assert r["rows"][0]["verdict"] == "refuted"


@pytest.mark.skipif(not AUDIT.exists(), reason="本地未生成审计产物，不伪造断言")
def test_real_audit_is_post_run_zero_call_and_hash_anchored() -> None:
    d = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert d["recorded_after_run"] is True
    assert d["source_artifact_modified_by_this_script"] is False
    assert d["isolated_calls"] == {"llm_requests": 0, "tavily_credits_used": 0}
    actual = hashlib.sha256(SCORE.read_bytes()).hexdigest()
    assert d["source_artifact_sha256"] == actual, "审计必须锚定到这份具体的判定产物"
    assert "准确率" in d["metric_boundary_note"]
    assert "仍未测" in d["metric_boundary_note"]
    assert d["known_issues_fixed"], "审计必须列明修了哪些问题"


@pytest.mark.skipif(not AUDIT.exists(), reason="本地未生成审计产物，不伪造断言")
def test_real_audit_recheck_shows_no_change_to_five_verdicts() -> None:
    d = json.loads(AUDIT.read_text(encoding="utf-8"))
    score = json.loads(SCORE.read_text(encoding="utf-8"))
    assert d["recheck"]["delta_vs_original"] == []
    assert [r["verdict"] for r in d["recheck"]["rows"]] == [
        v["verdict"] for v in score["judgements"]
    ]
    assert d["recheck"]["verdicts_changed"] == []
    p = d["provenance"]
    for k in (
        "golden_live_jsonl_sha256",
        "live_run_json_sha256",
        "judge_py_current_sha256",
        "judge_py_at_run_commit_sha256",
    ):
        assert p[k] and len(p[k]) == 64, k
    assert p["judge_py_at_run_commit_available"] is True
