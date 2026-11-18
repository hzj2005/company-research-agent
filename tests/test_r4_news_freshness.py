"""R4-2 验收：News 时效标注 + 事件去重（不删事实）。

验证：
1. 同一事件多来源被聚成一组，multi_source 为真；
2. 过旧年份的事实被标 stale，但不从 facts 里删除；
3. analysis 字段进段落，含 events / stale_count / reference_year。
"""

from __future__ import annotations

from datetime import date

from config.loader import get_settings
from graph.agents.news.analyzer import analyze_news


def _fact(claim: str, url: str) -> dict:
    return {"claim": claim, "source_url": url, "confidence": 0.8, "_round": 0}


def test_same_event_multi_source_grouped() -> None:
    year = date.today().year
    facts = [
        _fact(f"{year} 年 Notion 推出 AI 写作功能。", "https://e.org/1"),
        _fact(f"{year} 年 Notion 发布 AI 写作能力。", "https://e.org/2"),
    ]
    out = analyze_news(facts, "Notion", get_settings())
    events = out["analysis"]["events"]
    assert any(e["multi_source"] for e in events), "同事件多来源应聚合且标 multi_source"
    assert out["analysis"]["reference_year"] == year


def test_stale_marked_but_not_deleted() -> None:
    facts = [
        _fact("2015 年 Notion 获得早期融资。", "https://e.org/old"),
        _fact(f"{date.today().year} 年 Notion 发布新版本。", "https://e.org/new"),
    ]
    out = analyze_news(facts, "Notion", get_settings())
    assert out["analysis"]["stale_count"] == 1
    assert out["analysis"]["stale_urls"] == ["https://e.org/old"]
    # 事件里两条都在（不删事实）
    total = sum(e["count"] for e in out["analysis"]["events"])
    assert total == 2


def test_analyzer_returns_conflicts_and_analysis_shape() -> None:
    out = analyze_news([_fact("2024 年发布功能。", "https://e.org/a")], "X", get_settings())
    assert set(out.keys()) == {"conflicts", "analysis"}
    assert out["conflicts"] == []
    assert "events" in out["analysis"]
