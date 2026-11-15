"""S8.6 护栏：简历数字出处表里的每条数字都必须能当场复现。

与 S8.5 的区别：S8.5 只按字段路径重算；这里**真的执行文档里印出来的
复现命令**（独立 python -c 子进程），并校验 commit 能被 git 解析。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from evals import build_resume_evidence as m

DOC = m.ROOT / "docs" / "RESUME_EVIDENCE.md"
ALL_FACTS = m.facts()


@pytest.fixture(scope="module")
def data() -> dict:
    return m.load_inputs()


@pytest.fixture(scope="module")
def doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_document_is_exactly_the_rendered_output(data: dict, doc: str) -> None:
    assert doc == m.render(data, blocked=0), "文档被手工改过，或生成脚本改了没重新生成"


def test_every_fact_id_is_unique_and_in_document(doc: str) -> None:
    ids = [f.fid for f in ALL_FACTS]
    assert len(ids) == len(set(ids))
    for fid in ids:
        assert f"`{fid}`" in doc


@pytest.mark.parametrize("fact", ALL_FACTS, ids=lambda f: f.fid)
def test_reproduction_command_actually_runs_and_matches_value(fact: m.Fact, data: dict) -> None:
    """文档里那条命令不是摆设：起独立进程执行，stdout 必须与产物取值逐字一致。"""
    code = fact.code()
    assert "build_resume_evidence" not in code, "复现命令不能依赖生成脚本本身"
    assert code.startswith("import json; "), "复现命令必须只读原始产物"
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=m.ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 0, f"{fact.fid} 命令执行失败：{r.stderr[:300]}"
    assert r.stdout.strip() == m.show(fact.value(data)), f"{fact.fid} 命令输出与产物取值不符"


@pytest.mark.parametrize("fact", ALL_FACTS, ids=lambda f: f.fid)
def test_every_fact_row_has_value_source_commit_and_command(fact: m.Fact, data: dict, doc: str) -> None:
    row = next(line for line in doc.splitlines() if line.startswith(f"| `{fact.fid}` |"))
    assert f"`{m.show(fact.value(data))}`" in row
    for key in fact.source_keys():
        assert f"`{m.FILES[key]}`" in row, f"{fact.fid} 缺源文件 {key}"
        assert f"`{m.file_commit(m.FILES[key])}`" in row, f"{fact.fid} 缺 {key} 的 commit"
    assert f"`{fact.path}`" in row
    assert fact.command() in row


def test_verify_mode_passes_for_all_facts(data: dict) -> None:
    rows = m.run_verification(data)
    assert len(rows) == len(ALL_FACTS)
    assert [r for r in rows if not r["ok"]] == []
    assert all(r["command"] == f.command() for r, f in zip(rows, ALL_FACTS))


def test_verify_cli_is_runnable_without_network() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "evals.build_resume_evidence", "--verify"],
        cwd=m.ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout[-500:] + r.stderr[-500:]
    assert "[FAIL]" not in r.stdout
    assert "条复现命令通过" in r.stdout


def test_commits_are_real_git_objects_and_match_file_history() -> None:
    seen = {m.FILES[key] for key in {f.key for f in ALL_FACTS}}
    for rel in seen:
        commit = m.file_commit(rel)
        assert re.fullmatch(r"[0-9a-f]{7}", commit), f"{rel} 的 commit 格式不对：{commit}"
        r = subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=m.ROOT, capture_output=True, text=True,
        )
        assert r.returncode == 0, f"{rel} 的 commit {commit} 无法解析"
        history = subprocess.run(
            ["git", "log", "-1", "--format=%h", "--", rel],
            cwd=m.ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert commit == history


def test_upstream_attribution_is_read_from_file_and_real(doc: str) -> None:
    upstream = m.upstream_commit()
    assert re.fullmatch(r"[0-9a-f]{7}", upstream)
    assert upstream in doc
    assert "Apache-2.0" in doc
    assert "LICENSE" in doc
    assert "不得写「独立开发」" in doc
    r = subprocess.run(
        ["git", "cat-file", "-e", f"{upstream}^{{commit}}"],
        cwd=m.ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 0


def test_generator_has_no_hardcoded_measured_numbers_or_commits() -> None:
    src = Path(m.__file__).read_text(encoding="utf-8")
    for literal in ["2379.819", "4998", "62875.8", "2776", "7896", "3e16906", "53746f6", "55f24cb"]:
        assert literal not in src, f"生成脚本里硬编码了真实数字/commit：{literal}"


def test_banned_rows_all_carry_a_source_and_commit(doc: str) -> None:
    rows = m.banned_rows()
    assert len(rows) >= 8
    for bad, fact, src, why in rows:
        assert bad.startswith("❌")
        assert fact and why
        assert re.search(r"`[0-9a-f]{7}`", src), f"禁写条缺少 commit：{bad}"
        assert "`" in src
        assert bad in doc


def test_banned_topics_cover_every_dangerous_number(doc: str) -> None:
    for topic in [
        "fact_accuracy", "p95_latency_ms", "cost_per_report", "hallucination_rate",
        "summary.supported", "is_human_adjudicated", "citation_layer_usable_as_metric",
        "独立开发", "上线", "本地实测",
    ]:
        assert topic in doc, f"禁写清单漏了：{topic}"


def test_not_measured_items_are_explicit(doc: str) -> None:
    for item in ["真实准确率", "幻觉率", "引用可追溯率", "p95", "成本单价", "未测"]:
        assert item in doc
    assert "**未测**" in doc
    assert "fixture 侧有值、真机侧未测" in doc


def test_zero_call_claim_and_no_secrets(doc: str) -> None:
    assert "**0** 次模型请求" in doc
    assert "**0** Tavily credits" in doc
    assert "拦截外部连接 **0** 次" in doc
    assert "tvly-" not in doc
    assert "sk-" not in doc
    assert m.NOT_MEASURED in doc


def test_resume_wording_interpolates_each_own_value(data: dict, doc: str) -> None:
    for f in ALL_FACTS:
        assert "{v}" in f.resume, f"{f.fid} 的措辞没有插值占位"
        line = f"- `{f.fid}` {f.resume.format(v=m.show(f.value(data)))}"
        assert line in doc, f"{f.fid} 的简历措辞未出现在文档里"


def test_credit_accounting_is_self_consistent(data: dict) -> None:
    """额度记账自洽：累计 = 本轮 + 探针；judge 环节不新增检索。"""
    c = data["live_run"]["credits"]
    assert c["cumulative"] == c["spent_this_run"] + c["spent_in_s8_2"]
    assert c["cumulative"] <= c["user_ceiling"]
    assert data["live_score"]["isolation"]["tavily_credits_used"] == 0
    assert data["live_score"]["isolation"]["tavily_client_search_calls"] == 0


def test_render_is_bound_to_product_values(data: dict) -> None:
    """变异探针：改「已收录数字」的源字段，渲染结果必须跟着变。

    注意不拿 `scorecard...fact_accuracy` 做探针：它只出现在禁写清单里，
    是「不许写」的防御性规则、不引用数值，文档本来就不该随它变化。
    """
    import copy

    original = m.render(data, blocked=0)
    for key, path, value in [
        ("live_run", "credits.cumulative", 999),
        ("scorecard", "external_calls.tavily", 9),
    ]:
        mutated = copy.deepcopy(data)
        cur = mutated[key]
        parts = path.split(".")
        for part in parts[:-1]:
            cur = cur[part]
        cur[parts[-1]] = value
        assert m.render(mutated, blocked=0) != original, f"{key}.{path} 改了文档却没变"


def test_document_is_valid_markdown_tables(doc: str) -> None:
    for line in doc.splitlines():
        if line.startswith("|"):
            assert line.endswith("|"), f"表格行未闭合：{line[:80]}"
            assert line.count("|") >= 3
    assert doc.count("```") % 2 == 0, "代码块未闭合"


def test_fact_expression_matches_declared_path(data: dict) -> None:
    """非派生条目的 expr 必须由同一 path 生成，杜绝出处与命令脱节。"""
    for f in ALL_FACTS:
        if f.expr is None:
            assert f.expression() == m.expr_from_path(f.path)
            assert m.field(data[f.key], f.path) is not None
        else:
            assert "d" in f.expr
            assert f.derive is not None or f.derive_all is not None
        if f.sources:
            assert len(f.sources) > 1
            assert f.derive_all is not None, "跨文件条目必须给 derive_all"
            assert f.expr is not None, "跨文件条目必须显式给 expr"
            for var in (f"d{i}" for i in range(len(f.sources))):
                assert var in f.expr


def test_aggregate_model_requests_equals_its_parts(data: dict) -> None:
    """跨文件求和必须与分项自洽，避免「累计 6 次」变成手抄数。"""
    total = next(f for f in ALL_FACTS if f.fid == "F30").value(data)
    parts = (
        data["llm_probe"]["usage"]["successful_requests"]
        + data["live_run"]["llm_usage"]["successful_requests"]
        + data["live_score"]["usage"]["successful_requests"]
    )
    assert total == parts


def test_verify_reports_single_failure_instead_of_crashing(data: dict) -> None:
    """产物被改坏时，--verify 应报「哪条 FAIL」，而不是整批抛 traceback。"""
    import copy

    broken = copy.deepcopy(data)
    del broken["live_run"]["credits"]["cumulative"]
    rows = m.run_verification(broken)
    assert len(rows) == len(ALL_FACTS), "一条坏字段不应中断其余条目"
    failed = [r["fid"] for r in rows if not r["ok"]]
    assert "F01" in failed
    assert all(r["expected"] is not None or r["fid"] == "F01" for r in rows)
    assert any("KeyError" in str(r["actual"]) for r in rows if r["fid"] == "F01")


def test_every_fact_has_four_required_elements() -> None:
    for f in ALL_FACTS:
        assert f.fid and f.label and f.key in m.FILES and f.path and f.resume and f.note
        assert f.group in {"A", "B", "C"}
        assert f.command().startswith("uv run python -c '")
        assert f.command().endswith("'")
        assert "import evals" not in f.code()
