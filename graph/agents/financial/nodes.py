"""Financial Agent 的栏目专属实现 + 两个独有节点。

财务是唯一"先确认主体、再谈钱、最后核数字"的栏目：
- `bind_subject`：判定上市状态，避免把同名公司（含上市公司行情页）的钱当成本公司的；
- `verify_amount`：抽取后立刻核对金额是否原样出现在原文，独立留痕。

两个节点都只**记录/标注**，不删数据——`unknown` 不能当 `not_listed` 用。
"""

from __future__ import annotations

from typing import Any

from capabilities.finance_postprocess import verify_amounts
from capabilities.subject_binding import bind_subject
from config.loader import Settings
from graph.agents.extract import extract_with_fallback
from graph.agents.financial.prompts import FINANCIAL_ADDENDUM
from graph.agents.primitives import to_facts


async def financial_extract(
    company: str, section: str, docs: list[dict[str, Any]], settings: Settings
) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    """Financial extract：本栏目 prompt + 共享三级降级链。"""
    return await extract_with_fallback(
        company, section, docs, settings, addendum=FINANCIAL_ADDENDUM
    )


def make_bind_subject_node(section: str) -> Any:
    """主体绑定节点：判定上市状态（listed / not_listed / unknown）。"""

    def bind(state: dict[str, Any]) -> dict[str, Any]:
        binding = bind_subject(state["company"], state.get("docs") or []).to_dict()
        return {
            "subject_binding": binding,
            "notes": [
                *(state.get("notes") or []),
                {
                    "node": "bind_subject",
                    "section": section,
                    "status": binding["status"],
                    "ticker": binding["ticker"],
                    "reason": binding["reason"],
                },
            ],
        }

    return bind


def make_verify_amount_node(section: str) -> Any:
    """金额核对节点：纯规则，不做时间线、不判冲突。"""

    def verify(state: dict[str, Any]) -> dict[str, Any]:
        check = verify_amounts(
            to_facts(state.get("facts") or []),
            source_texts=state.get("source_texts") or {},
        )
        return {
            "analysis_extra": {
                "amount_verified": len(check["verified"]),
                "unverified_amounts": check["unverified"],
                "unchecked_amounts": len(check["unchecked"]),
            },
            "notes": [
                *(state.get("notes") or []),
                {
                    "node": "verify_amount",
                    "section": section,
                    "verified": len(check["verified"]),
                    "unverified": len(check["unverified"]),
                    "unchecked": len(check["unchecked"]),
                },
            ],
        }

    return verify
