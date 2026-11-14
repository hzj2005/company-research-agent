"""真实 golden 草稿的护栏：复核前绝不许被当成指标来源。

用户 2026-11-14 拍板「我查 5 家×5 条，你复核」。这份文件是**候选清单**，
不是标准答案。本测试防止两类事故：统计数字手写漂移、以及有人把
未复核的草稿路径接进 evals/run_eval.py 直接出「准确率」。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from config.loader import ROOT
from evals.config import dataset_path, load_eval_config

DRAFT = ROOT / "evals" / "golden_live_draft.jsonl"


@pytest.fixture(scope="module")
def rows() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in DRAFT.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.fixture(scope="module")
def claims(rows) -> list[dict[str, Any]]:
    return [r for r in rows if r["kind"] == "claim"]


def test_draft_is_marked_as_unverified_and_not_a_metric_source(rows) -> None:
    meta = next(r for r in rows if r["kind"] == "meta")
    assert meta["status"] == "draft_pending_human_review"
    assert meta["must_not_be_used_as_metric"] is True
    assert meta["human_verified_claims"] == 0
    assert "语义 judge" in meta["matching_note"], "必须写明 S7 逐字匹配口径不适用"
    assert "不保证逐字" in meta["excerpt_fidelity"], "摘录不得被当成已核验引文"


def test_eval_pipeline_does_not_consume_the_unreviewed_draft() -> None:
    """评测台当前数据集必须仍是 S7 的 synthetic golden，不能指向草稿。"""
    path = dataset_path(load_eval_config())
    assert path.name == "golden.jsonl"
    assert path != DRAFT.resolve()
    assert "draft" not in path.name


def test_25_candidates_across_5_companies(rows, claims) -> None:
    assert Counter(r["kind"] for r in rows) == {
        "meta": 1,
        "case": 5,
        "claim": 25,
        "review_summary": 1,
    }
    assert Counter(c["case"] for c in claims) == {
        "notion": 5,
        "figma": 5,
        "stripe": 5,
        "airbnb": 5,
        "canva": 5,
    }
    assert len({c["id"] for c in claims}) == 25
    assert all(c["id"].startswith(f"{c['case']}:") for c in claims)


def test_every_claim_is_pending_and_traceable(claims) -> None:
    for c in claims:
        assert c["review_status"] == "pending", c["id"]
        assert c["reviewer_verdict"] is None, c["id"]
        assert c["source_url"].startswith("https://"), c["id"]
        assert c["source_title"] and c["source_excerpt"] and c["check_hint"], c["id"]
        assert c["source_kind"] in {
            "official",
            "official_press_release",
            "authoritative_media",
            "aggregator",
        }, c["id"]
        assert c["candidate_fact"], c["id"]


def test_conflicted_claims_stay_pending(claims) -> None:
    flagged = [c for c in claims if c.get("conflict_note")]
    assert len(flagged) == 8
    assert all(c["review_status"] == "pending" for c in flagged)


def test_review_summary_matches_actual_data(rows, claims) -> None:
    summary = next(r for r in rows if r["kind"] == "review_summary")
    assert summary["candidate_claims"] == len(claims) == 25
    assert summary["source_kind_counts"] == dict(
        Counter(c["source_kind"] for c in claims)
    )
    assert summary["section_counts"] == dict(Counter(c["section"] for c in claims))
    assert summary["claims_with_conflict_notes"] == sum(
        1 for c in claims if c.get("conflict_note")
    )
    kinds = summary["source_kind_counts"]
    assert (
        kinds["official"] + kinds["official_press_release"]
        == summary["official_or_press_release_claims"]
    )
    assert summary["status"] == "pending_human_review"
    assert "blocking_note" in summary


def test_draft_cost_zero_tavily_credits(rows) -> None:
    meta = next(r for r in rows if r["kind"] == "meta")
    assert meta["tavily_credits_used_for_this_file"] == 0
    assert Path(DRAFT).exists()
