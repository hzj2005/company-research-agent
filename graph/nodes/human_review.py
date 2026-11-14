"""S6 HITL：成稿前的人工复核节点（图内 `interrupt()`）。

为什么放在 `briefing` 之前：`briefing` 会从 `degraded_sections` 决定哪些栏目拒答，
所以复核必须能改写这个字段，人工意见才会真正改变报告，而不是只留一条日志。

两级开关（见 ACTION_PLAN 10.2）：
- `features.human_review=false`：`build_graph` 根本不注册本节点，主图仍是 7 节点；
- `features.human_review=true` + `auto_approve_review=true`：节点存在但不中断，写
  `auto_approved` 留痕（无人值守 / A/B 基线）；
- `features.human_review=true` + `auto_approve_review=false`：真 `interrupt()` 暂停，
  由 CLI `--resume` 在新进程里用 `Command(resume=...)` 续跑。

`interrupt()` 恢复时节点会从头重跑，因此这里**不做任何副作用**，第一行就是取值。
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.types import interrupt

from config.loader import Settings
from graph.state import ResearchState

Node = Callable[[ResearchState], Any]


def _normalize_decision(raw: Any, sections: list[str]) -> dict[str, Any]:
    """把 resume 值收敛成受控契约，非法输入按「不批准」处理（fail-safe）。"""
    if not isinstance(raw, dict):
        return {
            "approved": False,
            "rejected_sections": [],
            "note": f"非法决策类型 {type(raw).__name__}",
            "invalid": True,
        }
    requested = raw.get("rejected_sections", [])
    if not isinstance(requested, (list, tuple)):
        requested = []
    # 栏目白名单：拒绝模型/调用方传进来的任意字符串污染 State
    rejected = [s for s in dict.fromkeys(requested) if s in sections]
    return {
        "approved": bool(raw.get("approved", False)),
        "rejected_sections": rejected,
        "note": str(raw.get("note", ""))[:300],
    }


def make_human_review_node(settings: Settings) -> Node:
    sections = list(settings.graph.sections)

    async def human_review(state: ResearchState) -> dict[str, Any]:
        if settings.features.auto_approve_review:
            return {
                "review_decision": {
                    "approved": True,
                    "rejected_sections": [],
                    "note": "auto_approved",
                },
                "review_notes": [{"node": "human_review", "status": "auto_approved"}],
            }

        payload = {
            "prompt": "复核成稿：批准出稿，或指定要拒答的栏目",
            "company": state["company"],
            "sections": sections,
            "reference_count": len(state.get("references", {})),
            "degraded_sections": list(state.get("degraded_sections", [])),
            "decision_schema": {
                "approved": "bool —— false 表示整份报告拒答",
                "rejected_sections": "list[str] —— 只拒答这些栏目，必须在 sections 内",
                "note": "str —— 复核备注",
            },
        }
        decision = _normalize_decision(interrupt(payload), sections)

        if decision["approved"] and not decision["rejected_sections"]:
            return {
                "review_decision": decision,
                "review_notes": [
                    {"node": "human_review", "status": "approved", "note": decision["note"]}
                ],
            }

        # 人工否决 → 复用「未找到公开依据」文案，不生成新结论、不编造
        rejected = (
            sections
            if not decision["approved"]
            else decision["rejected_sections"]
        )
        return {
            "review_decision": decision,
            "degraded": True,
            "degraded_sections": rejected,  # append_unique reducer，只追加不覆盖
            "review_notes": [
                {
                    "node": "human_review",
                    "status": "rejected",
                    "sections": rejected,
                    "note": decision["note"],
                    "message": settings.graph.degrade.message,
                }
            ],
        }

    return human_review
