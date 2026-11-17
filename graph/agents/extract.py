"""R3 共享抽取执行器：三级降级链，四栏目各自传 prompt 调用。

降级链（用户 D5 决策）：
  ① 真实 LLM（DashScope / qwen-plus，with_structured_output）
  ② 本地小模型接口（预留空位 LocalModelExtractor —— 后续用户接入）
  ③ 规则抽取（文档 content 逐条转 Fact，0 模型 0 网络）+ review_notes 留痕

四栏目 extract 统一用 SectionBrief 契约（用户 2026-11-17 确认）；
每栏目的 prompt 由 prompts.py 的 ADDENDUM 提供，经 build_section_prompt 拼通用规则。

设计：本模块只做编排，不定义栏目差异；四个 nodes.py 只声明自己的 addendum
并调用本函数，避免四份重复的降级代码（R4 加差异化节点时只改一处）。

返回签名与 pipeline 的 ExtractFn 一致：(facts, status, notes)。
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from config.loader import Settings
from capabilities.briefing import make_briefing_backend
from capabilities.structured import extract_section_brief
from graph.agents.prompts import build_section_prompt
from graph.contracts import SectionBrief

logger = logging.getLogger(__name__)


class LocalModelExtractor(Protocol):
    """② 本地小模型接口（预留空位）。

    接入方实现 `__call__(company, section, docs) -> SectionBrief` 即可，
    在 `extract_with_fallback` 的 ② 处注入。当前默认 None（直接落到 ③）。
    """

    async def __call__(
        self, company: str, section: str, docs: list[dict[str, Any]]
    ) -> SectionBrief: ...


def _rule_extract(section: str, docs: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """③ 规则降级：文档逐条转 Fact，带 source_url。0 模型 0 网络。"""
    facts = [
        {
            "claim": str(d["content"]),
            "source_url": d["url"],
            "confidence": float(d.get("score", 0) or 0),
        }
        for d in docs
        if d.get("url") and d.get("content")
    ]
    return facts, [
        {
            "node": "extract", "section": section, "status": "rule_fallback",
            "reason": "llm_and_local_model_unavailable", "facts": len(facts),
        }
    ]


async def extract_with_fallback(
    company: str,
    section: str,
    docs: list[dict[str, Any]],
    settings: Settings,
    *,
    addendum: str,
    local_model: LocalModelExtractor | None = None,
) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    """栏目抽取：① LLM → ② 本地小模型(预留) → ③ 规则。

    `addendum` 是本栏目 prompts.py 里的专属要求；`local_model` 为 ② 的注入点，
    当前默认 None（用户接入本地模型后传入实现即可，无需改四栏目代码）。
    """
    if not docs:
        return [], "ok", [{"node": "extract", "section": section, "status": "no_docs"}]

    # ① 真实 LLM（注入本栏目 prompt）
    backend = make_briefing_backend(
        settings, system_prompt=build_section_prompt(addendum)
    )
    try:
        result = await extract_section_brief(
            backend.chain, section=section, company=company, docs=docs, settings=settings
        )
        if result.brief.facts:
            return (
                [f.model_dump(mode="json") for f in result.brief.facts],
                "ok",
                [{"node": "extract", "section": section, "status": "llm",
                  "facts": len(result.brief.facts), "prompt": section}],
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s LLM 抽取失败，尝试降级：%s", section, exc)
    finally:
        await backend.aclose()

    # ② 本地小模型接口（预留：注入 local_model 后走这里，当前为 None）
    if local_model is not None:
        try:
            brief = await local_model(company, section, docs)
            if brief.facts:
                return (
                    [f.model_dump(mode="json") for f in brief.facts],
                    "ok",
                    [{"node": "extract", "section": section, "status": "local_model",
                      "facts": len(brief.facts)}],
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s 本地小模型抽取失败，降级规则：%s", section, exc)

    # ③ 规则抽取
    facts, notes = _rule_extract(section, docs)
    return facts, "no_retry", notes
