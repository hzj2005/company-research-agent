"""R7 验收：新闻语义实体过滤。

真事故（2026-11-18 live）：`Sia Partners buys … Notion Consulting` 被当成
Notion（协作工具）的动态。字面规则挡不住（Notion Labs, Inc. 就是 Notion 自己），
只能靠语义判定。这里用注入的假判定验证节点行为，0 次真实调用。
"""

from __future__ import annotations

import asyncio
from typing import Any

from capabilities.entity_filter import make_filter_entity_node
from config.loader import get_settings


def _doc(url: str, title: str) -> dict[str, Any]:
    return {"url": url, "title": title, "content": "x", "score": 0.9}


def _state(docs: list[dict[str, Any]]) -> dict[str, Any]:
    return {"company": "Notion", "docs": docs, "notes": []}


def test_different_entity_is_dropped() -> None:
    docs = [
        _doc("https://e.org/a", "Notion 发布 AI 功能"),
        _doc("https://e.org/b", "Sia Partners buys Notion Consulting"),
    ]

    async def judge(company: str, docs: list[dict[str, Any]], settings: Any) -> dict[int, str]:
        return {0: "same", 1: "different"}

    node = make_filter_entity_node("news", get_settings(), judge=judge)
    out = asyncio.run(node(_state(docs)))
    urls = [d["url"] for d in out["docs"]]
    assert urls == ["https://e.org/a"], "同名咨询公司应被剔除"
    note = [n for n in out["notes"] if n["node"] == "filter_entity"][0]
    assert note["dropped"][0]["url"] == "https://e.org/b"


def test_uncertain_is_kept_and_flagged() -> None:
    docs = [_doc("https://e.org/c", "Notion 相关报道")]

    async def judge(company: str, docs: list[dict[str, Any]], settings: Any) -> dict[int, str]:
        return {}

    node = make_filter_entity_node("news", get_settings(), judge=judge)
    out = asyncio.run(node(_state(docs)))
    assert len(out["docs"]) == 1, "无法判断时必须保留，不能删"
    assert out["docs"][0].get("entity_uncertain") is True


def test_judge_failure_keeps_everything() -> None:
    docs = [_doc("https://e.org/d", "某条新闻")]

    async def judge(company: str, docs: list[dict[str, Any]], settings: Any) -> dict[int, str]:
        raise RuntimeError("llm down")

    node = make_filter_entity_node("news", get_settings(), judge=judge)
    out = asyncio.run(node(_state(docs)))
    assert len(out["docs"]) == 1, "判定失败要放行，不能因为模型挂了就把新闻清空"
    assert any(n.get("status") == "failed" for n in out["notes"])


def test_fixture_mode_skips_without_calling_judge() -> None:
    called: list[int] = []

    async def judge(company: str, docs: list[dict[str, Any]], settings: Any) -> dict[int, str]:
        called.append(1)
        return {}

    # 不注入 judge 时，fixture 模式应直接跳过（不发起任何 LLM 调用）
    node = make_filter_entity_node("news", get_settings())
    out = asyncio.run(node(_state([_doc("https://e.org/e", "x")])))
    assert called == []
    assert len(out["docs"]) == 1
    assert any(n.get("status") == "skipped" for n in out["notes"])
