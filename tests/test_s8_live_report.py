"""S8.5 对比表的离线护栏（0 次模型 / Tavily 调用）。

核心契约：docs/LIVE_REPORT.md 必须由 evals/build_live_report.py 从既有产物生成，
文档里每个数字都能按它自己标注的「文件 → 字段」重算出来，模板里不许写死数值。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from evals import build_live_report as b

DOC = b.ROOT / "docs" / "LIVE_REPORT.md"


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def _data() -> dict[str, Any]:
    return b.load_inputs()


def _src() -> str:
    return open(b.__file__, encoding="utf-8").read()  # noqa: SIM115


# --- 可复现性：文档不是手写的 ---

def test_document_is_exactly_the_generated_output() -> None:
    assert DOC.exists(), "缺少 docs/LIVE_REPORT.md，请跑 uv run python -m evals.build_live_report"
    assert b.render(_data(), blocked=0) == _doc(), "文档被手改过或产物变化后未重新生成"


def test_render_is_deterministic() -> None:
    data = _data()
    assert b.render(data, blocked=0) == b.render(data, blocked=0)
    assert b.render(data, blocked=1) != _doc(), "blocked 是唯一可变输入，必须真的影响文档"


def test_all_six_input_files_exist_and_are_json() -> None:
    for rel in b.FILES.values():
        doc = json.loads((b.ROOT / rel).read_text(encoding="utf-8"))
        assert isinstance(doc, dict) and doc, f"{rel} 不是非空 JSON 对象"


# --- 每个数字按自己标出的出处重算 ---

def test_every_table_cell_recomputes_from_its_declared_path() -> None:
    data = _data()
    doc = _doc()
    cells = b.table_cells(data)
    assert len(cells) >= 60, "对比表的取数点太少，可能漏掉了整节表格"
    for c in cells:
        rendered = f"{c.text} 〔{c.ref}〕" if c.ref else c.text
        assert rendered in doc, f"表格里找不到这一格：{rendered[:120]}"
        if c.value is None:
            continue  # 「未测」/ 定性描述不参与数值重算
        raw = b.field(data[c.key], c.path)
        actual = c.transform(raw) if c.transform else raw
        assert actual == c.value, f"{c.key}:{c.path} 与产物不一致"
        assert c.text == b.show(c.value), f"{c.key}:{c.path} 显示值与真实值不符"


def test_known_issue_numbers_recompute_from_artifacts() -> None:
    data = _data()
    doc = _doc()
    for c in b.known_issue_cells(data):
        raw = b.field(data[c.key], c.path)
        actual = c.transform(raw) if c.transform else raw
        assert actual == c.value, f"已知问题取数错误：{c.key}:{c.path}"

    entity_hits = data["live_run"]["report"].count("Notion VTec Berhad")
    assert entity_hits > 0, "报告里找不到实体混淆证据，文档 §5 的说法就失去依据"
    assert f"**{entity_hits}** 次" in doc
    assert "medium.com" in data["live_quality"]["checks"]["source_domains"]
    assert data["live_score"]["is_human_adjudicated"] is False
    assert "is_human_adjudicated = false" in doc


def test_no_key_numbers_are_hardcoded_in_the_generator() -> None:
    src = _src()
    # 这些都是产物里的实测值；它们只能由 field() 读入，不能出现在模板字符串里
    banned = ["2379.819", "62875.8", "4998", "7896", "2776", "0.869565", "8 / 50"]
    for token in banned:
        assert token not in src, f"生成脚本写死了 {token}，产物一变文档就会说谎"


def test_field_rejects_paths_that_do_not_exist() -> None:
    data = _data()
    with pytest.raises(KeyError):
        b.field(data["scorecard"], "runs.baseline.metrics.does_not_exist")
    # 列表索引必须真能解析，否则 §5 的 2013/2014 出处就是假的
    assert b.field(data["live_quality"], "checks.contradictions[0].values") == [2013, 2014]


# --- 口径边界：不许把 fixture 数值当真实指标 ---

def test_fixture_side_is_explicitly_scoped_as_synthetic() -> None:
    data = _data()
    doc = _doc()
    sc = data["scorecard"]
    assert sc["mode"] == "fixture"
    assert sc["provenance"] == "synthetic-fixture-derived"
    assert all(v == 0 for v in sc["external_calls"].values()), "fixture 侧必须 0 外部调用"
    assert sc["disclaimer"] in doc, "fixture 自带的免责声明必须原文出现在对比表里"
    assert "合成语料" in doc and "契约回归" in doc


def test_fixture_p95_and_cost_are_never_presented_as_real() -> None:
    data = _data()
    doc = _doc()
    p95 = b.field(data["scorecard"], "runs.baseline.metrics.p95_latency_ms")
    cost = b.field(data["scorecard"], "runs.baseline.metrics.cost_per_report")
    elapsed = b.field(data["live_run"], "timing.elapsed_ms")
    assert f"`p95_latency_ms = {p95}`" in doc
    assert f"`cost_per_report = {cost}`" in doc
    assert "不是真实 p95" in doc
    assert "不是 p95" in doc
    assert f"单次墙钟是 {elapsed} ms" in doc
    assert "fixture 侧有值、真机侧全部未测" in doc
    # 不能出现把 fixture 数值直接挂到真实字样上的句子
    assert f"真实 p95 = {p95}" not in doc
    assert f"真实成本 = {cost}" not in doc


def test_eight_metrics_are_marked_unmeasured_on_the_live_side() -> None:
    data = _data()
    rows = b.comparison_rows(data)
    metrics = [r for r in rows if r.metric.startswith(("事实准确率", "引用可追溯", "幻觉率", "p95", "单份成本", "拒答率", "自纠正", "平均重试"))]
    assert len(metrics) == 8
    assert all(r.live.text == b.NOT_MEASURED for r in metrics)
    assert _doc().count(f"| {b.NOT_MEASURED} 〔") == 8, "「未测」格子数应与 8 个指标一一对应"


def test_red_line_list_is_present() -> None:
    doc = _doc()
    for phrase in [
        "不能相减", "准确率 0%", "零成本", "都测了",
        "上线 / 甲方 / 用户量", "**未测**", "不修、也不复测",
    ]:
        assert phrase in doc, f"红线清单缺：{phrase}"


def test_sample_size_limit_is_stated_with_real_numbers() -> None:
    data = _data()
    doc = _doc()
    s = data["live_score"]
    scored = b.field(s, "dataset.scored_claims")
    skipped = b.field(s, "dataset.skipped_claims")
    total = b.field(s, "dataset.total_claims_in_golden")
    assert scored + skipped == total
    assert f"把 {total} 条 golden 写成「都测了」" in doc
    assert f"当前只有 {scored} 条有真实报告可比" in doc
    assert f"另 {skipped} 条如实跳过" in doc
    assert "仅 " in doc and "一份真实报告" in doc


# --- A/B 佐证与 0 调用声明 ---

def test_ab_evidence_comes_from_scorecard_and_really_differs() -> None:
    data = _data()
    doc = _doc()
    sc = data["scorecard"]
    base = sc["runs"]["baseline"]["metrics"]
    off = sc["runs"]["no_inline_citations"]["metrics"]
    self_off = sc["runs"]["self_correction_off"]["metrics"]
    assert base["citation_traceability"] != off["citation_traceability"]
    assert base["hallucination_rate"] != off["hallucination_rate"]
    assert base["fact_accuracy"] == off["fact_accuracy"], "关掉行内引用不影响事实准确率，正是论证的关键"
    assert base["fact_accuracy"] != self_off["fact_accuracy"]
    assert str(self_off["fact_accuracy"]) in doc
    assert "分数随开关变化" in doc
    assert "不参与 A/B 判定" in doc


def test_zero_call_claim_is_backed_by_four_artifacts() -> None:
    data = _data()
    doc = _doc()
    assert all(v == 0 for v in data["scorecard"]["external_calls"].values())
    assert data["live_score"]["isolation"]["tavily_credits_used"] == 0
    assert data["live_score"]["isolation"]["tavily_client_search_calls"] == 0
    assert all(v == 0 for v in data["audit"]["isolated_calls"].values())
    creds = data["dryrun"]["credentials"]
    assert creds["tavily_key_resolutions"] == 0
    assert creds["llm_key_resolutions"] == 0
    assert creds["async_tavily_client_constructions"] == 0
    cumulative = b.field(data["live_run"], "credits.cumulative")
    ceiling = b.field(data["live_run"], "credits.user_ceiling")
    assert f"累计 **{cumulative} / {ceiling} credits**" in doc
    assert "0 Tavily credits" in doc
    assert "**0** 次外部连接" in doc


def test_generator_cannot_reach_live_stack() -> None:
    src = _src()
    for forbidden in [
        "AsyncTavilyClient", "ChatOpenAI", "import requests", "import httpx",
        "subprocess", "run_live(", "run_eval.main", "judge.run_live",
    ]:
        assert forbidden not in src, f"生成脚本不该接触 {forbidden}"
    assert "eval_offline_guard" in src, "生成时必须装禁网守卫"
    assert "assert not attempts" in src, "守卫拦到连接必须拒绝写文档"
