"""子图内部工作状态（四栏目共用）。

这些是**子图内部**字段，不出现在父图 State 里——`output_schema` 只放行各栏目
的 `{section}_paragraph / degraded_sections / retry_count / review_notes`，所以
中间态不会污染并行分支。

与 R3 的区别：R3 的中间态是函数局部变量（一个节点算完），R7 拆成多节点后必须
落在 state 上，才能在节点间传递。
"""

from __future__ import annotations

from typing import Any, TypedDict


class SectionWorkState(TypedDict, total=False):
    # 输入
    company: str
    round_no: int
    active_section: str

    # 循环控制
    attempt: int
    next_attempt: int
    used_round: int

    # 数据流
    docs: list[dict[str, Any]]
    facts: list[dict[str, Any]]
    references: dict[str, dict[str, Any]]
    source_texts: dict[str, str]
    processed_urls: list[str]
    notes: list[dict[str, Any]]

    # 判定与加工
    extract_status: str
    status: str
    conflicts: list[Any]
    analysis: dict[str, Any]
    subject_binding: dict[str, Any]
