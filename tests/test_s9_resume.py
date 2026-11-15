"""S9 护栏：简历里的每个数字都必须来自出处表，禁写词不得出现在描述里。

三道检查互相咬合：
1. 文档 == 生成脚本的输出（手改会红）；
2. 模板里不许有裸数字——所有数值只能走 `{F01}` 占位符；
3. 渲染后的正文里，除代码/编号外的数字必须能在出处表里找到同名取值。
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from evals import build_resume as r
from evals import build_resume_evidence as ev

DOC = r.OUTPUT
BULLETS = r.BULLETS
QA_LIST = r.QA_LIST


@pytest.fixture(scope="module")
def data() -> dict:
    return ev.load_inputs()


@pytest.fixture(scope="module")
def doc() -> str:
    return DOC.read_text(encoding="utf-8")


def _values(data: dict) -> dict[str, str]:
    return r.fact_values(data)


def test_document_is_exactly_the_rendered_output(data: dict, doc: str) -> None:
    assert doc == r.render(data), "文档被手工改过，或生成脚本改了没重新生成"


def test_has_three_or_four_bullets() -> None:
    assert 3 <= len(BULLETS) <= 4
    titles = [b.title for b in BULLETS]
    assert len(titles) == len(set(titles)), "条目标题重复"


def test_every_bullet_cites_facts_and_shows_their_values(data: dict) -> None:
    values = _values(data)
    for b in BULLETS:
        fids = b.facts()
        assert fids, f"{b.title} 没有引用任何出处编号"
        text = r.fill(b.text(), values)
        for fid in fids:
            assert f"F{fid}" in [f"F{x}" for x in fids]
            assert values[f"F{fid}"] in text, f"{b.title} 引了 F{fid} 却没写出它的值"


def test_bullets_cite_only_existing_facts() -> None:
    known = {f.fid for f in ev.facts()}
    for b in BULLETS:
        for fid in b.facts():
            assert f"F{fid}" in known, f"{b.title} 引用了不存在的编号 F{fid}"


def test_templates_contain_no_bare_numbers() -> None:
    """模板里只允许 `{F01}` 占位符、行内代码与白名单标识（sha256 / 版本号）。"""
    texts = []
    for b in BULLETS:
        texts += [b.paste, *b.detail]
    for qa in QA_LIST:
        texts += [qa.question, qa.answer]
    for text in texts:
        stripped = re.sub(r"`[^`]*`", "", text)
        stripped = r.PLACEHOLDER.sub("", stripped)
        stripped = re.sub(r"\bp95\b", "", stripped)
        for token in r.TEMPLATE_ALLOWED_TOKENS:
            stripped = stripped.replace(token, "")
        found = re.findall(r"\d+(?:\.\d+)?", stripped)
        assert not found, f"模板里出现裸数字 {found}：{text[:80]}"


def _measured_numbers(text: str) -> list[str]:
    """去掉代码、编号、章节号、指标名后剩下的数字，才是「当作事实写出来的数字」。"""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"\bF\d{2}\b", "", text)
    text = re.sub(r"\bQ\d+\b", "", text)
    text = re.sub(r"\bS\d+\b", "", text)
    text = re.sub(r"§\d+(?:\.\d+)*", "", text)
    text = re.sub(r"(?m)^#{1,6}\s*[\d.]*\s*", "", text)
    text = re.sub(r"(?m)^\s*\d+\.\s+", "", text)
    text = text.replace("Apache-2.0", "")
    text = re.sub(r"\bp95\b", "", text)
    for token in r.TEMPLATE_ALLOWED_TOKENS:
        text = text.replace(token, "")
    return re.findall(r"\d+(?:\.\d+)?", text)


def test_every_number_in_document_comes_from_the_evidence_table(data: dict, doc: str) -> None:
    allowed = set(_values(data).values())
    stray = [n for n in _measured_numbers(doc) if n not in allowed]
    assert not stray, f"简历里出现了出处表没有的数字：{stray}"


def test_resume_body_has_no_forbidden_claims(doc: str) -> None:
    """描述正文（§1/§2）不得出现夸大或虚假归因；§4 是「不能写」清单，另算。"""
    body = doc.split("## 1. 可直接粘贴的简历条目")[1].split("## 3. 面试追问清单")[0]
    for word in ["独立开发", "从零自研", "上线", "甲方", "用户量", "SOTA", "领先"]:
        assert word not in body, f"简历正文出现禁写词：{word}"


def test_forbidden_list_is_present_and_complete(doc: str) -> None:
    tail = doc.split("## 4. 不能写的话")[1]
    for word in ["准确率", "幻觉率", "引用可追溯率", "p95", "成本单价", "未测", "独立开发", "上线"]:
        assert word in tail, f"§4 漏了：{word}"


def test_p95_never_carries_a_value(doc: str) -> None:
    """p95 可以被提到（说「未测」），但不能紧跟着一个数字冒充延迟。"""
    for line in doc.splitlines():
        if re.search(r"p95[^。\n]{0,8}\d", line):
            assert "未测" in line or "不是 p95" in line, f"p95 被当成指标写了：{line[:80]}"


def test_attribution_and_upstream_commit_are_real(doc: str) -> None:
    upstream = ev.upstream_commit()
    assert "guy-hartstein/company-research-agent" in doc
    assert "Apache-2.0" in doc
    assert "二次开发" in doc
    assert upstream in doc
    r2 = __import__("subprocess").run(
        ["git", "cat-file", "-e", f"{upstream}^{{commit}}"], cwd=r.ROOT, capture_output=True
    )
    assert r2.returncode == 0


def test_every_referenced_path_exists() -> None:
    paths = [c for b in BULLETS for c in b.code]
    paths += [p for qa in QA_LIST for p in qa.refs]
    for rel in paths:
        assert (r.ROOT / rel).exists(), f"文档里指到的文件不存在：{rel}"


def test_qa_list_is_usable() -> None:
    assert len(QA_LIST) >= 14, "面试追问太少，覆盖不到设计/口径/问题/复现四类"
    groups = {qa.group for qa in QA_LIST}
    assert groups == {"设计取舍", "数字口径", "问题定位", "复现与额度"}
    for qa in QA_LIST:
        assert qa.question.endswith("？"), qa.question
        assert len(qa.answer) >= 80, f"回答太短：{qa.question}"
        assert qa.refs, f"回答没有指路：{qa.question}"
        assert all("`" in f"`{p}`" for p in qa.refs)


def test_no_placeholders_left_and_no_secrets(doc: str) -> None:
    assert "{F" not in doc
    assert "sk-" not in doc
    assert "tvly-" not in doc


def test_markdown_is_sane(doc: str) -> None:
    assert doc.startswith("# ")
    assert doc.count("```") % 2 == 0
    for line in doc.splitlines():
        if line.startswith("|"):
            assert line.endswith("|")


def test_render_is_bound_to_evidence_values(data: dict) -> None:
    """变异探针：改出处表的源字段，简历必须跟着变，不能是手抄的。"""
    original = r.render(data)
    mutated = copy.deepcopy(data)
    mutated["golden_live"][0]["claims_revised_by_user"] = 999
    assert r.render(mutated) != original
    mutated2 = copy.deepcopy(data)
    mutated2["live_run"]["credits"]["user_ceiling"] = 999
    assert r.render(mutated2) != original


def test_unknown_placeholder_raises() -> None:
    with pytest.raises(KeyError):
        r.fill("引用 {F99}", _values(ev.load_inputs()))


def test_zero_call_claim_matches_generator() -> None:
    src = Path(r.__file__).read_text(encoding="utf-8")
    assert "eval_offline_guard" in src, "生成脚本必须装禁网守卫"
    data = json.loads((r.ROOT / "evals" / "scorecard.json").read_text(encoding="utf-8"))
    assert data["external_calls"]["tavily"] == 0
