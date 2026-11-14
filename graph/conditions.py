"""条件边路由函数（S3）。

AGENT.md 第 6.9 条：条件函数必须是无副作用的纯函数，给定 State 返回分支名。
判定结果由 `evidence_check` 节点写进 `evidence_verdict`，这里只读不写。

循环终止的唯一依据是 `retry_count >= max_retry`，不让模型自己说「够了」。
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


def sections_to_research(state: dict[str, Any], settings: Settings) -> list[str]:
    """回退时只重搜证据不足的栏目，避免把四个 analyst 全部唤醒（成本翻四倍）。"""
    pending = insufficient_sections(state)
    return pending or list(settings.graph.sections)


def route_after_evidence(state: dict[str, Any], *, settings: Settings) -> Route:
    """evidence_check 后的三路分支。

    - 全部 sufficient → pass，进简报
    - 有 insufficient 且还有重试余量 → retry，改写 query 后回 research
    - 有 insufficient 但任一已达上限，或自纠正开关关闭 → degrade，明确拒答
    """
    pending = insufficient_sections(state)
    if not pending:
        return ROUTE_PASS
    if not settings.features.self_correction:
        return ROUTE_DEGRADE
    retry_count = state.get("retry_count", {})
    if any(retry_count.get(section, 0) >= settings.graph.max_retry for section in pending):
        return ROUTE_DEGRADE
    return ROUTE_RETRY
