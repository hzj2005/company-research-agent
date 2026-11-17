"""S7 评测台验收：图跑出来的分数必须能被反向证伪，不能是恒满分。

重点不是「baseline 拿了 1.0」，而是：
- golden 与 fixture/settings 同步、且明确标注合成来源；
- 注入一条幻觉 / 伪造一次拒答，指标必须掉下来（否则指标是摆设）；
- 关掉自纠正能定位到具体退化用例 id；
- 在 fixture 下无效的 A/B 如实标 no_effect，不伪造对照收益；
- 回归比对按容差判定、CI 可复现、0 次真实外部调用、live 模式一律拒绝启动。
"""

from __future__ import annotations

import asyncio
import json
import re
import socket
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from config.loader import ROOT, apply_overrides, get_settings
from evals.build_golden import _serialize, build_items
from evals.config import dataset_path, load_eval_config
from evals.metrics import (
    MISMATCH,
    NO_EXPLICIT_CITATION,
    NO_URL,
    UNKNOWN_URL,
    aggregate_metrics,
    compare_scorecards,
    evaluate_case,
    is_supported,
    load_golden,
    parse_report,
)
from evals.run_eval import build_scorecard, eval_offline_guard
from graph.run import run_research


@pytest.fixture(scope="module")
def cfg():
    return load_eval_config()


@pytest.fixture(scope="module")
def golden(cfg):
    return load_golden(dataset_path(cfg))


@pytest.fixture(scope="module")
def full_card(cfg, golden):
    card, attempts = build_scorecard(cfg, get_settings(), golden)
    return card, attempts


def _case(golden, key: str) -> dict[str, Any]:
    return next(c for c in golden.cases if c["case"] == key)


def _strip_nondeterministic(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _strip_nondeterministic(v)
            for k, v in value.items()
            if k not in ("elapsed_ms", "p95_latency_ms")
        }
    if isinstance(value, list):
        return [_strip_nondeterministic(v) for v in value]
    return value


# ---------------------------------------------------------------- golden ---

def test_golden_is_in_sync_with_fixture_and_settings(cfg) -> None:
    expected = _serialize(build_items())
    actual = dataset_path(cfg).read_text(encoding="utf-8")
    assert actual == expected, "golden 与 fixture/settings 不同步，请重跑 build_golden.py"


def test_golden_provenance_counts_and_honest_note(golden) -> None:
    assert golden.meta["provenance"] == "synthetic-fixture-derived"
    assert golden.meta["schema_version"] == 1
    assert "不是真实世界事实" in golden.meta["note"]
    assert len(golden.cases) == 3
    # claim 数由 fixture 文档数派生，不写死：扩数据后应随之增长
    assert len(golden.claims) >= 3
    assert len(golden.abstains) == 1
    assert all(i["expected_text"] == i["source_content"] for i in golden.claims)


def test_golden_derivation_follows_retry_rules(golden) -> None:
    sufficient, sparse, empty = (_case(golden, k) for k in ("sufficient", "sparse", "empty"))
    assert (sufficient["expected_research_runs"], sufficient["first_round_insufficient"]) == (1, False)
    assert (sparse["expected_research_runs"], sparse["first_round_insufficient"]) == (2, True)
    assert sparse["expect_self_correction"] is True
    assert empty["expected_research_runs"] == 3
    assert empty["expected_degraded_sections"] == ["company"]
    assert empty["expect_self_correction"] is False


# ------------------------------------------------------------ parse/judge ---

def test_parse_report_maps_inline_marker_to_reference_url(golden) -> None:
    report = (
        "# Acme 研究报告\n\n"
        "## 公司概况\n\n"
        "- Acme 成立于 2001 年。 [1]\n\n"
        "## References\n\n"
        "[1] 关于我们 — https://example.org/acme/about\n"
    )
    parsed = parse_report(report, get_settings(), text_index=golden.text_index, case="sufficient")
    assert len(parsed.claims) == 1
    claim = parsed.claims[0]
    assert claim.section == "company"
    assert claim.marker == 1
    assert claim.url == "https://example.org/acme/about"
    assert claim.is_abstain is False


def test_is_supported_matrix() -> None:
    corpus = {"https://example.org/a": ["Acme 成立于 2001 年，总部在上海。"]}
    ok, reason = is_supported("Acme 成立于 2001 年", "https://example.org/a/", corpus)
    assert (ok, reason) == (True, "ok")
    assert is_supported("Acme 已完成 IPO", "https://example.org/a", corpus) == (False, MISMATCH)
    assert is_supported("任意结论", None, corpus) == (False, NO_URL)
    assert is_supported("任意结论", "https://unknown.example", corpus) == (False, UNKNOWN_URL)


def test_injected_hallucination_is_detected(golden, tmp_path: Path) -> None:
    """反向验证：把一条有据结论改成凭空编造，指标必须掉，不能恒为 1.0。"""
    state, trace = asyncio.run(
        run_research("Notion", get_settings(), tmp_path / "s7.db", collect_trace=True)
    )
    match = re.search(r"^- (Notion 提供笔记[^\n]*?)\s+\[(\d+)\]$", state["report"], re.M)
    assert match, "fixture 基线报告里应能定位到 Notion 的公司段落"
    mutated = (
        state["report"][: match.start()]
        + f"- Notion 已于 2026 年完成 IPO，市值 1 万亿。 [{match.group(2)}]"
        + state["report"][match.end() :]
    )
    result = evaluate_case(
        case_item=_case(golden, "sufficient"),
        state={**state, "report": mutated},
        trace=trace,
        elapsed_ms=1.0,
        golden=golden,
        settings=get_settings(),
    )
    assert result["matched_claims"] == result["expected_claims"] - 1
    assert any(r["reason"] == MISMATCH for r in result["claim_records"])
    metrics, counts = aggregate_metrics([result], load_eval_config())
    assert metrics["fact_accuracy"] < 1.0
    assert metrics["citation_traceability"] < 1.0
    assert metrics["hallucination_rate"] > 0.0
    assert counts["unsupported_reasons"][MISMATCH] == 1


def test_fake_abstain_is_rejected(golden, cfg, tmp_path: Path) -> None:
    """本应拒答的栏目却硬塞一条无来源结论 → abstain item 必须判失败。"""
    state, trace = asyncio.run(
        run_research("Zephyrstone Labs", get_settings(), tmp_path / "s7.db", collect_trace=True)
    )
    degrade = get_settings().graph.degrade.message
    assert f"- {degrade}" in state["report"]
    mutated = state["report"].replace(
        f"- {degrade}", "- Zephyrstone Labs 2025 年营收 10 亿。", 1
    )
    result = evaluate_case(
        case_item=_case(golden, "empty"),
        state={**state, "report": mutated},
        trace=trace,
        elapsed_ms=1.0,
        golden=golden,
        settings=get_settings(),
    )
    assert "empty:company:abstain" in result["failures"]
    metrics, _ = aggregate_metrics([result], cfg)
    assert metrics["abstain_rate"] == 0.0


# ------------------------------------------------------------- scorecard ---

def test_baseline_gate_and_zero_external_calls(full_card, cfg) -> None:
    card, attempts = full_card
    base = card["runs"]["baseline"]
    assert card["provenance"] == "synthetic-fixture-derived"
    assert card["mode"] == "fixture"
    assert "不是真实世界准确率" in card["disclaimer"]
    assert base["gate"]["passed"] is True
    assert base["metrics"]["fact_accuracy"] == 1.0
    assert base["metrics"]["citation_traceability"] == 1.0
    assert base["metrics"]["abstain_rate"] == 1.0
    assert base["metrics"]["hallucination_rate"] == 0.0
    assert base["metrics"]["self_correction_success"] == 1.0
    # 两个计数必须与 dataset 派生出的 claim 数自洽，不写死具体数值
    n_claims = card["dataset"]["claim_items"]
    assert n_claims >= 3
    assert base["counts"]["expected_claims"] == n_claims
    assert base["counts"]["report_claims"] == n_claims
    assert card["external_calls"] == {"tavily": 0, "llm": 0, "blocked_connection_attempts": 0}
    assert attempts == []
    assert "generated_at" not in card and "timestamp" not in card
    assert card["config"]["protected_metrics"] == list(cfg.ci.protected_metrics)


def test_self_correction_off_regresses_and_names_case_ids(full_card) -> None:
    card, _ = full_card
    effect = card["ab_effects"]["self_correction_off"]
    assert effect["status"] == "changed"
    assert effect["delta_vs_baseline"]["fact_accuracy"] < 0
    assert effect["delta_vs_baseline"]["self_correction_success"] == -1.0
    failed = card["summary"]["failed_case_ids"]
    assert "self_correction_off:sparse:company:0" in failed
    assert len([i for i in failed if i.startswith("self_correction_off:sparse:company:")]) == 3


def test_fixture_inert_ab_tests_are_marked_no_effect(full_card) -> None:
    """三个 override 在 fixture 下不改变可观测行为，如实标注而不是编造对照收益。"""
    card, _ = full_card
    for name in ("fewer_results", "free_text_output", "no_human_review"):
        assert card["ab_effects"][name]["status"] == "no_effect", name
    assert all(
        v in (0, 0.0, None)
        for v in card["ab_effects"]["fewer_results"]["delta_vs_baseline"].values()
    )


def test_regression_comparison_detects_drop_and_lists_case_ids(full_card, cfg) -> None:
    card, _ = full_card
    prev = deepcopy(card)
    cur = deepcopy(card)
    cur["runs"]["baseline"]["metrics"]["citation_traceability"] = 0.80
    cur["runs"]["baseline"]["cases"][0]["failures"].append("sufficient:company:999")
    result = compare_scorecards(prev, cur, cfg)
    assert result["passed"] is False
    assert any("citation_traceability" in v for v in result["violations"])
    assert result["degraded_case_ids"] == ["baseline:sufficient:company:999"]


def test_regression_tolerance_absorbs_small_noise(full_card, cfg) -> None:
    card, _ = full_card
    prev = deepcopy(card)
    cur = deepcopy(card)
    cur["runs"]["baseline"]["metrics"]["fact_accuracy"] -= 0.005
    result = compare_scorecards(prev, cur, cfg)
    assert result["passed"] is True
    assert result["tolerance"] == cfg.ci.regression_tolerance


def test_scorecard_is_reproducible_except_declared_nondeterministic(cfg, golden) -> None:
    first, _ = build_scorecard(cfg, get_settings(), golden, ab_names=[])
    second, _ = build_scorecard(cfg, get_settings(), golden, ab_names=[])
    assert first["inputs_sha256"] == second["inputs_sha256"]
    assert _strip_nondeterministic(first["runs"]) == _strip_nondeterministic(second["runs"])
    assert _strip_nondeterministic(first["dataset"]) == _strip_nondeterministic(second["dataset"])


def test_live_mode_is_refused_to_protect_api_quota(cfg, golden) -> None:
    live = apply_overrides(get_settings(), {"app.mode": "live"})
    with pytest.raises(RuntimeError, match="APP_MODE=fixture"):
        build_scorecard(cfg, live, golden, ab_names=[])


def test_unknown_ab_name_fails_loudly(cfg, golden) -> None:
    with pytest.raises(ValueError, match="未知的 A/B 组名"):
        build_scorecard(cfg, get_settings(), golden, ab_names=["typo_group"])


def test_offline_guard_blocks_non_loopback_connections() -> None:
    original = socket.socket.connect
    with eval_offline_guard() as attempts:
        s = socket.socket()
        try:
            with pytest.raises(AssertionError, match="禁止外部连接"):
                s.connect(("93.184.216.34", 80))
        finally:
            s.close()
    assert len(attempts) == 1
    assert socket.socket.connect is original, "守卫必须被还原"


def test_one_command_produces_scorecard(tmp_path: Path, cfg, golden) -> None:
    """M3 验收：一条命令出分，写出的文件可定位退化用例。"""
    out = tmp_path / "scorecard.json"
    proc = subprocess.run(
        [sys.executable, "-m", "evals.run_eval", "--baseline-only", "--output", str(out)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    card = json.loads(out.read_text(encoding="utf-8"))
    assert card["runs"]["baseline"]["gate"]["passed"] is True
    assert "failed case ids" in proc.stdout
    assert card["dataset"]["claim_items"] == len(golden.claims)
    assert out.exists()


# ------------------------------------------- S7 复查补账（P1–P8）反向验证 ---

def test_no_inline_citations_cannot_pass_traceability(golden, cfg, tmp_path: Path) -> None:
    """P1：报告一条 [n] 都没有时，不能靠 golden 反推 URL 拿到引用满分。"""
    settings = apply_overrides(get_settings(), {"features.inline_citations": False})
    state, trace = asyncio.run(
        run_research("Notion", settings, tmp_path / "nocite.db", collect_trace=True)
    )
    parsed = parse_report(
        state["report"], settings, text_index=golden.text_index, case="sufficient"
    )
    assert parsed.claims and all(c.marker is None for c in parsed.claims)
    result = evaluate_case(
        case_item=_case(golden, "sufficient"),
        state=state, trace=trace, elapsed_ms=1.0, golden=golden, settings=settings,
    )
    metrics, counts = aggregate_metrics([result], cfg)
    assert metrics["fact_accuracy"] == 1.0, "内容仍应命中；引用缺失由 traceability 独立反映"
    assert metrics["citation_traceability"] == 0.0
    assert metrics["hallucination_rate"] == 1.0
    assert counts["claims_without_explicit_citation"] == len(result["claim_records"])
    assert all(r["reason"] == NO_EXPLICIT_CITATION for r in result["claim_records"])
    assert all(r["url_inferred"] for r in result["claim_records"])


def test_simulation_runs_to_retry_budget_when_fixture_rounds_run_out() -> None:
    """P3：fixture 轮数不足时，golden 模拟也要跑到额度用尽，与图一致。"""
    from evals.build_golden import _simulate_case

    settings = get_settings()
    short = {
        "company": "X",
        "rounds": [{"company": [{"url": "https://x/1", "score": 0.9, "content": "c"}]}],
    }
    sim = _simulate_case(short, settings)
    assert sim["expected_research_runs"] == settings.graph.max_retry + 1 == 3
    assert "company" in sim["degraded"]


def test_regression_detects_ab_group_degradation(full_card, cfg) -> None:
    """P4：A/B 组新出现的失败用例也必须被回归门禁点名。"""
    card, _ = full_card
    prev, cur = deepcopy(card), deepcopy(card)
    cur["runs"]["fewer_results"]["cases"][0]["failures"].append("sufficient:company:999")
    result = compare_scorecards(prev, cur, cfg)
    assert result["passed"] is False
    assert "fewer_results:sufficient:company:999" in result["degraded_case_ids"]
    assert "self_correction_off" in result["compared_groups"]


def test_scorecard_has_separate_input_and_code_fingerprints(full_card) -> None:
    """P2：数据指纹与代码指纹分开，才谈得上区分「输入变了」和「代码变了」。"""
    card, _ = full_card
    assert len(card["inputs_sha256"]) == 16
    assert len(card["code_sha256"]) == 16
    assert card["inputs_sha256"] != card["code_sha256"]


def test_custom_eval_config_is_included_in_inputs_fingerprint(cfg) -> None:
    """P6：--config 指向别的配置时，指纹必须跟着变。"""
    from evals.run_eval import inputs_sha256

    default = inputs_sha256(cfg, get_settings())
    custom = inputs_sha256(cfg, get_settings(), eval_config_path=ROOT / "config" / "settings.yaml")
    assert custom != default


def test_small_or_empty_golden_is_rejected(cfg, golden) -> None:
    """P5：样本不足 / 缺拒答样本时拒绝出分，不能拿空集刷满分。"""
    from dataclasses import replace

    with pytest.raises(ValueError, match="min_companies"):
        build_scorecard(cfg, get_settings(), replace(golden, cases=golden.cases[:1]), ab_names=[])
    with pytest.raises(ValueError, match="claim 与 abstain"):
        build_scorecard(cfg, get_settings(), replace(golden, abstains=[]), ab_names=[])


def test_baseline_only_conflicts_with_ab() -> None:
    """P7：两个互斥参数同时给必须报错，不能静默忽略。"""
    from evals.run_eval import main

    with pytest.raises(SystemExit) as exc:
        main(["--baseline-only", "--ab", "fewer_results"])
    assert exc.value.code == 2
