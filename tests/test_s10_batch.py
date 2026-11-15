"""S10-B 护栏：批量真实调研与批量批改的记账、隔离与红线。

这里**不发起任何真实请求**：只测纯逻辑与产物结构。
真实调用的结果落在 `evals/live_batch.json`，由文档引用，不在这里断言。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals import batch_live as bl
from evals import judge_batch as jb
from evals.judge import GOLDEN, build_payload, quote_in_report

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------- 额度记账

def test_credits_ledger_counts_failed_runs_too() -> None:
    """v1 里 Stripe 那 4 次检索发出去了但没拿到报告 —— 失败也要记账。"""
    total = bl.credits_already_spent()
    v1 = ROOT / "evals" / "live_batch_v1.json"
    run = ROOT / "evals" / "live_run.json"
    expected = 0
    if run.exists():
        expected += json.loads(run.read_text(encoding="utf-8"))["credits"]["cumulative"]
    if v1.exists():
        expected += json.loads(v1.read_text(encoding="utf-8"))["credits"]["spent_this_run"]
    assert total == expected
    assert total >= 8, "S8.2 + S8.3 的 8 credits 必须始终在账上"


def test_dynamic_budget_never_exceeds_the_user_ceiling() -> None:
    already = bl.credits_already_spent()
    max_calls = min(
        bl.GLOBAL_MAX_CALLS,
        max(0, (bl.USER_CREDIT_CEILING - already) // bl.CREDITS_PER_SEARCH),
    )
    assert already + max_calls * bl.CREDITS_PER_SEARCH <= bl.USER_CREDIT_CEILING


def test_default_companies_start_with_notion_to_reuse_cache() -> None:
    """Notion 的 4 条 query 命中 S8.3 的缓存，0 credits —— 这是「同题对比」的基础。"""
    assert bl.DEFAULT_COMPANIES[0] == "Notion"


# --------------------------------------------------------- 消歧留痕的提取

def test_guard_notes_only_picks_entity_guard() -> None:
    state = {
        "review_notes": [
            {"node": "curate", "kept": 3},
            {"node": "entity_guard", "section": "company", "rejected": [{"url": "u"}]},
            {"node": "briefing", "referenced": 2},
            "not a dict",
        ]
    }
    notes = bl._guard_notes(state)
    assert len(notes) == 1
    assert notes[0]["section"] == "company"


# ------------------------------------------------------------- 批量批改

def test_claims_are_grouped_by_company() -> None:
    grouped = jb.load_claims_by_company()
    assert set(grouped) == {"Notion", "Figma", "Stripe", "Airbnb", "Canva"}
    assert all(len(v) == 5 for v in grouped.values())
    # 全部条目都经过人工核验，没有「待定」混进来
    for claims in grouped.values():
        for claim in claims:
            assert claim["human_verdict"] is True


def test_payload_never_leaks_the_source_columns() -> None:
    """复用 S8.4 的 prompt 构造：只送 claim_id + expected_text。"""
    claims = jb.load_claims_by_company()["Figma"]
    payload = build_payload(claims, "Figma was founded in 2012. [1]", "Figma")
    for marker in ("source_url", "source_content", "ai_note", "human_note", "original_fact"):
        assert f'"{marker}"' not in payload
    assert "expected_text" in payload


def test_quote_check_rejects_reference_titles() -> None:
    """证据句只认正文 —— References 里的标题不能冒充事实陈述。"""
    report = "Figma was founded in 2012. [1]\n\n## References\n\n[1] Figma — https://x"
    assert quote_in_report("Figma was founded in 2012.", report) is True
    assert quote_in_report("[1] Figma — https://x", report) is False


def test_batch_and_judge_outputs_are_separate_files() -> None:
    """新脚本不许覆盖 S8.3 / S8.4 的产物，否则历史结论就对不上了。"""
    assert bl.OUTPUT.name == "live_batch.json"
    assert jb.OUTPUT.name == "live_score_batch.json"
    assert bl.OUTPUT != ROOT / "evals" / "live_run.json"
    assert jb.OUTPUT != ROOT / "evals" / "live_score.json"


@pytest.mark.skipif(
    not (ROOT / "evals" / "live_batch.json").exists(),
    reason="还没跑过批处理",
)
def test_batch_artifact_keeps_the_quota_book() -> None:
    data = json.loads((ROOT / "evals" / "live_batch.json").read_text(encoding="utf-8"))
    assert data["credits"]["cumulative"] <= data["credits"]["user_ceiling"]
    assert data["budget"]["calls_made"] <= data["budget"]["global_max_calls"]
    # 报告正文里不能出现凭据
    for run in data["runs"]:
        assert "tvly-" not in run["report"]
        assert "sk-" not in run["report"]
    assert data["credentials"]["keys_in_artifact"] is False
