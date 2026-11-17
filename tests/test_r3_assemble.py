"""R3 验收（拼装器）：子图段落 → 统一编号 → 报告。

验证：
1. 多个栏目都带同一个 URL 时，编号不撞（都用同一个 [n]）；
2. 正文 [n] 与 References 同源；
3. 降级栏目输出拒答话术，不硬凑；
4. 冲突标注用引用块，不参与 bullet 引用统计。

纯函数、0 网络 0 模型。
"""

from __future__ import annotations

from config.loader import get_settings
from graph.nodes.assemble import assemble_report


def _section(key: str, heading: str, facts: list[dict], refs: dict, **kw) -> dict:
    return {"key": key, "heading": heading, "facts": facts, "references": refs, **kw}


def test_shared_url_gets_one_number_no_collision() -> None:
    """Company 和 Industry 都引用同一个 URL → 编号相同，不撞号。"""
    s = get_settings()
    url = "https://e.org/shared"
    sections = [
        _section("company", "公司概况",
                 [{"claim": "事实A", "source_url": url}],
                 {url: {"title": "Shared", "score": 0.9}}),
        _section("industry", "行业概况",
                 [{"claim": "事实B", "source_url": url}],
                 {url: {"title": "Shared", "score": 0.9}}),
    ]
    report, _ = assemble_report("X", sections, s)
    assert report.count("[1]") == 3, "两处正文 + 1 处 References 都应指向 [1]"
    assert "- 事实A [1]" in report
    assert "- 事实B [1]" in report


def test_body_markers_match_references() -> None:
    s = get_settings()
    u1, u2 = "https://e.org/a", "https://e.org/b"
    sections = [
        _section("company", "公司概况",
                 [{"claim": "A", "source_url": u1}, {"claim": "B", "source_url": u2}],
                 {u1: {"title": "A源", "score": 0.9}, u2: {"title": "B源", "score": 0.5}}),
    ]
    report, _ = assemble_report("X", sections, s)
    assert "- A [1]" in report and "- B [2]" in report, "score 高的排前面"
    assert "[1] A源 — https://e.org/a" in report
    assert "[2] B源 — https://e.org/b" in report


def test_degraded_section_uses_refusal_text() -> None:
    s = get_settings()
    sections = [
        _section("company", "公司概况", [], {}, status="degraded"),
    ]
    report, briefings = assemble_report("X", sections, s)
    assert s.graph.degrade.message in report
    assert briefings["company"]["status"] == "degraded"
    assert "## References" in report  # 空 References 也保留


def test_conflict_is_quote_block_not_bullet() -> None:
    s = get_settings()
    url = "https://e.org/a"
    sections = [
        _section("company", "公司概况",
                 [{"claim": "成立于 2013", "source_url": url}],
                 {url: {"title": "A", "score": 0.9}},
                 conflicts=["成立年份：2013 [1] / 2014 [2]"]),
    ]
    report, _ = assemble_report("X", sections, s)
    assert "> 成立年份" in report, "冲突标注是引用块"
    quote_lines = [ln for ln in report.splitlines() if ln.startswith(">")]
    assert len(quote_lines) == 1


def test_fact_without_url_has_no_marker() -> None:
    """没 URL 的 fact 不挂编号（不可溯源就不标，而非乱标）。"""
    s = get_settings()
    sections = [
        _section("company", "公司概况", [{"claim": "无来源事实", "source_url": ""}], {}),
    ]
    report, _ = assemble_report("X", sections, s)
    assert "- 无来源事实\n" in report
    assert "- 无来源事实 [" not in report
