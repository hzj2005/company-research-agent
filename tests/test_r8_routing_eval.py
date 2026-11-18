"""R8-P5：路由准确率的回归锁。

跑 `evals/routing_eval.py` 的规则路径（0 检索、0 模型调用），要求全过。
真实 LLM 的分数不在这里卡——模型会漂，硬编 100% 会变成「为了过测试改断言」；
LLM 对照结果留档在 `evals/routing_eval.json`，要更新时手动跑 `--live`。
"""

from __future__ import annotations

import asyncio

from evals.routing_eval import _evaluate, load_cases


def test_rule_routing_cases_all_pass() -> None:
    report = asyncio.run(_evaluate(load_cases(), live=False))

    assert report["passed"] == report["total"], (
        f"规则路由出现回归：{report['failed_messages']}"
    )
    assert report["accuracy"] == 1.0
