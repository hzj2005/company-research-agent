"""Company Agent 独立状态（重建版 R1/R2）。

每栏目一套独立 state schema（D4），不共用 ResearchSubgraphState。
输出字段必须是父图 State 的同名子集、带同名 reducer，编译时才能作为父图节点。
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from graph.state import append_notes, merge_docs


class CompanyAgentInput(TypedDict, total=False):
    company: str
    round_no: int


class CompanyAgentState(TypedDict, total=False):
    company: str
    round_no: int
    active_section: str
    company_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    review_notes: Annotated[list[dict[str, Any]], append_notes]


class CompanyAgentOutput(TypedDict, total=False):
    """只回传本栏目数据与留痕，不污染其它栏目。"""

    company_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    review_notes: Annotated[list[dict[str, Any]], append_notes]
