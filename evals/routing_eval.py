"""R8-P5：路由准确率评测。

默认只跑**规则路径**（确定性、0 检索、0 模型调用）；`--live` 额外跑一遍真实
LLM 路由做对照。输出 `evals/routing_eval.json`：逐条结果 + 准确率 + 失败清单。

准确率口径（三条都中才算一条通过）：
1. 公司主体；
2. 栏目集合（顺序按配置，比较集合）；
3. 是否需要追问、追问类型。

失败条目原样列出来，不粉饰——路由判错会直接导致报告缺栏目，这是本功能最大的风险。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from config.loader import ROOT, get_settings
from graph.nodes.router import decide_route, llm_route_message

CASES_PATH = ROOT / "evals" / "routing_cases.json"
OUTPUT_PATH = ROOT / "evals" / "routing_eval.json"


def load_cases() -> list[dict[str, Any]]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def _checked(got: dict[str, Any], case: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if (got.get("company") or None) != case["expect_company"]:
        reasons.append(f"公司: 期望 {case['expect_company']!r}，得到 {got.get('company')!r}")
    if sorted(got.get("sections") or []) != sorted(case["expect_sections"]):
        reasons.append(f"栏目: 期望 {case['expect_sections']}，得到 {got.get('sections')}")
    got_kind = got.get("clarify_kind") if got.get("need_clarify") else None
    if got_kind != case["expect_clarify"]:
        reasons.append(f"追问: 期望 {case['expect_clarify']!r}，得到 {got_kind!r}")
    return not reasons, reasons


async def _evaluate(cases: list[dict[str, Any]], *, live: bool) -> dict[str, Any]:
    settings = get_settings()
    rows: list[dict[str, Any]] = []
    for case in cases:
        # 规则块必须显式 force_rules：否则 live 模式下节点会自动走 LLM，
        # 两行结果就变成同一份实现（第一版评测就踩了这个，两边数字一模一样）。
        got = await decide_route(
            case["message"],
            case["company_hint"],
            settings,
            llm_route=llm_route_message if live else None,
            force_rules=not live,
        )
        ok, reasons = _checked(got, case)
        rows.append({
            "message": case["message"],
            "note": case["note"],
            "passed": ok,
            "expected": {
                "company": case["expect_company"],
                "sections": case["expect_sections"],
                "clarify": case["expect_clarify"],
            },
            "got": {
                "company": got.get("company"),
                "sections": got.get("sections"),
                "clarify": got.get("clarify_kind") if got.get("need_clarify") else None,
                "source": got.get("source"),
            },
            "failures": reasons,
        })

    passed = sum(1 for row in rows if row["passed"])
    return {
        "mode": "live" if live else "rules",
        "total": len(rows),
        "passed": passed,
        "accuracy": round(passed / len(rows), 4) if rows else 0.0,
        "failed_messages": [row["message"] for row in rows if not row["passed"]],
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="R8 路由准确率评测（默认 0 成本）")
    parser.add_argument("--live", action="store_true", help="额外跑真实 LLM 路由做对照")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    cases = load_cases()
    report: dict[str, Any] = {"rules": asyncio.run(_evaluate(cases, live=False))}
    if args.live:
        report["llm"] = asyncio.run(_evaluate(cases, live=True))

    out = Path(args.output) if args.output else OUTPUT_PATH
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for key, block in report.items():
        print(
            f"{key}: {block['passed']}/{block['total']} 通过，"
            f"准确率 {block['accuracy']:.3f}，失败 {block['failed_messages']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
