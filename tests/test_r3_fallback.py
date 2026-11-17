"""R3 补漏验收：三级降级链（LLM → 本地小模型预留 → 规则）真的接上了。

验证：
1. 四栏目 extract 都调用共享 extract_with_fallback（不再是四份独立实现）；
2. 本地小模型注入点有效：LLM 失败时若注入 local_model，会走 ②；
3. 无 local_model 时 LLM 失败落到 ③ 规则抽取，并留痕原因。

0 网络 0 模型（用 fixture backend + 注入的假 local_model）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableLambda

import config.loader as loader
from config.loader import Settings, get_settings
from graph.agents.extract import extract_with_fallback
from graph.contracts import Fact, SectionBrief
from pydantic import HttpUrl


def _settings() -> Settings:
    return get_settings()


def _docs() -> list[dict[str, Any]]:
    return [{"url": "https://e.org/a", "content": "事实甲", "score": 0.9}]


def test_four_sections_share_extract_with_fallback() -> None:
    """结构上：四栏目 nodes.py 都 import 共享函数（不再各写一份降级）。"""
    root = Path(__file__).resolve().parent.parent
    for sec in ("company", "industry", "financial", "news"):
        src = (root / "graph" / "agents" / sec / "nodes.py").read_text(encoding="utf-8")
        assert "extract_with_fallback" in src, f"{sec} 未接共享降级链"


def test_local_model_injection_point_works() -> None:
    """② 预留接口：LLM 失败 + 注入 local_model → 走本地小模型。"""
    s = _settings()

    class FakeLocal:
        async def __call__(self, company: str, section: str, docs: list[dict]) -> SectionBrief:
            return SectionBrief(
                section=section,
                facts=[Fact(claim="本地模型事实", source_url=HttpUrl("https://e.org/local"),
                            confidence=0.5)],
            )

    # 让 LLM 失败：注入一个抛异常的 backend 工厂
    class FailingBackend:
        chain = RunnableLambda(lambda _p: (_ for _ in ()).throw(RuntimeError("LLM down")))
        mode = "test"

        async def aclose(self) -> None:
            pass

    orig = loader.make_briefing_backend if hasattr(loader, "make_briefing_backend") else None
    import graph.agents.extract as ex

    saved = ex.make_briefing_backend
    ex.make_briefing_backend = lambda settings, **kw: FailingBackend()
    try:
        facts, status, notes = asyncio.run(
            ex.extract_with_fallback(
                "X", "company", _docs(), s,
                addendum="test", local_model=FakeLocal(),
            )
        )
    finally:
        ex.make_briefing_backend = saved

    assert status == "ok"
    assert facts[0]["claim"] == "本地模型事实"
    assert notes[0]["status"] == "local_model"


def test_falls_back_to_rules_with_reason() -> None:
    """无 local_model + LLM 失败 → ③ 规则抽取，留痕原因。"""
    s = _settings()
    import graph.agents.extract as ex

    class FailingBackend:
        chain = RunnableLambda(lambda _p: (_ for _ in ()).throw(RuntimeError("LLM down")))
        mode = "test"

        async def aclose(self) -> None:
            pass

    saved = ex.make_briefing_backend
    ex.make_briefing_backend = lambda settings, **kw: FailingBackend()
    try:
        facts, status, notes = asyncio.run(
            ex.extract_with_fallback("X", "company", _docs(), s, addendum="test")
        )
    finally:
        ex.make_briefing_backend = saved

    assert status == "no_retry"
    assert facts[0]["claim"] == "事实甲"  # 规则把 content 直接转 fact
    assert notes[0]["status"] == "rule_fallback"
    assert notes[0]["reason"] == "llm_and_local_model_unavailable"
