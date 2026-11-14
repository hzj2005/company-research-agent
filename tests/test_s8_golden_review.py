"""S8.3 辅助复核护栏：把「AI 核对」与「人工核验」严格分开。

这些测试锁死的不是事实本身（那需要用户逐条判断），而是：
1. 复核表覆盖 25 条草稿、不多不少；
2. 在任何 user_verdict 被填完之前，文件始终标着「不是人工核验、不得当指标」；
3. 评测台不会误读到草稿 / 复核表；
4. 汇总数字由脚本核对，防止手写计数与真实数据不一致。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from config.loader import ROOT
from evals.config import dataset_path, load_eval_config

REVIEW = ROOT / "evals" / "golden_live_review.jsonl"
DRAFT = ROOT / "evals" / "golden_live_draft.jsonl"


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def review() -> list[dict]:
    return _rows(REVIEW)


@pytest.fixture(scope="module")
def claims(review: list[dict]) -> list[dict]:
    return [r for r in review if r["kind"] == "claim"]


def test_review_covers_exactly_the_25_draft_claims(review: list[dict], claims: list[dict]) -> None:
    draft_ids = {r["id"] for r in _rows(DRAFT) if r["kind"] == "claim"}
    assert len(claims) == 25
    assert {r["id"] for r in claims} == draft_ids
    assert len({r["id"] for r in claims}) == len(claims)


def test_meta_and_summary_declare_ai_assisted_only(review: list[dict]) -> None:
    meta = next(r for r in review if r["kind"] == "meta")
    summary = next(r for r in review if r["kind"] == "summary")
    assert meta["is_human_verification"] is False
    assert meta["human_verified_claims"] == 0
    assert meta["must_not_be_used_as_metric"] is True
    assert meta["tavily_credits_used"] == 0
    assert summary["ai_assisted_only"] is True
    assert summary["human_verified_claims"] == 0
    assert summary["user_verdict_filled"] == 0


def test_no_verdict_is_pre_filled(claims: list[dict]) -> None:
    """AI 不得代替用户宣布复核通过。"""
    assert all(r["user_verdict"] is None for r in claims)


def test_summary_counts_match_actual_data(review: list[dict], claims: list[dict]) -> None:
    """上一版手写 16/7/2 与真实 15/8/2 不符；用脚本锁死。"""
    summary = next(r for r in review if r["kind"] == "summary")
    assert summary["by_ai_check"] == dict(Counter(r["ai_check"] for r in claims))
    assert summary["total_candidates"] == len(claims)
    assert summary["original_urls_checked"] == len({r["original_source_url"] for r in claims})
    assert summary["original_urls_unavailable"] == len(
        {r["original_source_url"] for r in claims if not r["source_accessible"]}
    )
    assert summary["user_verdict_filled"] == sum(1 for r in claims if r["user_verdict"] is not None)


def test_every_claim_has_evidence_and_valid_check(claims: list[dict]) -> None:
    assert all(r["ai_check"] in {"verified", "needs_fix", "reject"} for r in claims)
    assert all(r["evidence_quote"].strip() for r in claims)
    assert all(r["note"].strip() for r in claims)
    assert all(r["suggested_action"].strip() for r in claims)


def test_suggested_urls_are_https(claims: list[dict]) -> None:
    assert all(
        r["suggested_source_url"] is None or r["suggested_source_url"].startswith("https://")
        for r in claims
    )


def test_unavailable_sources_always_offer_a_replacement(claims: list[dict]) -> None:
    """链接打不开的条目不能只标问题、不给可核验的替代出处。"""
    for r in claims:
        if not r["source_accessible"]:
            assert r["suggested_source_url"], r["id"]
            assert r["ai_check"] in {"needs_fix", "reject"}, r["id"]


def test_eval_pipeline_never_reads_live_draft_or_review() -> None:
    """正式 golden 生成前，评测台只能指向 S7 的 fixture golden。"""
    active = dataset_path(load_eval_config())
    assert active.name == "golden.jsonl"
    assert active != DRAFT.resolve()
    assert active != REVIEW.resolve()
    assert DRAFT.exists() and REVIEW.exists()
