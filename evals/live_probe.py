"""S8.2：单次真实 Tavily 调用，核对 `search()` 返回结构与 Document 契约。

**额度约束（用户 2026-11-14 放行 2–20 credits）**：本脚本硬编码
`CallBudget(1)` + `RecordingClient` 双重保险，**最多 1 次真实请求**；
`search_depth=advanced` → 官方计费 2 credits。缓存落到被 gitignore 的
`evals/cache/tavily/`，之后同 query 复现不再扣额度。

安全：key 只从进程环境 `TAVILY_API_KEY` 读（运行时由 shell 注入，不落盘），
不打印、不写入产物、不提交。产物 `evals/live_probe.json` 只含**结构信息**
（字段名 / 类型 / 长度 / 分数分布 / URL 哈希），不含检索正文或完整 URL。

用法（PowerShell 里把用户变量映射成标准名后注入）：
    DASHSCOPE_API_KEY 等见 .env.example；Tavily 只需：
    $env:TAVILY_API_KEY = [Environment]::GetEnvironmentVariable('TAVILY_API_KEY','User')
    uv run python -m evals.live_probe
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from capabilities.retrieval import build_live_query, make_document_tool
from capabilities.tavily_retriever import CallBudget, documents_from_results
from config.loader import ROOT, load_settings

OUTPUT = ROOT / "evals" / "live_probe.json"
CACHE_DIR = ROOT / "evals" / "cache" / "tavily"
COMPANY = "Notion"
SECTION = "company"
MAX_REAL_CALLS = 1
CREDIT_SOURCE = "https://docs.tavily.com/documentation/api-credits"
# 官方只列了 basic=1 / advanced=2；其他 depth 不猜数字。
CREDITS_PER_SEARCH = {"basic": 1, "advanced": 2}

ENV = {
    "APP_MODE": "live",
    "TAVILY_LIVE_ENABLED": "true",
    "TAVILY_MAX_CALLS": str(MAX_REAL_CALLS),
    "TAVILY_DRY_RUN": "false",
    "TAVILY_CACHE_DIR": "./evals/cache/tavily",
    # 本探针只验检索层，不构造模型（FEATURES_STRUCTURED_OUTPUT=false）。
    "FEATURES_STRUCTURED_OUTPUT": "false",
}


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def describe_response(response: Any) -> dict[str, Any]:
    """只记录结构，不记录正文。用于验证 documents_from_results 的假设。"""
    if not isinstance(response, dict):
        return {
            "is_dict": False,
            "python_type": type(response).__name__,
            "top_level_keys": {},
            "results_count": 0,
            "results": [],
            "contract_ok": False,
        }
    top = {k: type(v).__name__ for k, v in response.items()}
    raw_results = response.get("results")
    items: list[dict[str, Any]] = []
    if isinstance(raw_results, list):
        for item in raw_results:
            if not isinstance(item, dict):
                items.append({"is_dict": False, "python_type": type(item).__name__})
                continue
            url = str(item.get("url") or "")
            content = item.get("content")
            items.append(
                {
                    "is_dict": True,
                    "keys": {k: type(v).__name__ for k, v in item.items()},
                    "has_url": bool(url),
                    "url_host": urlparse(url).netloc if url else "",
                    "url_sha256_12": _short_hash(url) if url else "",
                    "has_title": bool(item.get("title")),
                    "content_chars": len(content) if isinstance(content, str) else None,
                    "score": _jsonable(item.get("score")),
                    "extra_keys": sorted(
                        set(item) - {"url", "title", "content", "score"}
                    ),
                }
            )
    required = {"url", "title", "content", "score"}
    dict_items = [i for i in items if i.get("is_dict")]
    contract_ok = (
        "results" in response
        and isinstance(raw_results, list)
        and bool(dict_items)
        and all(required <= set(i["keys"]) for i in dict_items)
    )
    return {
        "is_dict": True,
        "top_level_keys": top,
        "results_is_list": isinstance(raw_results, list),
        "results_count": len(raw_results) if isinstance(raw_results, list) else None,
        "results": items,
        "other_top_level_fields": {
            k: (type(v).__name__, _jsonable(v) if not isinstance(v, (list, dict)) else None)
            for k, v in response.items()
            if k != "results"
        },
        "contract_ok": contract_ok,
        "contract_note": (
            "假设 response['results'] 是 list，且每条含 url/title/content/score"
        ),
    }


class RecordingClient:
    """包一层真实 SDK：既转发请求，又记录原始响应结构；硬拦第 2 次调用。"""

    def __init__(self, inner: Any):
        self.inner = inner
        self.call_count = 0
        self.request: dict[str, Any] = {}
        self.response_shape: dict[str, Any] = {}
        self.raw_results: Any = []

    async def search(self, **kwargs: Any) -> dict[str, Any]:
        self.call_count += 1
        if self.call_count > MAX_REAL_CALLS:
            raise AssertionError(
                f"S8.2 探针只允许 {MAX_REAL_CALLS} 次真实调用，检测到第 {self.call_count} 次"
            )
        self.request = {k: _jsonable(v) for k, v in kwargs.items() if k != "api_key"}
        response = await self.inner.search(**kwargs)
        self.response_shape = describe_response(response)
        self.raw_results = response.get("results", []) if isinstance(response, dict) else []
        return response


def build_probe() -> dict[str, Any]:
    key = (os.environ.get("TAVILY_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "S8.2 需要 TAVILY_API_KEY 在当前进程环境里（运行时注入，不落盘）；"
            "本脚本不会去注册表或用户变量里自行取 key"
        )

    settings = load_settings(environ=ENV)
    assert settings.app.mode == "live" and not settings.retrieval.live.dry_run
    assert settings.retrieval.live.max_calls_per_run == MAX_REAL_CALLS
    depth = settings.retrieval.search_depth
    per_call = CREDITS_PER_SEARCH.get(depth)

    from tavily import AsyncTavilyClient

    recorder = RecordingClient(AsyncTavilyClient(api_key=key))
    budget = CallBudget(MAX_REAL_CALLS, dry_run=False)
    tool = make_document_tool(
        settings, live_client=recorder, budget=budget, cache_dir=CACHE_DIR
    )
    query = build_live_query(COMPANY, SECTION, 0)

    async def run() -> tuple[dict[str, Any], dict[str, Any]]:
        first = await tool.ainvoke(
            {"company": COMPANY, "sections": [SECTION], "round_no": 0}
        )
        # 同一 query 立刻再跑一次：应命中磁盘缓存，不再发请求、不再扣额度。
        second = await tool.ainvoke(
            {"company": COMPANY, "sections": [SECTION], "round_no": 0}
        )
        return first, second

    first, second = asyncio.run(run())

    docs = documents_from_results(recorder.raw_results, section=SECTION)
    scores = [float(d.metadata.get("score", 0.0)) for d in docs]
    cache_files = sorted(p.name for p in CACHE_DIR.glob("*.json")) if CACHE_DIR.exists() else []

    return {
        "status": "ok",
        "purpose": "S8.2 单次真实调用，核对 search() 返回结构与 Document 契约",
        "company": COMPANY,
        "section": SECTION,
        "query": query,
        "request": recorder.request,
        "response_shape": recorder.response_shape,
        "document_contract": {
            "documents_from_results_count": len(docs),
            "metadata_keys": sorted(docs[0].metadata) if docs else [],
            "score_min": min(scores) if scores else None,
            "score_max": max(scores) if scores else None,
            "all_have_url": all(bool(d.metadata.get("url")) for d in docs),
        },
        "budget": {
            "max_calls": MAX_REAL_CALLS,
            "calls_made": budget.calls_made,
            "cache_hits": budget.cache_hits,
            "dry_runs": budget.dry_runs,
            "sdk_search_invocations": recorder.call_count,
            "queries": [dict(q) for q in budget.queries],
        },
        "cache": {
            "dir": "./evals/cache/tavily (gitignore，含真实响应，禁止提交)",
            "files": cache_files,
            "second_call_hit_cache": first == second,
            "note": "命中缓存不扣额度；后续同一 query 可离线复现",
        },
        "credits": {
            "depth": depth,
            "per_search_credits": per_call,
            "estimated_credits_used": per_call * budget.calls_made if per_call else None,
            "source": CREDIT_SOURCE,
            "unknown_reason": None if per_call else f"官方未列出 {depth} 的单价，拒绝猜测",
            "note": "官方计费规则推算，不是实测扣费账单",
        },
        "credentials": {
            "key_source": "process env TAVILY_API_KEY (injected at runtime)",
            "key_printed": False,
            "key_written_to_output": False,
        },
        "caveats": [
            "仅 1 次真实请求、1 家公司、1 个栏目，不能推断稳定性、p95 或平均成本",
            "本产物只含结构统计，不含检索正文或完整 URL",
            "未调用任何模型，不产出准确率 / 幻觉率数字",
        ],
    }


def main() -> int:
    try:
        report = build_probe()
    except Exception as exc:  # noqa: BLE001 - 失败也要如实留痕，不伪造成功
        report = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:300],
            "traceback_tail": traceback.format_exc(limit=3)[-600:],
            "note": "真实调用失败或护栏拦截；本次结果不作为结构验证结论",
        }
        OUTPUT.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[FAIL] {report['error_type']}: {report['error_message']}")
        return 1

    OUTPUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    shape = report["response_shape"]
    print(f"[OK] S8.2 单次真实调用完成，产物 {OUTPUT.relative_to(ROOT)}")
    print(
        f"  calls_made={report['budget']['calls_made']} "
        f"sdk_invocations={report['budget']['sdk_search_invocations']} "
        f"cache_hits={report['budget']['cache_hits']} "
        f"estimated_credits={report['credits']['estimated_credits_used']}"
    )
    print(
        f"  top_level_keys={list(shape['top_level_keys'])} "
        f"results={shape['results_count']} contract_ok={shape['contract_ok']}"
    )
    print(f"  documents={report['document_contract']['documents_from_results_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
