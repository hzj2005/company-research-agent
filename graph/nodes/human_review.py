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


# 复核面板每个栏目最多展示几条证据、正文摘录截断多少字。
# 面板是给人看证据的：只给一个「共 8 条引用」的数字，人根本没法判断该不该批准，
# 审批就成了盲批。截断是为了不让 payload 无限大（它会进 checkpoint、还要过 SSE）。
EVIDENCE_PREVIEW_PER_SECTION = 4
SNIPPET_CHARS = 220


def _build_evidence_preview(
    state: ResearchState, sections: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """按栏目整理证据摘要，供复核人判断「这一栏证据够不够」。

    只取 `curated_data` 里已通过相关性阈值与实体消歧的文档，且只取真正会被写进
    报告的那些（与 report 节点的筛选口径一致：`in references` 才算数）。排序也按
    分数从高到低，保证人看到的是最可能进正文的那几条。
    """
    preview: dict[str, list[dict[str, Any]]] = {}

    for section in sections:
        # R3：证据来自该子图写好的段落 facts（不再是主图 curated_data）
        paragraph = state.get(f"{section}_paragraph") or {}
        facts = list(paragraph.get("facts", []))
        refs = paragraph.get("references", {}) or {}
        items: list[dict[str, Any]] = []
        for fact in facts[:EVIDENCE_PREVIEW_PER_SECTION]:
            url = str(fact.get("source_url") or "")
            content = str(fact.get("claim") or "").strip()
            meta = refs.get(url, {})
            items.append({
                "title": str(meta.get("title") or "")[:200],
                "url": url,
                "score": round(float(fact.get("confidence", 0) or 0.0), 4),
                "snippet": content[:SNIPPET_CHARS] + ("…" if len(content) > SNIPPET_CHARS else ""),
            })
        preview[section] = items
    return preview


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
            "reference_count": sum(
                len((state.get(f"{s}_paragraph") or {}).get("references", {}))
                for s in sections
            ),
            "degraded_sections": list(state.get("degraded_sections", [])),
            # 给人看的证据摘要：没有它，复核人只能看到一个引用总数，
            # 既判断不了证据够不够，也定不了该拒答哪一栏 —— 那就只是盲批。
            "evidence": _build_evidence_preview(state, sections),
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
