"""Company Agent 独立状态（重建版 R1/R2，R7 改为继承共用工作态）。

每栏目一套独立 state schema（D4）。`SectionWorkState` 只是**共用中间态字段**，
不是共用流程——节点顺序仍由本栏目 graph.py 自己决定。
输出字段必须是父图 State 的同名子集、带同名 reducer，编译时才能作为父图节点。
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from graph.agents.work_state import SectionWorkState
from graph.state import append_notes, append_unique, merge_mapping, replace_mapping


class CompanyAgentInput(TypedDict, total=False):
    company: str
    round_no: int


class CompanyAgentState(SectionWorkState, total=False):
    company_paragraph: Annotated[dict[str, Any], replace_mapping]
    degraded_sections: Annotated[list[str], append_unique]
    retry_count: Annotated[dict[str, int], merge_mapping]
    review_notes: Annotated[list[dict[str, Any]], append_notes]


class CompanyAgentOutput(TypedDict, total=False):
    """只回传本栏目段落与留痕，不污染其它栏目。"""

    company_paragraph: Annotated[dict[str, Any], replace_mapping]
    degraded_sections: Annotated[list[str], append_unique]
    retry_count: Annotated[dict[str, int], merge_mapping]
    review_notes: Annotated[list[dict[str, Any]], append_notes]
