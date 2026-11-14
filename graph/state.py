"""统一 State 契约（S2）。

对应 docs/PROJECT_PLAN.md 第 4 节。修复原版三个问题：
1. 原版 `StateGraph(InputState)` 只有 5 个字段，18 个业务字段在别处 → 这里统一用 ResearchState。
2. 原版节点就地修改传入 State（curator.py L147、collector.py L30）→ 这里所有跨节点写入都声明字段并配 reducer。
3. 原版 `from typing import TypedDict` 在 Python 3.11 + pydantic 2.14 下
   `get_input_schema()` 抛 PydanticUserError（docs/BASELINE.md 第 3 节）
   → 这里统一从 typing_extensions 导入。
"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph.message import add_messages
from typing_extensions import Annotated, NotRequired, Required, TypedDict

Section = Literal["company", "industry", "financial", "news"]
Verdict = Literal["sufficient", "insufficient", "degraded"]


def merge_docs(
    left: dict[str, dict[str, Any]] | None,
    right: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """按 URL 去重合并检索文档。

    并行 analyst 写回、或回退重搜时，旧证据必须保留；同一 URL 的新结果覆盖旧结果。
    不能直接用 operator.add，因为值是 dict。
    """
    return {**(left or {}), **(right or {})}


class InputState(TypedDict, total=False):
    """外部入参。只有这里允许 optional；业务字段一律在 ResearchState 声明。"""

    company: Required[str]
    company_url: NotRequired[str]
    hq_location: NotRequired[str]
    industry: NotRequired[str]
    job_id: NotRequired[str]
    thread_id: NotRequired[str]


class ResearchState(InputState):
    """全图唯一状态 schema。跨节点写入的字段必须在此声明。"""

    messages: Annotated[list[Any], add_messages]

    # 四类原始检索文档：key = URL
    company_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    industry_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    financial_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    news_data: Annotated[dict[str, dict[str, Any]], merge_docs]

    curated_data: dict[str, dict[str, Any]]
    evidence_verdict: dict[str, Verdict]
    retry_count: dict[str, int]
    rewrite_queries: dict[str, list[str]]
    briefings: dict[str, dict[str, Any]]

    # url -> {title, score, used_by}；正文行内引用与末尾 References 同源
    references: Annotated[dict[str, dict[str, Any]], merge_docs]

    review_notes: list[dict[str, Any]]
    report: str


def initial_state(company: str, **kwargs: Any) -> dict[str, Any]:
    """构造一次调研的初始 State；空容器显式初始化，避免节点里做 setdefault。"""
    return {
        "company": company,
        "messages": [],
        "company_data": {},
        "industry_data": {},
        "financial_data": {},
        "news_data": {},
        "curated_data": {},
        "evidence_verdict": {},
        "retry_count": {},
        "rewrite_queries": {},
        "briefings": {},
        "references": {},
        "review_notes": [],
        "report": "",
        **kwargs,
    }
