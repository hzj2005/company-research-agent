"""R4-1 Company 专属加工：同栏目事实冲突标注（同轮才判）。

规则（用户 2026-11-18 确认）：不同轮次的不同取值视为"陆续补充/修正"，
不算冲突；只有**同一轮**内出现两个不同取值，才作为真冲突标注出来。

产出结构化 conflicts（不带编号），由报告层 assemble 统一渲染 `[n]`：
  [{slot, label, values: [{display, urls: [...]}]}]
复用 capabilities.conflict.detect_conflicts（已实现槽位识别与阈值）。
"""

from __future__ import annotations

from typing import Any

from config.loader import Settings
from graph.contracts import Fact


def _to_facts(raw: list[dict[str, Any]]) -> list[Fact]:
    out: list[Fact] = []
    for f in raw:
        try:
            out.append(
                Fact(
                    claim=str(f["claim"]),
                    source_url=f["source_url"],
                    confidence=float(f.get("confidence", 0.0)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def detect_same_round_conflicts(
    facts: list[dict[str, Any]], company: str, settings: Settings
) -> list[dict[str, Any]]:
    """按轮次分组，组内调 detect_conflicts；合并成结构化列表。"""
    from capabilities.conflict import detect_conflicts

    by_round: dict[int, list[dict[str, Any]]] = {}
    for f in facts:
        by_round.setdefault(int(f.get("_round", 0)), []).append(f)

    conflicts: list[dict[str, Any]] = []
    for round_no in sorted(by_round):
        round_facts = _to_facts(by_round[round_no])
        for c in detect_conflicts(round_facts):
            conflicts.append(
                {
                    "slot": c.slot,
                    "label": c.label,
                    "round": round_no,
                    "values": [
                        {"display": v.display, "urls": list(v.source_urls)}
                        for v in c.values
                    ],
                }
            )
    return conflicts
