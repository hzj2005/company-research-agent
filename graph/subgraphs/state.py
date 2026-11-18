"""S4 research 子图的独立 State。

对外只暴露「四类文档 + 复核留痕」。输出字段必须是 `ResearchState` 的子集、
且带同名 reducer，编译后的子图才能直接作为主图 `add_node` 的值
（已在 uv + AsyncSqliteSaver 环境实测：并行写回经 reducer 合并，不互相覆盖）。

用独立 schema 而不是复用 ResearchState，是为了把 `active_section` 这类
派发用的内部字段关在子图里，不污染主图状态契约（AGENT.md 第 6.2 条）。
"""

from __future__ import annotations

from typing import Any

from typing_extensions import Annotated, TypedDict

from graph.state import append_notes, merge_docs


class ResearchSubgraphState(TypedDict, total=False):
    company: str
    sections_to_research: list[str]
    # R8：路由选中的栏目。必须声明在子图 state 里，否则编排层读不到，
    # 会退回「四栏全派发」（P2 实测踩到：报告只渲染选中段，但四个 Agent 都跑了）。
    requested_sections: list[str]
    retry_count: dict[str, int]
    active_section: str

    company_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    industry_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    financial_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    news_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    review_notes: Annotated[list[dict[str, Any]], append_notes]


class ResearchSubgraphInput(TypedDict, total=False):
    """子图只接收编排参数，不接收累积型字段。

    关键：若把主图已有的 `review_notes` / `*_data` 传进子图，子图输出会把它们
    再带回主图，append_notes reducer 会把旧记录重复累加一次（S4 实测踩到）。
    """

    company: str
    sections_to_research: list[str]
    requested_sections: list[str]
    retry_count: dict[str, int]


class ResearchSubgraphOutput(TypedDict, total=False):
    """子图只回传本轮新增的四类文档与执行留痕。"""

    company_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    industry_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    financial_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    news_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    review_notes: Annotated[list[dict[str, Any]], append_notes]
