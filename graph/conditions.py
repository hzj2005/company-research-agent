"""条件边路由函数（S3 建，S4 改为栏目级重试判定）。

AGENT.md 第 6.9 条：条件函数必须是无副作用的纯函数，给定 State 返回分支名。
判定结果由 `evidence_check` 节点写进 `evidence_verdict`，这里只读不写。

循环终止的唯一依据是 `retry_count >= max_retry`，不让模型自己说「够了」。
S4 修正：原来用 `any(...)`，一个栏目达上限就把其他还有额度的栏目一起降级；
改成 `all(...)`，各栏目用尽自己的额度才整体拒答。
"""

from __future__ import annotations

from typing import Any, Literal

from config.loader import Settings

ROUTE_PASS = "pass"
ROUTE_RETRY = "retry"
ROUTE_DEGRADE = "degrade"

Route = Literal["pass", "retry", "degrade"]


def insufficient_sections(state: dict[str, Any]) -> list[str]:
    return [s for s, v in state.get("evidence_verdict", {}).items() if v == "insufficient"]


def eligible_sections(state: dict[str, Any], settings: Settings) -> list[str]:
    """证据不足、且重试额度尚未用尽的栏目。"""
    counts = state.get("retry_count", {})
    return [
        s
        for s in insufficient_sections(state)
        if counts.get(s, 0) < settings.graph.max_retry
    ]


def sections_to_research(state: dict[str, Any], settings: Settings) -> list[str]:
    """回退白名单：由 rewrite_query 写进 State，子图 dispatch 据此精确派发。

    首轮白名单为空（子图侧把空列表解释为「全部栏目」）；只有不足且仍有额度的
    栏目会被重搜，避免把 4 个 analyst 全部唤醒。
    """
    return eligible_sections(state, settings)


def route_after_evidence(state: dict[str, Any], *, settings: Settings) -> Route:
    """evidence_check 后的三路分支。

    - 全部 sufficient → pass，进简报
    - 有 insufficient 且仍有栏目有重试余量 → retry
    - 所有不足栏目都已用尽额度，或自纠正开关关闭 → degrade
    """
    pending = insufficient_sections(state)
    if not pending:
        return ROUTE_PASS
    if not settings.features.self_correction:
        return ROUTE_DEGRADE
    counts = state.get("retry_count", {})
    if all(counts.get(section, 0) >= settings.graph.max_retry for section in pending):
        return ROUTE_DEGRADE
    return ROUTE_RETRY
