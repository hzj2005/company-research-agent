"""S8.4 前置：本地人工复核页面的诚信护栏。

页面是给用户点选用的工具，不是判分器。测试锁死：
1. 数据来自两份草稿、覆盖 25 条，且页面本身不预填任何结论；
2. 页面完全离网（无外链脚本/样式、无密钥、无 fetch）；
3. 导出的 jsonl 如实标成「用户确认记录」，且不冒充正式 golden 或指标；
4. 生成页面是只读的：不改动两份源 jsonl。
"""

from __future__ import annotations

import hashlib
import json
import re

import pytest

from config.loader import ROOT
from evals.build_review_page import DRAFT, OUTPUT, REVIEW, HTML, build_rows, main

SEED_RE = re.compile(r'<script type="application/json" id="seed">(.*?)</script>', re.S)


@pytest.fixture(scope="module")
def page() -> str:
    main()
    return OUTPUT.read_text(encoding="utf-8")


def _seed(page: str) -> list[dict]:
    match = SEED_RE.search(page)
    assert match, "page must inline its data as JSON"
    return json.loads(match.group(1))


def test_rows_cover_all_25_draft_claims() -> None:
    rows = build_rows()
    draft_ids = [
        json.loads(line)["id"]
        for line in DRAFT.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("kind") == "claim"
    ]
    assert len(rows) == 25
    assert [r["id"] for r in rows] == draft_ids
    assert {r["ai_check"] for r in rows} == {"verified", "needs_fix", "reject"}
    assert all(r["candidate_fact"] and r["source_url"] and r["evidence_quote"] for r in rows)


def test_page_never_pre_fills_a_verdict(page: str) -> None:
    """AI 既出题又批卷是最容易「面试一眼假」的地方。"""
    rows = _seed(page)
    assert len(rows) == 25
    assert all("user_verdict" not in r and "user_decision" not in r for r in rows)
    assert 'var state = {};' in HTML
    assert "localStorage.getItem(KEY)" in HTML
    assert "btn.disabled = n !== rows.length" in HTML, "must not export before all 25 are decided"


def test_page_is_fully_offline_and_key_free(page: str) -> None:
    assert "__SEED_JSON__" not in page
    assert not re.search(r"<script[^>]+src=", page)
    assert not re.search(r"<link[^>]+href=", page)
    assert not re.search(r"https?://[^\"'\s]+\.(js|css)", page)
    assert "fetch(" not in page
    assert "XMLHttpRequest" not in page
    assert not re.search(r"tvly-|sk-[A-Za-z0-9]", page)
    assert "0 Tavily" in page  # 页面上如实告知额度


def test_export_declares_human_record_not_a_metric(page: str) -> None:
    assert 'review_type: "human_confirmed_by_user"' in page
    assert "is_human_verification: true" in page
    assert "must_not_be_used_as_metric: true" in page
    assert "ai_check_is_not_human_verdict: true" in page
    assert 'a.download = "golden_live_review_filled.jsonl"' in page
    assert "golden_live.jsonl" not in _seed_marker(page)


def test_page_warns_about_accepting_ai_flagged_claims(page: str) -> None:
    """25 条全点「采纳原样」是最容易把已知错误写成标准答案的情况。"""
    assert 'id="warn"' in page
    assert 'id="filterRisky"' in page
    assert "conflicts.length" in page
    assert "测出来的准确率没有意义" in page
    assert 'r.ai_check !== "verified"' in page
    # 导出时如实记录冲突数，不靠用户自己发现
    assert "accepted_but_conflicts_with_ai_check: conflicts" in page
    assert "accepted_as_is_claims: asIs" in page
    assert "accepted_with_fix_claims: withFix" in page


def _seed_marker(page: str) -> str:
    """The seed JSON must not contain a ready-made golden filename."""
    return SEED_RE.search(page).group(1)


def test_generation_does_not_mutate_source_files() -> None:
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (DRAFT, REVIEW)
    }
    main()
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (DRAFT, REVIEW)}
    assert before == after


def test_output_lives_inside_evals() -> None:
    assert OUTPUT.parent == ROOT / "evals"
    assert OUTPUT.name == "golden_review.html"
