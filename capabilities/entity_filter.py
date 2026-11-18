"""新闻栏目：语义实体过滤——判断一篇文档讲的是不是这家公司。

为什么必须用语义判定而不是字面规则（`capabilities/entity_guard.py` 已论证）：
- `Notion Labs, Inc.` 就是 Notion 自己的注册实体，把带法域后缀的名字一律当异实体
  是**误杀**；
- `Sia Partners buys … Notion Consulting` 是另一家同名咨询公司，但它没有行情页
  特征，任何纯字面规则都抓不到。

真实事故（2026-11-18 live 报告）：上面那条收购新闻被当成 Notion（协作工具）的
动态写进了报告。

成本控制：一次调用判定整批文档，用 index 对齐；返回里缺的 index 一律按
`uncertain` 处理（保留，不删）。
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Literal, Protocol

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from config.loader import Settings

logger = logging.getLogger(__name__)

MAX_DOCS = 6
SNIPPET = 400

Verdict = Literal["same", "different", "uncertain"]


class _DocVerdict(BaseModel):
    index: int = Field(description="文档序号，从 1 开始")
    verdict: Verdict = Field(description="same=就是这家公司；different=另一家同名公司；uncertain=无法判断")
    reason: str = Field(default="", description="一句话理由")


class _BatchVerdict(BaseModel):
    verdicts: list[_DocVerdict] = Field(default_factory=list)


_SYSTEM = """你在核对一批检索文档，判断每篇讲的主体是不是「{company}」这家公司。

判定规则：
- same：文档主体就是 {company}（同一家公司，可能是不同语言/不同来源的报道）。
- different：文档主体是**另一家同名公司**（不同国家、不同行业、不同法域，
  例如某上市集团的子公司、某咨询公司、某期刊）。典型信号：出现与主业务无关的
  行业词、出现股票代码或"Berhad/Bhd/Pte"等法域后缀、出现收购/咨询/制造等业务。
- uncertain：信息不足以判断。

不确定时必须选 uncertain，不要为了给出结论而猜。
按文档序号（从 1 开始）逐条给出结论。"""


class JudgeFn(Protocol):
    async def __call__(
        self, company: str, docs: list[dict[str, Any]], settings: Settings
    ) -> dict[int, str]: ...


def _render_docs(docs: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for i, doc in enumerate(docs, start=1):
        title = str(doc.get("title") or "")[:200]
        content = str(doc.get("content") or "")[:SNIPPET]
        lines.append(f"[{i}] 标题：{title}\n正文：{content}")
    return "\n\n".join(lines)


async def judge_entities_batch(
    company: str, docs: list[dict[str, Any]], settings: Settings
) -> dict[int, str]:
    """一次调用判定整批文档主体。返回 {文档下标(0-based): verdict}。"""
    from capabilities.llm import make_chat_model

    if not docs:
        return {}

    model = make_chat_model(settings, "briefing")
    chain = (
        ChatPromptTemplate.from_messages(
            [("system", _SYSTEM), ("human", "{documents}")]
        )
        | model.with_structured_output(_BatchVerdict, method="function_calling")
    )
    out = await chain.ainvoke(
        {"company": company, "documents": _render_docs(docs)}
    )
    verdicts: dict[int, str] = {}
    for item in getattr(out, "verdicts", []) or []:
        idx = int(item.index) - 1
        if 0 <= idx < len(docs):
            verdicts[idx] = str(item.verdict)
    return verdicts


def make_filter_entity_node(
    section: str,
    settings: Settings,
    *,
    judge: Callable[..., Awaitable[dict[int, str]]] | None = None,
    max_docs: int = MAX_DOCS,
) -> Any:
    """语义实体过滤节点。

    只在 live 模式生效：fixture 的抽取后端是本地 mock，合成样本也没有同名实体，
    跑这一步既没有意义又会污染 baseline。fixture 下直接放行并留痕 `skipped`。
    `judge` 可注入，用于在 0 次真实调用下验证过滤逻辑。
    """
    active_judge = judge or judge_entities_batch

    async def filter_entity(state: dict[str, Any]) -> dict[str, Any]:
        docs = [dict(d) for d in (state.get("docs") or [])]
        notes = list(state.get("notes") or [])

        if judge is None and settings.app.mode != "live":
            notes.append(
                {"node": "filter_entity", "section": section,
                 "status": "skipped", "reason": "fixture_mode"}
            )
            return {"docs": docs, "notes": notes}

        if not docs:
            return {"docs": docs, "notes": notes}

        head = docs[:max_docs]
        try:
            verdicts = await active_judge(state["company"], head, settings)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s 实体过滤失败，全部放行：%s", section, exc)
            notes.append(
                {"node": "filter_entity", "section": section,
                 "status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
            )
            return {"docs": docs, "notes": notes}

        kept: list[dict[str, Any]] = []
        dropped: list[dict[str, Any]] = []
        uncertain: list[dict[str, Any]] = []
        for i, doc in enumerate(docs):
            verdict = verdicts.get(i, "uncertain")
            if verdict == "different":
                dropped.append({"url": str(doc.get("url") or ""), "verdict": verdict})
                continue
            if verdict == "uncertain":
                doc["entity_uncertain"] = True
                uncertain.append({"url": str(doc.get("url") or "")})
            kept.append(doc)

        notes.append(
            {
                "node": "filter_entity",
                "section": section,
                "status": "ok",
                "judged": len(head),
                "kept": len(kept),
                "dropped": dropped,
                "uncertain": uncertain,
            }
        )
        return {"docs": kept, "notes": notes}

    return filter_entity
