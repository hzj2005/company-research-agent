"""Company 专职 Agent 节点（V2 S4）。

相对原 `make_analyst_node` 的差异：抽取前先做**文档级实体消歧**（纯规则），
把同名异实体挡在事实抽取之前。复用现有 `entity_guard`，只是把它从主图
curate 下沉到公司子图内（curate 保留，双保险）。

边界说明：
- 本阶段**不改变输出字段**——仍只回传 `company_data` 与 `review_notes`，
  主图 State 契约、报告渲染、评测全程无感。
- 事实级冲突标注（`detect_conflicts`）**不在本阶段接入**：它依赖结构化 facts，
  而 facts 由 briefing 阶段的抽取链产出、此刻尚未下沉到子图。对文档正文做
  冲突检测是无效劳动（槽位正则针对英文 fact、fixture 正文是中文整段）。
  留到抽取链下沉后再接，见 PROJECT_PLAN_V2.md 4.1.1。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import StructuredTool

from capabilities.entity_guard import EntityGuard
from capabilities.retrieval import SECTION_FIELDS
from config.loader import Settings

logger = logging.getLogger(__name__)


def make_company_node(settings: Settings, document_tool: StructuredTool) -> Any:
    """公司栏目专职节点：检索 → 文档级实体消歧。"""

    async def company_agent(state: dict[str, Any]) -> dict[str, Any]:
        section = "company"
        field = SECTION_FIELDS[section]
        round_no = int(state.get("retry_count", {}).get(section, 0))
        raw = await document_tool.ainvoke(
            {"company": state["company"], "sections": [section], "round_no": round_no}
        )
        docs = list(raw.get(section, []))

        # 差异化：文档级实体消歧（纯规则，0 模型/网络调用）
        rejected: list[dict[str, Any]] = []
        all_rejected_fallback = False
        if settings.features.entity_guard:
            guard = EntityGuard(state["company"], enabled=True)
            result = guard.filter_docs(docs)
            docs = list(result.kept)
            rejected = result.rejected
            all_rejected_fallback = result.all_rejected_fallback

        payload = {str(doc["url"]): doc for doc in docs}

        notes: list[dict[str, Any]] = [
            {
                "node": "research",  # 保持 CLI/评测轨迹依赖的节点名
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

    return company_agent
