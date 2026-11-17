"""R3：栏目内真实 LLM 抽取节点工厂 + 三级降级链。

降级链（用户 D5 决策）：
  ① 真实 LLM（DashScope / qwen-plus，with_structured_output）
  ② 本地小模型接口（预留，当前为空位——后续用户接入）
  ③ 规则抽取（把文档 content 逐条转成 Fact）+ review_notes 留痕降级原因

四栏目 extract 统一用 SectionBrief 契约（用户 2026-11-17 确认），
FundingRound 等专用结构留到 R4 由规则从 facts 派生。

测试路径：注入 mock model（MockTransport）→ 走 ① 但不联网、不烧额度。
"""

from __future__ import annotations

import logging
from typing import Any

from config.loader import Settings
from capabilities.briefing import make_briefing_backend
from capabilities.structured import ExtractionResult, extract_section_brief
from graph.contracts import Fact, SectionBrief

logger = logging.getLogger(__name__)


def _rule_extract(company: str, section: str, docs: list[dict[str, Any]]) -> ExtractionResult:
    """③ 规则降级：文档 content 逐条转 Fact，带 source_url。0 模型 0 网络。"""
    facts: list[Fact] = []
    for doc in docs:
        if doc.get("url") and doc.get("content"):
            try:
                facts.append(
                    Fact(
                        claim=str(doc["content"]),
                        source_url=doc["url"],
                        confidence=float(doc.get("score", 0.0) or 0.0),
                    )
                )
            except (ValueError, TypeError):
                continue
    return ExtractionResult(
        brief=SectionBrief(section=section, facts=facts),  # type: ignore[arg-type]
        notes=[
            {
                "node": "extract",
                "section": section,
                "status": "rule_fallback",
                "reason": "llm_and_local_model_unavailable",
                "facts": len(facts),
            }
        ],
    )


def make_extract_node(
    settings: Settings,
    section: str,
    *,
    backend: Any | None = None,
) -> Any:
    """返回栏目内 extract 节点（真实 LLM，失败走三级降级）。

    `backend` 可注入（测试用 mock，生产用真实 DashScope）；不传则按 settings 构造。
    """
    async def extract(state: dict[str, Any]) -> dict[str, Any]:
        company = state["company"]
        docs = list(state.get("docs", []))
        section_state = state.get("active_section", section)

        if not docs:
            return {
                "facts": [],
                "review_notes": [
                    {"node": "extract", "section": section_state, "status": "no_docs"}
                ],
            }

        # ① 真实 LLM（或注入的 mock）
        current_backend = backend if backend is not None else make_briefing_backend(settings)
        try:
            result = await extract_section_brief(
                current_backend.chain,
                section=section_state,  # type: ignore[arg-type]
                company=company,
                docs=docs,
                settings=settings,
            )
            if result.brief.facts:
                return {
                    "facts": [f.model_dump(mode="json") for f in result.brief.facts],
                    "review_notes": [
                        {
                            "node": "extract",
                            "section": section_state,
                            "status": "llm",
                            "provider": current_backend.mode,
                            "facts": len(result.brief.facts),
                        }
                    ],
                }
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s LLM 抽取失败，尝试降级：%s", section_state, exc)
        finally:
            # 自建 backend 才由本节点关闭；注入的 backend 由调用方管理生命周期
            if backend is None:
                await current_backend.aclose()

        # ② 本地小模型接口（预留空位，当前直接落到 ③）
        # TODO(用户)：接入本地小模型后，在这里加 extractor 调用

        # ③ 规则抽取
        result = _rule_extract(company, section_state, docs)
        return {
            "facts": [f.model_dump(mode="json") for f in result.brief.facts],
            "review_notes": result.notes,
        }

    return extract
