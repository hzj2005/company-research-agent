"""Financial Agent 独立状态（重建版 R1/R2）。"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from graph.state import append_notes, append_unique, merge_docs, merge_mapping, replace_mapping


class FinancialAgentInput(TypedDict, total=False):
    company: str
    round_no: int


class FinancialAgentState(TypedDict, total=False):
    company: str
    round_no: int
    active_section: str
    financial_paragraph: Annotated[dict[str, Any], replace_mapping]
    degraded_sections: Annotated[list[str], append_unique]
    retry_count: Annotated[dict[str, int], merge_mapping]
    review_notes: Annotated[list[dict[str, Any]], append_notes]


class FinancialAgentOutput(TypedDict, total=False):
    financial_paragraph: Annotated[dict[str, Any], replace_mapping]
    degraded_sections: Annotated[list[str], append_unique]
    retry_count: Annotated[dict[str, int], merge_mapping]
    review_notes: Annotated[list[dict[str, Any]], append_notes]
