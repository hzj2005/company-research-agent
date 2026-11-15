"""S5 结构化抽取链：LCEL + `with_structured_output` + 校验重试 + URL 级回溯。

    ChatPromptTemplate | model.with_structured_output(SectionBrief)

三条红线（对应 AGENT.md 与 PROJECT_PLAN 5.1）：
1. 禁止裸 `json.loads` 当结构化输出；解析交给 Pydantic。
2. 校验失败重试 `models.max_retries` 次，仍失败 → 整栏 `degraded=True` 且写
   `review_notes`，**绝不静默丢字段**或拿自由文本凑数。
3. 每条 Fact 的 `source_url` 必须出现在本次传入的文档 URL 集合里，否则剔除并
   留痕。这只做到 URL 级回溯，不等于「来源内容确实支持结论」（归 S7）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_core.exceptions import OutputParserException
from pydantic import ValidationError

from config.loader import Settings
from graph.contracts import Fact, SectionBrief
from graph.state import Section

_SYSTEM_PROMPT = """你是公司调研资料抽取器，只处理 <documents> 里给出的来源。

语言要求：
- **所有 claim 一律用简体中文书写**，即使来源整篇是英文。公司名、产品名、技术/财务术语
  保留英文原名，首次出现时可在括号里补中文说明，例如 "NVIDIA H100（数据中心 GPU）"。
- 数字、金额、日期、比例、人名、型号必须原样保留，不要改写成"大幅增长""多款产品"这类模糊说法。

规则：
- 每条事实必须带且仅带一个 source_url，必须是给定文档里出现过的 URL，不要编造。
- 只使用文档内容，不得引入外部知识；文档没写的内容不要写。
- **不要把多个独立事实合并成一句**：不同时间、不同数字、不同主体的信息分别写成独立条目，
  这样读者才能逐条核对。同一文档里能抽出的独立事实不要遗漏。
- confidence 取 0~1，表示你对该事实被来源直接支持的把握。
- 若文档不足以产生任何有依据的事实，返回空 facts，并置 degraded=true、
  degrade_reason 写明原因。查不到就如实说查不到，禁止编造。
- 输出必须符合 SectionBrief schema；section 字段必须等于给定的栏目名。

最后再强调一次语言：**即使来源整篇是英文，claim 也必须写成简体中文**。
"""

# ValidationError / OutputParserException 都是 ValueError 子类；捕获它们但
# 不吞掉网络异常（httpx.HTTPError 不是 ValueError），网络故障应直接暴露。
_PARSE_ERRORS = (ValidationError, OutputParserException, ValueError, TypeError)


@dataclass(frozen=True)
class ExtractionResult:
    brief: SectionBrief
    notes: list[dict[str, Any]] = field(default_factory=list)


def make_extraction_chain(model: BaseChatModel) -> Runnable:
    """LCEL：prompt | with_structured_output(SectionBrief)。"""
    prompt = ChatPromptTemplate.from_messages(
        [("system", _SYSTEM_PROMPT), ("human", "{payload}")]
    )
    return prompt | model.with_structured_output(SectionBrief, method="function_calling")


def _norm_url(value: Any) -> str:
    """HttpUrl 会给裸域名补尾斜杠，比对前统一去掉，避免误判为外部来源。"""
    return str(value).rstrip("/")


def _format_payload(company: str, section: Section, docs: Iterable[Mapping[str, Any]]) -> str:
    lines = [
        f"company: {company}",
        f"section: {section}",
        # 混在长英文文档里的一句语言要求，比只写在 system prompt 里有效
        "output_language: 简体中文（claim 必须用中文写，专有名词与数字保留原文）",
        "<documents>",
    ]
    for doc in docs:
        lines.append(
            json.dumps(
                {
                    "url": doc.get("url", ""),
                    "title": doc.get("title", ""),
                    "content": doc.get("content", ""),
                    # 供 fixture stub 回显为 Fact.confidence（不伪造高置信度）
                    "score": doc.get("score", 0.0),
                },
                ensure_ascii=False,
            )
        )
    lines.append("</documents>")
    return "\n".join(lines)


def _note(section: Section, attempt: int, status: str, **extra: Any) -> dict[str, Any]:
    return {
        "node": "structured_extract",
        "section": section,
        "attempt": attempt,
        "status": status,
        **extra,
    }


async def extract_section_brief(
    chain: Runnable,
    *,
    section: Section,
    company: str,
    docs: list[Mapping[str, Any]],
    settings: Settings,
) -> ExtractionResult:
    """抽取一个栏目的结构化简报；失败重试，耗尽则整栏降级并留痕。"""
    notes: list[dict[str, Any]] = []
    allowed = {_norm_url(d.get("url", "")) for d in docs if d.get("url")}
    if not docs or not allowed:
        reason = "本栏目没有可用文档"
        notes.append(_note(section, 0, "degraded", reason=reason))
        return ExtractionResult(
            SectionBrief(section=section, facts=[], degraded=True, degrade_reason=reason),
            notes,
        )

    payload = _format_payload(company, section, docs)
    attempts = settings.models.max_retries + 1
    last_error = ""

    for attempt in range(1, attempts + 1):
        try:
            brief = await chain.ainvoke({"payload": payload})
            if not isinstance(brief, SectionBrief):
                raise TypeError(f"抽取结果类型异常：{type(brief).__name__}")
            if brief.section != section:
                raise ValueError(
                    f"模型返回栏目 {brief.section!r}，期望 {section!r}"
                )
        except _PARSE_ERRORS as exc:
            last_error = f"{type(exc).__name__}: {exc}"[:300]
            notes.append(_note(section, attempt, "validation_failed", error=last_error))
            continue

        # URL 级回溯：不在本次文档集合里的来源一律剔除，且必须留下痕迹
        kept: list[Fact] = []
        dropped: list[str] = []
        for fact in brief.facts:
            if _norm_url(fact.source_url) in allowed:
                kept.append(fact)
            else:
                dropped.append(str(fact.source_url))
        if dropped:
            notes.append(
                _note(section, attempt, "dropped_uncited_facts", urls=dropped)
            )
        if not kept:
            reason = "所有事实都缺少可回溯来源"
            notes.append(_note(section, attempt, "degraded", reason=reason))
            return ExtractionResult(
                SectionBrief(
                    section=section,
                    facts=[],
                    degraded=True,
                    degrade_reason=reason,
                ),
                notes,
            )

        notes.append(_note(section, attempt, "ok", facts=len(kept)))
        return ExtractionResult(brief.model_copy(update={"facts": kept}), notes)

    reason = f"结构化输出校验失败 {attempts} 次：{last_error}"[:300]
    notes.append(_note(section, attempts, "degraded", reason=reason))
    return ExtractionResult(
        SectionBrief(section=section, facts=[], degraded=True, degrade_reason=reason),
        notes,
    )
