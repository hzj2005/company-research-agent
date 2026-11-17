"""统一 State 契约（S2 建、S3 补 reducer、S4 支持子图与全量重算）。

对应 docs/PROJECT_PLAN.md 第 4 节。修复原版三个问题：
1. 原版 `StateGraph(InputState)` 只有 5 个字段，18 个业务字段在别处 → 这里统一用 ResearchState。
2. 原版节点就地修改传入 State（curator.py L147、collector.py L30）→ 所有跨节点写入都声明字段并配 reducer。
3. 原版 `from typing import TypedDict` 在 Python 3.11 + pydantic 2.14 下
   `get_input_schema()` 抛 PydanticUserError（docs/BASELINE.md 第 3 节）
   → 统一从 typing_extensions 导入。

S4 新增：
- `sections_to_research`：rewrite_query 写入的回退白名单，子图 dispatch 据此用 Send 精确派发；
- `latest_list` / `replace_mapping`：白名单每轮覆盖而非累积；curate 每轮全量重算
  curated_data / references，让上一轮已失效的引用能被移除。
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


def merge_mapping(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> dict[str, Any]:
    """按键合并状态字典（retry_count / evidence_verdict / rewrite_queries / briefings）。

    回退节点只返回自己负责的 section，其他 section 的值必须原样保留。
    """
    return {**(left or {}), **(right or {})}


def replace_mapping(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> dict[str, Any]:
    """全量替换（S4）：curate 每轮基于全量原始文档重算，旧失效引用自动移除。

    right is None 表示本轮不更新；返回空 dict 是合法结果（清空）。
    """
    return dict(right) if right is not None else dict(left or {})


def latest_list(left: list[str] | None, right: list[str] | None) -> list[str]:
    """last-write-wins（S4）：回退白名单每轮覆盖，不累积上一轮的栏目。"""
    return list(right) if right is not None else list(left or [])


def append_unique(left: list[str] | None, right: list[str] | None) -> list[str]:
    """去重追加（degraded_sections）：同一 section 多次判定失败只记一次。"""
    return list(dict.fromkeys([*(left or []), *(right or [])]))


def append_notes(
    left: list[dict[str, Any]] | None,
    right: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """累加复核/降级备注，不覆盖历史记录。并行 analyst 各写一条也能全部保留。"""
    return [*(left or []), *(right or [])]


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

    # 四类原始检索文档：key = URL（累积，回退重搜要保留旧证据）
    company_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    industry_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    financial_data: Annotated[dict[str, dict[str, Any]], merge_docs]
    news_data: Annotated[dict[str, dict[str, Any]], merge_docs]

    # curate 每轮全量重算，不用累积语义
    curated_data: Annotated[dict[str, dict[str, Any]], replace_mapping]
    evidence_verdict: Annotated[dict[str, Verdict], merge_mapping]
    retry_count: Annotated[dict[str, int], merge_mapping]
    rewrite_queries: Annotated[dict[str, list[str]], merge_mapping]
    briefings: Annotated[dict[str, dict[str, Any]], merge_mapping]

    # url -> {title, score, used_by}；正文行内引用与末尾 References 同源
    references: Annotated[dict[str, dict[str, Any]], replace_mapping]

    # 回退白名单：空列表 = 首轮全栏目派发；非空 = 只派发这些栏目
    sections_to_research: Annotated[list[str], latest_list]

    degraded: bool
    degraded_sections: Annotated[list[str], append_unique]
    review_notes: Annotated[list[dict[str, Any]], append_notes]
    # S6 HITL：人工复核的原始决策（受控 dict），供审计与 resume 后追溯
    review_decision: Annotated[dict[str, Any], replace_mapping]
    # V2 后处理产物（行业竞品/对比矩阵、新闻时效/事件去重）；默认空，不影响报告
    postprocess: Annotated[dict[str, Any], replace_mapping]
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
        "sections_to_research": [],
        "degraded": False,
        "degraded_sections": [],
        "review_notes": [],
        "review_decision": {},
        "postprocess": {},
        "report": "",
        **kwargs,
    }
