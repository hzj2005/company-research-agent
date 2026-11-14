"""S8.2 探针自身的离线验证：0 次真实调用、0 次外部连接。

用假 SDK 替身跑完整 `build_probe()`，在花钱之前确认：
预算只有 1 次、第 2 次被拦、缓存能防重复扣费、密钥不进产物、
结构判定不会把「缺字段的响应」误判为通过。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import evals.live_probe as probe

FAKE_KEY = "sk-should-never-appear-in-output"
FAKE_BODY = "UNIQUE_SENTINEL_SHOULD_NOT_BE_PERSISTED"

FAKE_RESPONSE: dict[str, Any] = {
    "query": "Notion company overview background products",
    "response_time": 1.23,
    "results": [
        {
            "url": "https://www.notion.com/about",
            "title": "About Notion",
            "content": FAKE_BODY,
            "score": 0.91,
            "raw_content": None,
        },
        {
            "url": "https://en.wikipedia.org/wiki/Notion_(productivity_software)",
            "title": "Notion - Wikipedia",
            "content": "another body",
            "score": 0.77,
        },
    ],
}


class FakeSDK:
    """记录 api_key 但绝不发请求；search 返回固定真实形状。"""

    instances: list["FakeSDK"] = []

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.search_count = 0
        FakeSDK.instances.append(self)

    async def search(self, **kwargs: Any) -> dict[str, Any]:
        self.search_count += 1
        return FAKE_RESPONSE


@pytest.fixture
def offline_probe(monkeypatch, tmp_path):
    """把 SDK 与缓存目录全部替换成本地替身，并注入假 key。"""
    FakeSDK.instances = []
    monkeypatch.setenv("TAVILY_API_KEY", FAKE_KEY)
    monkeypatch.setattr("tavily.AsyncTavilyClient", FakeSDK)
    monkeypatch.setattr(probe, "CACHE_DIR", tmp_path / "cache")
    return tmp_path


def test_describe_response_accepts_full_contract() -> None:
    shape = probe.describe_response(FAKE_RESPONSE)
    assert shape["is_dict"] is True
    assert shape["results_is_list"] is True
    assert shape["results_count"] == 2
    assert shape["contract_ok"] is True
    assert set(shape["top_level_keys"]) == {"query", "response_time", "results"}
    assert shape["results"][0]["extra_keys"] == ["raw_content"]


def test_describe_response_rejects_missing_results_key() -> None:
    shape = probe.describe_response({"answer": "no results here"})
    assert shape["contract_ok"] is False
    assert shape["results_is_list"] is False
    assert shape["results_count"] is None, "没有 results 键时不能谎报 0 条结果"


def test_describe_response_rejects_non_dict_and_missing_fields() -> None:
    assert probe.describe_response(["not", "a", "dict"])["contract_ok"] is False
    shape = probe.describe_response(
        {"results": [{"url": "https://x.test", "content": "no score/title"}]}
    )
    assert shape["contract_ok"] is False, "缺 title/score 不能算契约通过"


def test_describe_response_never_persists_body_text() -> None:
    serialized = json.dumps(probe.describe_response(FAKE_RESPONSE), ensure_ascii=False)
    assert FAKE_BODY not in serialized
    assert "https://www.notion.com/about" not in serialized
    assert "www.notion.com" in serialized, "只保留域名与哈希用于核对"


def test_recording_client_hard_blocks_second_real_call() -> None:
    sdk = FakeSDK(api_key=FAKE_KEY)
    recorder = probe.RecordingClient(sdk)
    import asyncio

    assert asyncio.run(recorder.search(query="one")) is FAKE_RESPONSE
    with pytest.raises(AssertionError, match="只允许 1 次真实调用"):
        asyncio.run(recorder.search(query="two"))
    assert sdk.search_count == 1


def test_build_probe_without_key_refuses_before_any_sdk_construction(monkeypatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    FakeSDK.instances = []
    monkeypatch.setattr("tavily.AsyncTavilyClient", FakeSDK)
    with pytest.raises(RuntimeError, match="不会去注册表或用户变量里自行取 key"):
        probe.build_probe()
    assert FakeSDK.instances == [], "无 key 时绝不能构造 SDK"


def test_full_probe_offline_budget_and_no_secret_leak(offline_probe) -> None:
    """完整跑一次探针逻辑（假 SDK）：验证 1 次调用 + 缓存复用 + 脱敏。"""
    report = probe.build_probe()
    assert report["status"] == "ok"
    assert report["budget"]["calls_made"] == 1
    assert report["budget"]["sdk_search_invocations"] == 1
    assert report["budget"]["cache_hits"] == 1, "第二次调用必须命中缓存，不重复扣费"
    assert report["budget"]["max_calls"] == 1
    assert report["cache"]["second_call_hit_cache"] is True
    assert report["response_shape"]["contract_ok"] is True
    assert report["document_contract"]["documents_from_results_count"] == 2
    assert report["document_contract"]["all_have_url"] is True
    assert report["credits"]["estimated_credits_used"] == 2
    assert FAKE_KEY not in json.dumps(report, ensure_ascii=False)
    assert FAKE_BODY not in json.dumps(report, ensure_ascii=False)
    assert FakeSDK.instances[0].search_count == 1


def test_credit_table_does_not_invent_prices() -> None:
    assert probe.CREDITS_PER_SEARCH == {"basic": 1, "advanced": 2}
    assert probe.MAX_REAL_CALLS == 1
    assert probe.ENV["TAVILY_DRY_RUN"] == "false"
    assert probe.ENV["FEATURES_STRUCTURED_OUTPUT"] == "false"
