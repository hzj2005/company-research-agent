"""S8.3 最小真实模型探针：验证 DashScope + qwen-plus 的结构化输出契约。

只做一件事：用生产代码路径跑一次 `extract_section_brief`。
- 不构造任何检索工具，并给 `AsyncTavilyClient.search` 装哨兵，证明 0 次 Tavily 调用；
- 关闭重试（生产配置保留 1 次重试），把模型请求硬锁定在 **1 次**；
- 只写结构统计与 token 计数，不写密钥、不写文档正文、不写完整 URL 参数。

从 S5-B 起 `search()` 真实返回结构一直标「未实测」，本文件专管**模型侧**的同类未知：
`with_structured_output(method="function_calling")` 在百炼 OpenAI 兼容端点上到底能不能返回
符合 `SectionBrief` 契约的 Pydantic 对象。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator

from langchain_community.callbacks import get_openai_callback

from capabilities.llm import make_chat_model
from capabilities.structured import extract_section_brief, make_extraction_chain
from config.loader import ROOT, apply_overrides, load_settings, resolve_llm_credentials

OUTPUT = ROOT / "evals" / "llm_probe.json"

# 模型名必须显式锁定：settings.yaml 的默认值是上游的 google/gemini-3.8-flash，
# 直接拿去打 DashScope 必然失败。
LIVE_ENV: dict[str, str] = {
    "APP_MODE": "live",
    "LLM_PROVIDER": "dashscope",
    "LLM_MODEL": "qwen-plus",
    "LLM_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}

DOCS: list[dict[str, Any]] = [
    {
        "url": "https://example.org/notion/overview",
        "title": "Notion 产品概览（合成）",
        "content": (
            "Notion 提供笔记、文档与协作工作区，目标客户为团队与个人知识工作者。"
            "Notion 团队位于 San Francisco。"
        ),
        "score": 0.92,
    },
    {
        "url": "https://example.org/notion/pricing",
        "title": "Notion 定价页（合成）",
        "content": "Notion 采用订阅制，包含免费版与付费版，收入以按席位订阅为主。",
        "score": 0.88,
    },
]


def describe_result(result: Any) -> dict[str, Any]:
    brief = result.brief
    allowed = {str(d["url"]).rstrip("/") for d in DOCS}
    return {
        "brief_type": type(brief).__name__,
        "section": brief.section,
        "degraded": brief.degraded,
        "degrade_reason": brief.degrade_reason,
        "facts_count": len(brief.facts),
        "fact_fields": sorted(type(brief.facts[0]).model_fields) if brief.facts else [],
        "all_urls_in_allowed_set": all(
            str(f.source_url).rstrip("/") in allowed for f in brief.facts
        ),
        "confidence_range": (
            [min(f.confidence for f in brief.facts), max(f.confidence for f in brief.facts)]
            if brief.facts
            else None
        ),
        "notes": [{"status": n.get("status"), "attempt": n.get("attempt")} for n in result.notes],
        "contract_ok": (
            type(brief).__name__ == "SectionBrief"
            and brief.section == "company"
            and not brief.degraded
            and len(brief.facts) > 0
            and all(str(f.source_url).rstrip("/") in allowed for f in brief.facts)
        ),
    }


@contextmanager
def tavily_guard() -> Iterator[list[int]]:
    """本探针不允许检索；被调用即抛错，退出时还原原方法，不污染同进程后续调用。"""
    calls: list[int] = []
    try:
        from tavily import AsyncTavilyClient
    except ImportError:
        yield calls
        return

    original = AsyncTavilyClient.search

    def _sentinel(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        raise AssertionError("LLM 探针禁止调用 Tavily 检索")

    AsyncTavilyClient.search = _sentinel  # type: ignore[assignment]
    try:
        yield calls
    finally:
        AsyncTavilyClient.search = original  # type: ignore[assignment]


def build_report() -> dict[str, Any]:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "缺少 DASHSCOPE_API_KEY。请从 Windows 用户级变量 SYSTEM_ALIYUN_APIKEY "
            "映射到本进程内存后运行，不要把密钥写进 .env 或命令行参数。"
        )
    env = {**LIVE_ENV, "DASHSCOPE_API_KEY": key}
    settings = load_settings(environ=env)
    if settings.models.roles["briefing"] != "qwen-plus":
        raise RuntimeError(
            f"模型名未锁定：briefing={settings.models.roles['briefing']!r}，"
            "拒绝用非百炼模型名发起真实调用（会白烧一次请求）"
        )
    creds = resolve_llm_credentials(environ=env)
    if creds.provider != "dashscope":
        raise RuntimeError(f"provider 未锁定：{creds.provider!r}")

    # 探针关闭重试：生产 settings 的 max_retries=1，这里硬锁定 1 次模型请求。
    probe_settings = apply_overrides(settings, {"models.max_retries": 0})

    model = make_chat_model(probe_settings, "briefing", credentials=creds)
    chain = make_extraction_chain(model)

    started = time.perf_counter()
    error: str | None = None
    result: Any = None
    usage: dict[str, Any] = {}
    with tavily_guard() as tavily_calls:
        try:
            with get_openai_callback() as cb:
                result = asyncio.run(
                    extract_section_brief(
                        chain,
                        section="company",
                        company="Notion",
                        docs=DOCS,
                        settings=probe_settings,
                    )
                )
            usage = {
                "successful_requests": cb.successful_requests,
                "total_tokens": cb.total_tokens,
                "prompt_tokens": cb.prompt_tokens,
                "completion_tokens": cb.completion_tokens,
                "total_cost_usd": None,
                "cost_note": (
                    "get_openai_callback 的价目表只覆盖 OpenAI 官方模型；"
                    "qwen-plus 单价不在此表内，故不套用、不编造成本数字"
                ),
            }
        except Exception as exc:  # 真实故障必须如实落盘，不能吞
            error = f"{type(exc).__name__}: {str(exc)[:400]}"
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    tavily_call_count = len(tavily_calls)

    report: dict[str, Any] = {
        "purpose": "S8.3 最小真实模型调用：核对 with_structured_output 在百炼端点的兼容性",
        "status": "ok" if error is None and result is not None else "failed",
        "error": error,
        "config": {
            "app_mode": probe_settings.app.mode,
            "provider": creds.provider,
            "model": probe_settings.models.roles["briefing"],
            "base_url": creds.base_url,
            "temperature": probe_settings.models.temperature,
            "max_retries_in_probe": 0,
            "max_retries_in_production": settings.models.max_retries,
            "structured_output_method": "function_calling",
        },
        "result": describe_result(result) if result is not None else None,
        "usage": usage,
        "elapsed_ms": elapsed_ms,
        "elapsed_note": "本机墙钟，非确定性字段，不参与 CI 比对",
        "isolation": {
            "tavily_client_search_calls": tavily_call_count,
            "document_tool_constructed": False,
            "llm_requests_cap": 1,
            "llm_requests_cap_note": "探针把 max_retries 置 0；若模型返回不合规，链内不会重试",
        },
        "credentials": {
            "api_key_env_var": "DASHSCOPE_API_KEY",
            "api_key_characters": len(key),
            "api_key_printed": 0,
            "api_key_in_artifact": False,
            "note": "key 仅存在于本进程内存；产物不写值、不写 .env、不进 git",
        },
    }
    if error and key in error:
        report["error"] = "错误信息中疑似含密钥，已整体屏蔽"
        report["credentials"]["api_key_in_artifact"] = True
    return report


def main() -> int:
    report = build_report()
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[S8.3 LLM probe] status={report['status']} -> {OUTPUT.relative_to(ROOT)}")
    print(f"  model={report['config']['model']} provider={report['config']['provider']}")
    if report["result"]:
        r = report["result"]
        print(
            f"  contract_ok={r['contract_ok']} facts={r['facts_count']} "
            f"urls_ok={r['all_urls_in_allowed_set']} degraded={r['degraded']}"
        )
    if report["error"]:
        print(f"  error={report['error'][:200]}")
    print(f"  usage={report['usage'].get('total_tokens', 'n/a')} tokens; tavily_calls=0")
    return 0 if report["status"] == "ok" and report["result"]["contract_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
