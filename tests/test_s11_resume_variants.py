"""S11 护栏：岗位版只换顺序与解读，不许改事实、不许新增数字。

与 `tests/test_s9_resume.py` 同一套口径，多查两件 S11 特有的事：

1. 三版的重排必须真的不同（否则「按岗位出多版」是假动作）；
2. 每条正文必须与 `docs/RESUME.md` 里那条逐字一致（防止悄悄改写事实句）。
"""

from __future__ import annotations

import re

import pytest

from evals import build_resume as r
from evals import build_resume_evidence as ev
from evals import build_resume_variants as v

DOC = v.OUTPUT
CANON = r.OUTPUT
VARIANTS = v.VARIANTS


@pytest.fixture(scope="module")
def data() -> dict:
    return ev.load_inputs()


@pytest.fixture(scope="module")
def doc() -> str:
    return DOC.read_text(encoding="utf-8")


def _values(data: dict) -> dict[str, str]:
    return r.fact_values(data)


def test_document_is_exactly_the_rendered_output(data: dict, doc: str) -> None:
    assert doc == v.render(data), "文档被手工改过，或生成脚本改了没重新生成"


def test_three_role_variants() -> None:
    roles = [x.role for x in VARIANTS]
    assert len(VARIANTS) == 3, "岗位版就是要三个方向"
    assert len(roles) == len(set(roles)), "岗位名重复"


def test_each_variant_keeps_exactly_three_distinct_bullets() -> None:
    for var in VARIANTS:
        assert len(var.keep) == v.BULLETS_PER_VARIANT
        assert len(set(var.keep)) == len(var.keep), f"{var.role} 有重复条目"
        for title in var.keep:
            assert title in v.BY_TITLE, f"{var.role} 引用了不存在的条目：{title}"


def test_each_variant_has_an_angle_for_every_kept_bullet() -> None:
    for var in VARIANTS:
        assert set(var.angles) == set(var.keep), f"{var.role} 的解读与条目对不上"


def test_orders_are_actually_different() -> None:
    """三版如果排法一样，「按岗位出多版」就没有意义。"""
    orders = [tuple(x.keep) for x in VARIANTS]
    assert len(set(orders)) == len(orders), "有岗位版的排序完全相同"
    firsts = [x.keep[0] for x in VARIANTS]
    assert len(set(firsts)) >= 2, "三版开头全是同一条，等于没分方向"


def test_templates_contain_no_bare_numbers() -> None:
    """模板只允许 `{Fxx}` 占位符与白名单标识（sha256 等），和 S9 同一把尺。"""
    for var in VARIANTS:
        for text in var.texts():
            stripped = re.sub(r"`[^`]*`", "", text)
            stripped = r.PLACEHOLDER.sub("", stripped)
            stripped = re.sub(r"\bp95\b", "", stripped)
            for token in r.TEMPLATE_ALLOWED_TOKENS:
                stripped = stripped.replace(token, "")
            found = re.findall(r"\d+(?:\.\d+)?", stripped)
            assert not found, f"{var.role} 的模板里出现裸数字 {found}：{text[:60]}"


def _resume_body(doc: str) -> str:
    """只留「真的会写进简历的部分」。

    「这一版不要写」那几行是在点名禁写词（「没压测、没上线」），本身含禁写词，
    不能当成简历正文来查；和 `docs/RESUME.md` 的 §4 一样单独排除。
    """
    body = doc.split("## 1. ")[1].split("## 4. 三版共用的底线")[0]
    kept: list[str] = []
    skipping = False
    for line in body.splitlines():
        if line.startswith("**这一版不要写**"):
            skipping = True
            continue
        if skipping and line.startswith("- "):
            continue
        if line.startswith("**") or line.startswith("代码位置"):
            skipping = False
        kept.append(line)
    return "\n".join(kept)


def test_every_variant_number_comes_from_the_evidence_table(data: dict, doc: str) -> None:
    """正文区的每个数字都得能在出处表里找到；§6 只是结构计数，不在射程内。"""
    allowed = set(_values(data).values())
    stray = [n for n in r.measured_numbers(_resume_body(doc)) if n not in allowed]
    assert not stray, f"岗位版出现出处表没有的数字：{stray}"


def test_pasted_text_is_byte_identical_to_the_canonical_bullet(data: dict, doc: str) -> None:
    """岗位版不许改写事实句：粘贴行必须与 `docs/RESUME.md` 的对应条目逐字相同。"""
    values = _values(data)
    canonical = CANON.read_text(encoding="utf-8")
    for var in VARIANTS:
        for b in var.bullets():
            pasted = f"- **{b.title}**：{r.fill(b.paste, values)}"
            assert pasted in doc, f"{var.role} 少了这条粘贴行：{b.title}"
            assert pasted in canonical, f"{b.title} 与 docs/RESUME.md 的原文不一致"


def test_no_placeholders_left_and_no_secrets(doc: str) -> None:
    assert "{F" not in doc
    assert "sk-" not in doc
    assert "tvly-" not in doc


def test_forbidden_claims_absent_from_variant_bodies(doc: str) -> None:
    body = _resume_body(doc)
    for word in ["独立开发", "从零自研", "上线", "甲方", "用户量", "SOTA", "领先"]:
        assert word not in body, f"岗位版正文出现禁写词：{word}"


def test_attribution_present(doc: str) -> None:
    assert "guy-hartstein/company-research-agent" in doc
    assert "Apache-2.0" in doc
    assert "二次开发" in doc
    assert ev.upstream_commit() in doc


def test_every_referenced_path_exists() -> None:
    for var in VARIANTS:
        for b in var.bullets():
            for code in b.code:
                assert (v.ROOT / code).exists(), f"岗位版指到的文件不存在：{code}"


def test_markdown_is_sane(doc: str) -> None:
    assert doc.startswith("# ")
    assert doc.count("```") % 2 == 0
    for line in doc.splitlines():
        if line.startswith("|"):
            assert line.endswith("|")


def test_bullet_titles_are_all_covered_across_variants() -> None:
    """三条一版，三个方向合起来应该把四条都用上；否则有一条永远上不了简历。"""
    used = {t for var in VARIANTS for t in var.keep}
    assert used == set(v.BY_TITLE), f"这些条目在所有岗位版里都没出现：{set(v.BY_TITLE) - used}"
