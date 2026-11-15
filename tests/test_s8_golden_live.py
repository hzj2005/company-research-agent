"""S8.4 正式 golden 的诚信护栏（用户二次复核后的最终版）。

用户重新看了 25 条，把其中 11 条改成最终标准答案（14 采纳原样 / 11 按建议修正）。
测试锁死的是：
1. 正式 golden 用的确实是**用户的最终措辞与最终 URL**，旧草稿只留作对照；
2. 6 条打不开的原始 URL 全部被换掉，但换了 URL 不等于引用层已核验；
3. 用户确认不能外溢成「引用层可用」「全量样本已覆盖」或「可换路径复用 S7」。
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from config.loader import ROOT
from evals.build_golden_live import DRAFT, FILLED, OUTPUT, REVIEW, main
from evals.config import dataset_path, load_eval_config
from evals.metrics import load_golden

DOC = ROOT / "docs" / "GOLDEN_LIVE.md"


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module", autouse=True)
def _generated() -> None:
    main()


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return _rows(OUTPUT)


@pytest.fixture(scope="module")
def claims(rows: list[dict]) -> dict[str, dict]:
    return {r["id"]: r for r in rows if r["kind"] == "claim"}


@pytest.fixture(scope="module")
def meta(rows: list[dict]) -> dict:
    return next(r for r in rows if r["kind"] == "meta")


def test_shape_and_full_id_coverage(rows: list[dict]) -> None:
    kinds = Counter(r["kind"] for r in rows)
    assert kinds == {"meta": 1, "case": 5, "claim": 25}
    filled_ids = {r["id"] for r in _rows(FILLED) if r["kind"] == "claim"}
    claim_ids = [r["id"] for r in rows if r["kind"] == "claim"]
    assert len(claim_ids) == len(set(claim_ids)) == 25
    assert set(claim_ids) == filled_ids


def test_final_wording_and_url_come_from_the_user(claims: dict[str, dict]) -> None:
    """不能拿旧草稿悄悄覆盖用户的最终答案。"""
    filled = {r["id"]: r for r in _rows(FILLED) if r["kind"] == "claim"}
    draft = {r["id"]: r for r in _rows(DRAFT) if r["kind"] == "claim"}
    for cid, r in claims.items():
        assert r["expected_text"] == filled[cid]["final_fact"], cid
        assert r["source_url"] == filled[cid]["final_source_url"], cid
        assert r["original_fact"] == draft[cid]["candidate_fact"], cid
        assert r["original_source_url"] == draft[cid]["source_url"], cid
        assert r["human_verdict"] == filled[cid]["user_verdict"]
        assert r["human_decision"] == filled[cid]["user_decision"]
        assert r["human_note"] == filled[cid].get("user_note", "")
    assert all(r["human_note"] for r in claims.values()), "逐条备注须原样带进正式 golden"


def test_user_decisions_are_counted_from_the_source_not_hardcoded(
    meta: dict, claims: dict[str, dict]
) -> None:
    assert meta["provenance"] == "human-verified"
    assert meta["verified_by"] == "user"
    assert meta["fact_layer_verified_by_user"] is True
    assert meta["user_decisions"] == dict(Counter(r["human_decision"] for r in claims.values()))
    assert meta["claims_revised_by_user"] == sum(1 for r in claims.values() if r["source_revised"])
    assert set(meta["revised_claim_ids"]) == {
        cid for cid, r in claims.items() if r["source_revised"]
    }
    assert "notes_source" in meta, "备注来自页面预填说明，必须标明出处"


def test_all_unreachable_original_urls_were_replaced(claims: dict[str, dict], meta: dict) -> None:
    review = {r["id"]: r for r in _rows(REVIEW) if r["kind"] == "claim"}
    unreachable = {cid for cid, r in review.items() if not r["source_accessible"]}
    assert len(unreachable) == 6
    assert set(meta["original_unreachable_claim_ids"]) == unreachable
    assert meta["original_unreachable_source_urls"] == 6
    for cid in unreachable:
        r = claims[cid]
        assert r["source_url"] != r["original_source_url"], cid
        assert r["source_url"].startswith("https://"), cid
        assert r["source_revised"] is True, cid


def test_no_ai_flagged_claim_was_left_as_is(meta: dict, claims: dict[str, dict]) -> None:
    review = {r["id"]: r for r in _rows(REVIEW) if r["kind"] == "claim"}
    flagged = {cid for cid, r in review.items() if r["ai_check"] != "verified"}
    assert len(flagged) == 10
    assert meta["claims_flagged_by_ai_source_check"] == 10
    assert meta["claims_flagged_but_left_as_is"] == 0
    assert all(claims[cid]["human_decision"] != "accept" for cid in flagged)


def test_replaced_urls_do_not_fake_page_content(claims: dict[str, dict], meta: dict) -> None:
    """换了 URL 就没抓过新页面（0 调用），不能把旧引文冒充新页面内容。"""
    assert meta["final_url_content_fetched_in_project"] is False
    replaced = [r for r in claims.values() if r["source_url"] != r["original_source_url"]]
    assert replaced
    for r in replaced:
        assert r["source_content"] is None, r["id"]
        assert r["source_content_for_final_url_verified"] is False, r["id"]
        assert r["evidence_quote_from_ai_check"], r["id"]
        assert "不保证对应最终 URL" in r["evidence_quote_note"], r["id"]
    assert meta["final_url_sources"]["original"] + sum(
        v for k, v in meta["final_url_sources"].items() if k != "original"
    ) == 25


def test_citation_layer_is_explicitly_unusable(meta: dict) -> None:
    assert meta["citation_layer_verified"] is False
    assert meta["citation_layer_usable_as_metric"] is False
    assert meta["metric_scope"] == "fact_layer_only"
    assert "没有重新抓取" in meta["citation_layer_status"]
    assert "citation_traceability" in meta["usage_restriction"]
    assert meta["tavily_credits_used"] == 0 and meta["llm_calls_used"] == 0


def test_only_notion_has_a_real_report(claims: dict[str, dict], meta: dict) -> None:
    scorable = [r for r in claims.values() if r["has_real_report_to_score"]]
    assert len(scorable) == 5
    assert {r["case"] for r in scorable} == {"notion"}
    assert "只有 Notion" in meta["coverage_note"] and "20 条" in meta["coverage_note"]
    assert all(r["report_section"] for r in claims.values())


def test_s7_pipeline_cannot_be_reused_by_swapping_dataset_path(rows: list[dict]) -> None:
    """实测三处不兼容：无 abstain、provenance 写死、fixture case 名对不上。"""
    golden = load_golden(OUTPUT)
    assert len(golden.abstains) == 0
    cfg = load_eval_config()
    assert cfg.dataset.provenance == "synthetic-fixture-derived"
    assert not set(cfg.fixture.cases) & {r["case"] for r in rows if r["kind"] == "case"}
    assert dataset_path(cfg).name == "golden.jsonl", "S7 仍必须只跑 fixture golden"


def test_generation_does_not_mutate_any_input() -> None:
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (FILLED, REVIEW, DRAFT)}
    main()
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (FILLED, REVIEW, DRAFT)}
    assert before == after


def test_annotation_doc_records_the_three_blockers() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "L205-206" in text and "abstains = 0" in text
    assert "synthetic-fixture-derived" in text
    assert "fixture.cases" in text
    assert "事实层" in text and "引用层" in text and "覆盖层" in text
    assert "11 条" in text and "14 条" in text
