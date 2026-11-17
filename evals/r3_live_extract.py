"""R3-live：真实 LLM 最小实跑 —— 四栏目各 1 次，验证新架构抽取链路。

与 llm_probe.py（单次、旧路径）的区别：
本脚本走**新架构真实路径** `extract_with_fallback`（共享三级链 + 各栏目 prompt），
即 R3 重构后生产代码实际调用的函数。四栏目各跑 1 次，共 **4 次 LLM 请求**。

额度护栏：
- 硬编码 max_retries=0（关闭重试），每栏目恰好 1 次请求，总计 4 次；
- Tavily 装哨兵，0 次检索；
- key 只从进程环境读（SYSTEM_ALIYUN_APIKEY / DASHSCOPE_API_KEY），不落盘不打印；
- 产物 evals/r3_live_extract.json 只写结构统计，不写密钥/完整正文。

用法：
    .venv/Scripts/python.exe -m evals.r3_live_extract
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator

from langchain_community.callbacks import get_openai_callback

from config.loader import ROOT, apply_overrides, load_settings, resolve_llm_credentials
from graph.agents.extract import extract_with_fallback

OUTPUT = ROOT / "evals" / "r3_live_extract.json"

LIVE_ENV: dict[str, str] = {
    "APP_MODE": "live",
    "LLM_PROVIDER": "dashscope",
    "LLM_MODEL": "qwen-plus",
    "LLM_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}

# 四栏目各自的样例文档（合成，覆盖本栏目 prompt 关注的点）
SECTION_DOCS: dict[str, list[dict[str, Any]]] = {
    "company": [
        {"url": "https://example.org/notion/overview", "title": "概览（合成）",
         "content": "Notion 提供笔记与协作工作区，团队位于 San Francisco，成立于 2013 年。",
         "score": 0.92},
    ],
    "industry": [
        {"url": "https://example.org/market/size", "title": "市场（合成）",
         "content": "Gartner 口径下协作文档市场规模 50 亿美元，同比增长 20%。",
         "score": 0.9},
    ],
    "financial": [
        {"url": "https://example.org/finance/round", "title": "融资（合成）",
         "content": "2021 年完成 A 轮融资 500 万美元，投资方为 Sequoia。",
         "score": 0.88},
    ],
    "news": [
        {"url": "https://example.org/news/launch", "title": "新闻（合成）",
         "content": "2024 年 5 月 Notion 推出 AI 写作功能。",
         "score": 0.85},
    ],
}
ADDENDA: dict[str, str] = {
    "company": "只抽公司自身的结构性事实；不要抽股价、市值、融资轮次。",
    "industry": "市场数字要连同口径一起抽；不同机构数字各自成条。",
    "financial": "金额、轮次、年份、投资方逐字保留；不同轮次是时间序列。",
    "news": "每条事实尽量带出发生时间；只写文档明确出现的。",
}


@contextmanager
def tavily_guard() -> Iterator[list[int]]:
    calls: list[int] = []
    try:
        from tavily import AsyncTavilyClient
    except ImportError:
        yield calls
        return
    original = AsyncTavilyClient.search

    def _sentinel(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        raise AssertionError("R3-live 探针禁止调用 Tavily 检索")

    AsyncTavilyClient.search = _sentinel  # type: ignore[assignment]
    try:
        yield calls
    finally:
        AsyncTavilyClient.search = original  # type: ignore[assignment]


def build_report() -> dict[str, Any]:
    key = (
        os.environ.get("DASHSCOPE_API_KEY", "").strip()
        or os.environ.get("SYSTEM_ALIYUN_APIKEY", "").strip()
    )
    if not key:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY / SYSTEM_ALIYUN_APIKEY")

    env = {**LIVE_ENV, "DASHSCOPE_API_KEY": key}
    settings = load_settings(environ=env)
    if settings.models.roles["briefing"] != "qwen-plus":
        raise RuntimeError(f"模型未锁定：{settings.models.roles['briefing']!r}")
    creds = resolve_llm_credentials(environ=env)
    if creds.provider != "dashscope":
        raise RuntimeError(f"provider 未锁定：{creds.provider!r}")
    # 关闭重试：每栏目恰好 1 次请求，四栏目共 4 次
    probe_settings = apply_overrides(settings, {"models.max_retries": 0})

    results: dict[str, Any] = {}
    total_requests = 0
    started_all = time.perf_counter()
    with tavily_guard() as tavily_calls:
        for section, docs in SECTION_DOCS.items():
            item: dict[str, Any] = {}
            started = time.perf_counter()
            try:
                with get_openai_callback() as cb:
                    facts, status, notes = asyncio.run(
                        extract_with_fallback(
                            "Notion", section, docs, probe_settings,
                            addendum=ADDENDA[section],
                        )
                    )
                total_requests += cb.successful_requests
                allowed = {d["url"].rstrip("/") for d in docs}
                item = {
                    "status": "ok",
                    "extract_status": status,
                    "facts_count": len(facts),
                    "fact_fields": sorted(facts[0].keys()) if facts else [],
                    "all_urls_in_allowed_set": all(
                        str(f.get("source_url", "")).rstrip("/") in allowed for f in facts
                    ),
                    "notes": [{"status": n.get("status"), "prompt": n.get("prompt")}
                              for n in notes],
                    "sample_claim": facts[0]["claim"][:60] if facts else None,
                    "requests": cb.successful_requests,
                    "total_tokens": cb.total_tokens,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            except Exception as exc:  # 真实故障如实落盘
                item = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
            results[section] = item

    elapsed_all = round((time.perf_counter() - started_all) * 1000, 1)
    all_ok = all(r.get("status") == "ok" for r in results.values())
    report: dict[str, Any] = {
        "purpose": "R3-live：新架构 extract_with_fallback 四栏目真实 LLM 抽取（各 1 次）",
        "status": "ok" if all_ok and total_requests == 4 else "partial_or_failed",
        "config": {
            "app_mode": probe_settings.app.mode,
            "provider": creds.provider,
            "model": probe_settings.models.roles["briefing"],
            "base_url": creds.base_url,
            "max_retries": 0,
        },
        "guard": {
            "llm_requests_total": total_requests,
            "expected_llm_requests": 4,
            "tavily_calls": len(tavily_calls),
        },
        "results": results,
        "elapsed_ms_total": elapsed_all,
        "note": "qwen-plus 单价不在 get_openai_callback 价目表，不套用/不编造成本数字",
    }
    return report


def main() -> int:
    report = build_report()
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[R3-live] status={report['status']} -> {OUTPUT.name}")
    for section, r in report["results"].items():
        if r.get("status") == "ok":
            print(f"  {section}: facts={r['facts_count']} urls_ok={r['all_urls_in_allowed_set']} "
                  f"req={r['requests']} tokens={r['total_tokens']}")
        else:
            print(f"  {section}: FAILED {r.get('error', '')[:80]}")
    print(f"  LLM requests: {report['guard']['llm_requests_total']}/4, "
          f"Tavily calls: {report['guard']['tavily_calls']}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
