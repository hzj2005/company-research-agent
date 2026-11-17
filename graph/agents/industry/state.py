"""Industry Agent 独立状态（重建版 R1/R2）。"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from graph.state import append_notes, merge_docs


class IndustryAgentInput(TypedDict, total=False):
    company: str
    round_no: int


class IndustryAgentState(TypedDict, total=False):
    company: str
    round_no: int
    active_section: str
    industry_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    review_notes: Annotated[list[dict[str, Any]], append_notes]


class IndustryAgentOutput(TypedDict, total=False):
    industry_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    review_notes: Annotated[list[dict[str, Any]], append_notes]
