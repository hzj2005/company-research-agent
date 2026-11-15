"""S8.4 复查审计：0 次模型请求 / 0 Tavily credits，给既有真实判定补可追溯性。

背景：首次真实判定（`evals/live_score.json`）跑完后复查出三处校验口径漏洞
（References 标题能冒充正文证据、not_mentioned 塞编造引文不标失败、
schema 缺条目时 status 仍写 ok）和一处可复现性缺口（产物无输入/代码指纹）。
漏洞已在 `evals/judge.py` 修好，但**不能拿修改后的代码假装当时就是那样跑的**。

本脚本做两件事，全程只读、不重新调用模型、不覆盖原始产物：
1. 按新口径（证据句只在报告正文核）重算 5 条判定，给出与原始产物的差异；
2. 事后补记 golden / 报告 / judge.py / git commit 的 sha256，并明确
   `recorded_after_run=true`：这是事后补记，不等价于运行时采集。

下次真实运行会由 `judge.py` 的 `fingerprints()` 在运行时自动写 provenance。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from typing import Any

from config.loader import ROOT
from evals.judge import quote_in_report, report_body

SCORE = ROOT / "evals" / "live_score.json"
REPORT = ROOT / "evals" / "live_run.json"
GOLDEN = ROOT / "evals" / "golden_live.jsonl"
JUDGE_PY = ROOT / "evals" / "judge.py"
OUTPUT = ROOT / "evals" / "live_score_audit.json"

# 真实判定完成后的首个提交；judge.py 在运行结束到该提交之间未被编辑。
RUN_COMMIT = "3e16906"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_show(commit: str, path: str) -> str | None:
    """取提交时的文件文本；git 不可用/路径不存在时如实返回 None。"""
    try:
        proc = subprocess.run(
            ["git", "show", f"{commit}:{path}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def recheck(score: dict[str, Any], report: str) -> dict[str, Any]:
    """用修复后的 quote_in_report 重算，只报差异，不改原始判定。"""
    rows: list[dict[str, Any]] = []
    deltas: list[dict[str, Any]] = []
    for v in score["judgements"]:
        unverified = [q for q in v["evidence_quotes"] if not quote_in_report(q, report)]
        verified = bool(v["evidence_quotes"]) and not unverified
        verdict = v["verdict"]
        recomputed = bool(unverified) or (
            verdict in ("supported", "refuted") and not verified
        )
        rows.append(
            {
                "claim_id": v["claim_id"],
                "verdict": verdict,
                "evidence_quotes": v["evidence_quotes"],
                "quotes_present_and_all_in_body": not unverified and bool(v["evidence_quotes"]),
                "unverified_quotes_under_fixed_rule": unverified,
                "quote_check_failed_original": v["quote_check_failed"],
                "quote_check_failed_recomputed": recomputed if verdict is not None else None,
            }
        )
        if verdict is not None and v["quote_check_failed"] != recomputed:
            deltas.append(
                {
                    "claim_id": v["claim_id"],
                    "original": v["quote_check_failed"],
                    "recomputed": recomputed,
                }
            )
    return {
        "rule_after_fix": "证据句只在报告正文核（排除 ## References），归一化空白/[n]/大小写",
        "rows": rows,
        "delta_vs_original": deltas,
        "verdicts_changed": [],  # 本审计不重新判定，verdict 一律不动
        "conclusion": (
            "修复未改变既有 5 条判定的 verdict 与 quote_check_failed 结论"
            if not deltas
            else "存在差异，需人工复核，不得直接沿用旧结论"
        ),
    }


def build() -> dict[str, Any]:
    score = json.loads(SCORE.read_text(encoding="utf-8"))
    report = json.loads(REPORT.read_text(encoding="utf-8"))["report"]
    at_commit = git_show(RUN_COMMIT, "evals/judge.py")

    return {
        "purpose": "S8.4 复查：为既有真实判定补事后可追溯性与新口径重核",
        "source_artifact": "evals/live_score.json",
        "source_artifact_sha256": sha(SCORE.read_bytes()),
        "source_artifact_modified_by_this_script": False,
        "recorded_after_run": True,
        "recorded_after_run_note": (
            "以下是事后补记，不是运行时采集；不等价于 judge.py 下次运行时的 "
            "fingerprints() 字段。原始判定 verdict/reason/evidence_quotes 一字未改。"
        ),
        "isolated_calls": {"llm_requests": 0, "tavily_credits_used": 0},
        "provenance": {
            "git_commit_after_run": RUN_COMMIT,
            "git_commit_note": (
                "真实判定完成后立即提交；judge.py 在运行结束到该提交之间未编辑，"
                "故该提交的 judge.py 可代表运行时版本（依据 git 历史推定，非运行时采集）"
            ),
            "golden_live_jsonl_sha256": sha(GOLDEN.read_bytes()),
            "live_run_json_sha256": sha(REPORT.read_bytes()),
            "judge_py_current_sha256": sha(JUDGE_PY.read_bytes()),
            "judge_py_at_run_commit_sha256": sha(at_commit.encode("utf-8")) if at_commit else None,
            "judge_py_at_run_commit_available": at_commit is not None,
            "report_body_chars": len(report_body(report)),
            "report_total_chars": len(report),
        },
        "recheck": recheck(score, report),
        "known_issues_fixed": [
            "References 标题不再能冒充正文证据句",
            "任何 verdict 塞编造引文都会标 quote_check_failed",
            "schema 缺条目时 status 改为 partial 而非 ok",
            "前置检查失败写 live_score_failed.json，不覆盖已有成功产物",
            "新增运行时 fingerprints() 输入/代码指纹",
        ],
        "metric_boundary_note": (
            "本审计不产出新指标，不改变 usable_as_resume_metric=false；"
            "真实准确率 / 幻觉率 / p95 / 成本单价仍未测"
        ),
    }


def main() -> int:
    result = build()
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[S8.4 audit] 0 调用 -> {OUTPUT.relative_to(ROOT)}")
    print(f"  recheck: {result['recheck']['conclusion']}")
    print(f"  deltas={len(result['recheck']['delta_vs_original'])}")
    p = result["provenance"]
    print(f"  judge_py_at_run_commit_available={p['judge_py_at_run_commit_available']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
