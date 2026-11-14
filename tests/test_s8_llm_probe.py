"""S8.3 模型探针的离线自测（0 次真实模型 / Tavily 调用）。

真实调用由 `evals/llm_probe.py` 单独执行；这里只锁死纯逻辑与护栏，
避免用「本地模拟的结果」冒充实测结论。
"""

from __future__ import annotations

import pytest

from capabilities.structured import ExtractionResult
from evals import llm_probe
from graph.contracts import Fact, SectionBrief

GOOD_URL = "https://example.org/notion/overview"


def _result(*, section: str = "company", degraded: bool = False, urls: list[str] | None = None):
    facts = [
        Fact(claim=f"结论 {i}", source_url=url, confidence=0.8)
        for i, url in enumerate(urls if urls is not None else [GOOD_URL])
    ]
    return ExtractionResult(
        brief=SectionBrief(
            section=section,  # type: ignore[arg-type]
            facts=facts,
            degraded=degraded,
            degrade_reason="查不到" if degraded else None,
        ),
        notes=[{"status": "ok", "attempt": 1}],
    )


def test_contract_ok_for_compliant_brief() -> None:
    r = llm_probe.describe_result(_result())
    assert r["contract_ok"] is True
    assert r["brief_type"] == "SectionBrief"
    assert r["facts_count"] == 1
    assert r["fact_fields"] == ["claim", "confidence", "source_url"]
    assert r["all_urls_in_allowed_set"] is True


@pytest.mark.parametrize(
    "kwargs, why",
    [
        ({"degraded": True}, "降级简报不能算契约通过"),
        ({"section": "news"}, "栏目不符不能算通过"),
        ({"urls": []}, "空 facts 不能算通过"),
        ({"urls": ["https://evil.example/hallucinated"]}, "编造来源必须被判失败"),
    ],
)
def test_contract_rejects_bad_briefs(kwargs: dict, why: str) -> None:
    assert llm_probe.describe_result(_result(**kwargs))["contract_ok"] is False, why


def test_tavily_guard_blocks_and_restores_original_method() -> None:
    from tavily import AsyncTavilyClient

    original = AsyncTavilyClient.search
    with llm_probe.tavily_guard() as calls:
        client = AsyncTavilyClient(api_key="not-a-real-key")
        with pytest.raises(AssertionError, match="禁止调用 Tavily"):
            client.search(query="anything")
        assert len(calls) == 1
    assert AsyncTavilyClient.search is original


def test_probe_refuses_to_start_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="缺少 DASHSCOPE_API_KEY"):
        llm_probe.build_report()


def test_live_env_pins_provider_and_model() -> None:
    assert llm_probe.LIVE_ENV["LLM_PROVIDER"] == "dashscope"
    assert llm_probe.LIVE_ENV["LLM_MODEL"] == "qwen-plus"
    assert llm_probe.LIVE_ENV["APP_MODE"] == "live"
    assert llm_probe.LIVE_ENV["LLM_BASE_URL"].startswith("https://")


def test_probe_documents_are_synthetic_and_local() -> None:
    assert llm_probe.DOCS
    assert all(d["url"].startswith("https://example.org/") for d in llm_probe.DOCS)
    assert all("合成" in d["title"] for d in llm_probe.DOCS)
