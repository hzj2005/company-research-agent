"""S1 探针：验证 LangGraph 子图嵌子图 + Send 派发到嵌套子图节点。

目的（PROJECT_PLAN_V2.md 6.1 S1）：
  决定 V2 架构能否成立。若 `Send` 无法派发到"本身是编译子图"的节点，
  则整个 V2 降级为"4 平铺节点 + 内部条件链"。

验证三件事：
  1. 父节点的 Send 能否把任务派给一个 compiled subgraph 作为节点；
  2. 嵌套子图能否收到 Send 携带的局部 state（active_section）；
  3. 并行分支的输出能否通过 reducer 正确汇总回父 state。

0 网络、0 模型调用，纯状态传递。运行：
  .venv/Scripts/python.exe -m evals.probe_nested_send
"""

from __future__ import annotations

import sys
from operator import add
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send


class InnerState(TypedDict):
    active_section: str
    trace: Annotated[list[str], add]


class OuterState(TypedDict):
    sections: list[str]
    trace: Annotated[list[str], add]


def build_inner() -> Any:
    """内层 Agent 子图：收到 active_section，写一条 trace。"""

    def work(state: InnerState) -> dict[str, Any]:
        return {"trace": [f"inner:{state['active_section']}"]}

    g = StateGraph(InnerState)
    g.add_node("work", work)
    g.add_edge(START, "work")
    g.add_edge("work", END)
    return g.compile()


def build_outer(inner: Any) -> Any:
    """外层编排子图：dispatch 用 Send 派发到内层子图节点。"""

    def dispatch(state: OuterState) -> dict[str, Any]:
        return {"trace": [f"dispatch:{len(state['sections'])}"]}

    def fanout(state: OuterState) -> list[Send]:
        return [Send("agent", {"active_section": s}) for s in state["sections"]]

    g = StateGraph(OuterState)
    g.add_node("dispatch", dispatch)
    g.add_node("agent", inner)
    g.add_edge(START, "dispatch")
    g.add_conditional_edges("dispatch", fanout, ["agent"])
    g.add_edge("agent", END)
    return g.compile()


def main() -> int:
    sections = ["company", "industry", "financial", "news"]
    outer = build_outer(build_inner())
    result = outer.invoke({"sections": sections})
    trace = result.get("trace", [])

    print("nested Send result:", trace)
    expected_dispatch = "dispatch:4"
    expected_leaves = {f"inner:{s}" for s in sections}
    actual_leaves = {t for t in trace if t.startswith("inner:")}

    ok = expected_dispatch in trace and actual_leaves == expected_leaves
    if ok:
        print("[PASS] 嵌套 Send 可用：子图派发到 compiled 子图节点，状态传递与 reducer 汇总均正常")
        return 0
    print("[FAIL] 嵌套 Send 不符合预期：V2 需降级为 4 平铺节点 + 内部条件链")
    return 1


if __name__ == "__main__":
    sys.exit(main())
