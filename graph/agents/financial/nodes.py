"""Financial 专职 Agent 节点（V2 S4）。

相对原 `make_analyst_node` 的差异：**两道实体门前置**——
1. 单篇标题级 `ticker_binding`（挡 `公司名 + 法域后缀 + (股票代码)` 行情页）；
2. 跨文档 `find_incoherent`（官网域名无交集且成立年份少数派）。

拆两道而非直接调 `filter_docs`，是因为 `filter_docs` 内部已含单篇判定
（entity_guard.py:275），会把 ticker_binding 跑两次。这里用 `judge` + `find_incoherent`
精确分工：第一道逐篇 judge（只取 ticker_binding 类），第二道只做跨文档一致性。
全灭护栏沿用 filter_docs 的语义：全被拒则全部放行并留痕。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import StructuredTool

from capabilities.entity_guard import EntityGuard, find_incoherent
from capabilities.retrieval import SECTION_FIELDS
from config.loader import Settings

logger = logging.getLogger(__name__)


def make_financial_node(settings: Settings, document_tool: StructuredTool) -> Any:
    """财务栏目专职节点：检索 → 单篇代码绑定门 → 跨文档一致性门。"""

    async def financial_agent(state: dict[str, Any]) -> dict[str, Any]:
        section = "financial"
        field = SECTION_FIELDS[section]
        round_no = int(state.get("retry_count", {}).get(section, 0))
        raw = await document_tool.ainvoke(
            {"company": state["company"], "sections": [section], "round_no": round_no}
        )
        docs = list(raw.get(section, []))

        rejected: list[dict[str, Any]] = []
        all_rejected_fallback = False

        if settings.features.entity_guard and docs:
            guard = EntityGuard(state["company"], enabled=True)

            # 第一道门：单篇标题级判定。只拦 judge 判不 keep 的文档。
            after_ticker: list[dict[str, Any]] = []
            for doc in docs:
                verdict = guard.judge(doc)
                if not verdict.keep:
                    rejected.append(
                        {
                            "url": str(doc.get("url", "")),
                            "title": str(doc.get("title", ""))[:160],
                            "code": verdict.code,
                            "reason": verdict.reason,
                            **verdict.evidence,
                        }
                    )
                else:
                    after_ticker.append(doc)

            # 全灭护栏：整栏被第一道门清空则全部放行，防止误杀正经的
            # 带法域后缀外国公司（沿用 filter_docs 的语义）。
            if docs and not after_ticker:
                after_ticker = docs
                rejected = []
                all_rejected_fallback = True

            # 第二道门：只做跨文档一致性，不重复单篇判定。
            if len(after_ticker) >= 2:
                flagged = find_incoherent(after_ticker)
                flagged_urls = {str(d.get("url", "")) for d, _ in flagged}
                for doc, record in flagged:
                    rejected.append(
                        {
                            "url": str(doc.get("url", "")),
                            "title": str(doc.get("title", ""))[:160],
                            **record,
                        }
                    )
                if flagged_urls:
                    kept = [d for d in after_ticker if str(d.get("url", "")) not in flagged_urls]
                    # 跨文档也可能清空，同样放行
                    if kept:
                        after_ticker = kept
                    else:
                        all_rejected_fallback = True
            docs = after_ticker

        payload = {str(doc["url"]): doc for doc in docs}

        notes: list[dict[str, Any]] = [
            {
                "node": "research",
                "analyst": section,
                "round": round_no,
                "sections": [section],
                "docs": len(docs),
            }
        ]
        if rejected or all_rejected_fallback:
            notes.append(
                {
                    "node": "entity_guard",
                    "analyst": section,
                    "rejected": rejected,
                    "all_rejected_fallback": all_rejected_fallback,
                }
            )

        return {field: payload, "review_notes": notes}

    return financial_agent
