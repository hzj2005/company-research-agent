"""R4 收尾验收：栏目附加分析渲染（受 postprocess 开关控制，不改正文 bullet）。

两条硬要求：
1. 开关关闭（默认）→ 报告里没有任何分析行，与不渲染时逐字一致；
2. 开关开启 → 分析行以 `>` 开头（不污染"每条 bullet 带引用"统计），
   且行内 [n] 编号必须能在 References 找到（编号同源红线）。
"""

from __future__ import annotations

import re

from config.loader import apply_overrides, get_settings
from graph.nodes.assemble import assemble_report

_SECTION = {
    "key": "financial", "status": "ok",
    "facts": [{"claim": "2021 年完成 A 轮融资 5000 万美元。", "source_url": "https://e.org/a"}],
    "references": {
        "https://e.org/a": {"title": "A", "score": 0.9},
        "https://e.org/b": {"title": "B", "score": 0.8},
    },
    "conflicts": [],
    "analysis": {
        "timeline": [
            {"round": "A轮", "amount": "5000 万美元", "year": "2021",
             "source_url": "https://e.org/a"},
            {"round": "B轮", "amount": "2 亿美元", "year": "2023",
             "source_url": "https://e.org/b"},
        ],
        "unverified": [],
    },
}


def test_postprocess_off_no_analysis_lines() -> None:
    s = get_settings()
    assert s.features.postprocess is False
    report, _ = assemble_report("X", [_SECTION], s)
    assert "融资时间线" not in report
    assert not [ln for ln in report.splitlines() if "融资时间线" in ln]


def test_postprocess_on_renders_as_quote_block() -> None:
    s = apply_overrides(get_settings(), {"features.postprocess": True})
    report, _ = assemble_report("X", [_SECTION], s)
    line = next(ln for ln in report.splitlines() if "融资时间线" in ln)
    assert line.startswith("> "), "分析行必须是引用块，不能是 bullet"
    assert "2021" in line and "2023" in line
    assert "→" in line, "时间线应按年份连接"


def test_analysis_citations_resolve_to_references() -> None:
    s = apply_overrides(get_settings(), {"features.postprocess": True})
    report, _ = assemble_report("X", [_SECTION], s)
    line = next(ln for ln in report.splitlines() if "融资时间线" in ln)
    used = {int(n) for n in re.findall(r"\[(\d+)\]", line)}
    refs = {int(n) for n in re.findall(r"^\[(\d+)\] ", report, flags=re.M)}
    assert used and used <= refs, "分析行的编号必须能在 References 找到"


def test_analysis_never_adds_factual_bullets() -> None:
    """分析行不得以 `- ` 开头，否则会被误算成事实 bullet。"""
    s = apply_overrides(get_settings(), {"features.postprocess": True})
    report, _ = assemble_report("X", [_SECTION], s)
    bullets = [ln for ln in report.splitlines() if ln.startswith("- ")]
    assert len(bullets) == 1, "只有 1 条真实事实 bullet，分析行不得混入"
    assert not any("融资时间线" in b for b in bullets)
