"""S8.3 端到端真实运行脚本的离线自测（0 credits、0 次真实调用）。

真实数字由 `evals/live_run.py` 单独产出；这里只锁死纯逻辑、护栏与预算算式。
"""

from __future__ import annotations

import pytest

from config.loader import get_settings
from evals import live_run

SAMPLE_REPORT = """# Notion 研究报告

## 公司概况

- Notion 提供笔记与协作工作区。 [1]
- 团队位于 San Francisco。 [2]

## 行业概况

- 协同文档市场持续增长。 [3]

## 财务概况

- 订阅制收入为主。 [4]

## 新闻动态

- 近期发布新版本。 [5]

## References

[1] 产品概览 — https://example.org/a
[2] 关于我们 — https://example.org/b
[3] 市场 — https://example.org/c
[4] 定价 — https://example.org/d
[5] 新闻 — https://example.org/e
"""


def test_report_checks_recognise_a_well_formed_report() -> None:
    c = live_run._report_checks(SAMPLE_REPORT, get_settings())
    assert c["has_four_sections"] is True
    assert c["has_references_section"] is True
    assert c["inline_citation_markers"] == 5
    assert c["reference_lines"] == 5
    assert c["chars"] == len(SAMPLE_REPORT)


def test_report_checks_flag_missing_citations() -> None:
    stripped = "\n".join(
        line for line in SAMPLE_REPORT.splitlines() if not line.startswith("[")
    ).replace(" [1]", "").replace(" [2]", "").replace(" [3]", "").replace(" [4]", "").replace(" [5]", "")
    c = live_run._report_checks(stripped, get_settings())
    assert c["inline_citation_markers"] == 0
    assert c["reference_lines"] == 0
    assert c["has_references_section"] is True


def test_state_summary_is_json_safe() -> None:
    class Opaque:
        def __str__(self) -> str:
            return "opaque"

    out = live_run._state_summary(
        {"degraded": True, "degraded_sections": ["news"], "retry_count": {"news": 2},
         "company": "Notion", "review_notes": [{"status": "ok", "obj": Opaque()}]}
    )
    assert out["degraded"] is True
    assert out["review_notes"][0]["obj"] == "opaque"


def test_refuses_to_start_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="缺少 TAVILY_API_KEY, DASHSCOPE_API_KEY"):
        live_run.build_report()


def test_budget_is_within_user_ceiling() -> None:
    assert live_run.MAX_CALLS == 12
    assert live_run.CREDITS_PER_SEARCH == 2
    # 已用额度以台账 total_credits 为唯一真相（不再用 S8 时点冻结的 2）
    used, ceiling = live_run._ledger_totals()
    assert used >= 0 and ceiling == 200, "上限 2026-11-15 已从 50 放宽到 200"
    worst = live_run.MAX_CALLS * live_run.CREDITS_PER_SEARCH + used
    assert worst == used + 24, "单次最坏消耗仍是 12 次 advanced 检索"
    assert worst <= ceiling, "最坏情况也必须落在放行上限内"


def test_live_env_pins_all_guards() -> None:
    env = live_run.LIVE_ENV
    assert env["APP_MODE"] == "live"
    assert env["TAVILY_LIVE_ENABLED"] == "true"
    assert env["TAVILY_DRY_RUN"] == "false"
    assert env["TAVILY_MAX_CALLS"] == "12"
    assert env["LLM_PROVIDER"] == "dashscope"
    assert env["LLM_MODEL"] == "qwen-plus"
    assert env["FEATURES_HUMAN_REVIEW"] == "false"
