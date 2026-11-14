"""S8.3 词法质量检查的离线自测（0 次外部调用）。"""

from __future__ import annotations

import json

import pytest

from config.loader import ROOT
from evals.live_quality import analyse

HEAD = "# X Research Report\n\n## Company Overview\n\n"
REFS = "\n## References\n\n[1] 来源一 — https://a.example/x\n[2] 来源二 — https://b.example/y\n"


def test_detects_founding_year_contradiction_in_same_section() -> None:
    report = HEAD + "- Notion was founded in 2013. [1]\n- Notion was founded in 2014. [2]\n" + REFS
    out = analyse(report)
    assert out["contradiction_count"] == 1
    assert out["contradictions"][0]["values"] == [2013, 2014]
    assert out["contradictions"][0]["section"] == "Company Overview"


def test_no_false_positive_when_years_agree() -> None:
    report = HEAD + "- Notion was founded in 2013. [1]\n- It was founded in 2013 again. [2]\n" + REFS
    assert analyse(report)["contradiction_count"] == 0


def test_marker_without_reference_is_flagged() -> None:
    report = HEAD + "- Some claim. [9]\n" + REFS
    out = analyse(report)
    assert out["citation_integrity_ok"] is False
    assert out["markers_without_reference"] == [9]


def test_well_formed_report_passes_integrity() -> None:
    report = HEAD + "- Some claim. [1]\n- Another claim. [2]\n" + REFS
    out = analyse(report)
    assert out["citation_integrity_ok"] is True
    assert out["claims_count"] == 2
    assert out["source_domain_count"] == 2


def test_real_artifact_is_analysable_when_present() -> None:
    path = ROOT / "evals" / "live_run.json"
    if not path.exists():
        pytest.skip("真实产物尚未生成（需用户放行额度后运行 evals/live_run.py）")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("status") != "ok":
        pytest.skip("真实运行未成功，不检查报告")
    out = analyse(str(data["report"]))
    assert out["claims_count"] > 0
    assert out["method"].startswith("词法")
    assert isinstance(out["contradictions"], list)
