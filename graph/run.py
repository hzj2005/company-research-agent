"""S3 CLI：在 fixture 模式真跑一次完整调研，不联网、不要 key。

    uv run python -m graph.run --case sparse --show-report --trace

默认每次用临时 SQLite 文件，保证结果可复现；`--db <path>` 可复用同一个库
演示 Checkpointer 的跨进程恢复。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from langgraph.types import Command

from capabilities.briefing import briefing_backend_scope
from capabilities.retrieval import load_fixture_store, make_document_tool
from config.loader import Settings, apply_overrides, build_thread_id, get_settings
from graph.builder import build_graph
from graph.state import initial_state
from persistence.checkpointer import CheckpointSession


async def run_research(
    company: str,
    settings: Settings,
    db_path: Path | str | None = None,
    *,
    collect_trace: bool = False,
    resume: dict[str, Any] | None = None,
    thread_id: str | None = None,
    document_tool: StructuredTool | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """跑完整图，返回 (最终 State, 节点执行轨迹)。

    - `briefing_backend_scope` 保证本次运行注入的 httpx client 一定被关闭。
    - `resume` 非空时用 `Command(resume=...)` 从**磁盘 checkpoint** 续跑（S6 HITL），
      调用方可以是一个全新的进程；这也是「checkpointer 不是摆设」的验证点。
    - 若本次运行暂停在 `interrupt()`，返回 State 会额外带 `_interrupt` 键
      （`{thread_id, payload}`，**不是图的 State 字段**，仅供 CLI/测试读取）。
    - `document_tool` 是 S8 预演/实测的注入点：调用方可传入带自己 `CallBudget`
      的检索工具以核对真实调用次数。默认 `None` 时行为与原来完全一致。

    统一走 `astream(updates)`：`ainvoke` 遇到 interrupt 的语义与 astream 不一致，
    这里保持一条路径，行为可预测。
    """
    async with (
        CheckpointSession(settings=settings, path=db_path) as session,
        briefing_backend_scope(settings) as backend,
    ):
        tool = document_tool if document_tool is not None else make_document_tool(settings)
        compiled = session.compile(
            build_graph(settings, tool, briefing_backend=backend)
        )
        config = session.config_for(
            thread_id or build_thread_id(company, settings=settings)
        )
        inp: Any = Command(resume=resume) if resume is not None else initial_state(company)

        trace: list[str] = []
        async for chunk in compiled.astream(inp, config=config, stream_mode="updates"):
            trace.extend(chunk.keys())
        snapshot = await compiled.aget_state(config)
        state = dict(snapshot.values)

        interrupts = [
            item.value
            for task in (snapshot.tasks or ())
            for item in (getattr(task, "interrupts", None) or ())
        ]
        if interrupts:
            state["_interrupt"] = {
                "thread_id": config.get("configurable", {}).get("thread_id", ""),
                "payload": interrupts[0],
            }
        return state, trace if collect_trace else []


def _summarize(state: dict[str, Any], trace: list[str]) -> dict[str, Any]:
    return {
        "company": state.get("company"),
        "evidence_verdict": state.get("evidence_verdict"),
        "retry_count": state.get("retry_count"),
        "degraded": state.get("degraded"),
        "degraded_sections": state.get("degraded_sections"),
        "review_decision": state.get("review_decision") or None,
        "interrupted": "_interrupt" in state,
        "curated_docs": len(state.get("curated_data", {})),
        "reference_count": len(state.get("references", {})),
        "report_chars": len(state.get("report", "")),
        "node_trace": trace,
        "research_runs": trace.count("research") if trace else None,
    }


def _build_resume(args: argparse.Namespace) -> dict[str, Any]:
    if args.decision == "approve":
        return {"approved": True, "rejected_sections": [], "note": args.note}
    if args.decision == "reject":
        return {"approved": False, "rejected_sections": [], "note": args.note}
    sections = [s.strip() for s in (args.reject_sections or "").split(",") if s.strip()]
    return {"approved": True, "rejected_sections": sections, "note": args.note}


def main() -> None:
    parser = argparse.ArgumentParser(description="公司调研 Agent：fixture 演示 / S6 人工复核")
    parser.add_argument("--case", choices=["sufficient", "sparse", "empty"])
    parser.add_argument("--company", default=None, help="直接指定公司名（需存在于 fixture）")
    parser.add_argument("--db", default=None, help="持久化 SQLite 库；默认每次临时库")
    parser.add_argument("--show-report", action="store_true")
    parser.add_argument("--trace", action="store_true", help="记录节点执行轨迹")
    parser.add_argument("--review", action="store_true", help="S6 第一步：跑到人工复核中断并打印 thread_id")
    parser.add_argument("--resume", action="store_true", help="S6 第二步：从磁盘 checkpoint 恢复")
    parser.add_argument("--decision", choices=["approve", "reject", "reject-sections"])
    parser.add_argument("--reject-sections", default="", help="逗号分隔，如 news,financial")
    parser.add_argument("--note", default="", help="复核备注")
    parser.add_argument("--thread-id", default=None, help="默认按公司名从 --case/--company 重算")
    args = parser.parse_args()

    review_mode = args.review or args.resume
    if args.review and args.resume:
        parser.error("--review 与 --resume 不能同时使用")
    if args.resume and not args.decision:
        parser.error("--resume 必须带 --decision")

    settings = get_settings()
    if review_mode:
        # CLI 显式开启 HITL，不依赖环境变量；两次运行必须用同一份配置重建图
        settings = apply_overrides(
            settings,
            {"features.human_review": True, "features.auto_approve_review": False},
        )

    store = load_fixture_store(settings)
    if args.case:
        company = store.case_by_key(args.case)["company"]
    elif args.company:
        company = args.company
    else:
        company = store.case_by_key("sufficient")["company"]

    if args.db:
        db_path: Path | None = Path(args.db)
    elif review_mode:
        db_path = Path("data/review.db")
    else:
        db_path = None
    if db_path is not None:
        db_path.parent.mkdir(parents=True, exist_ok=True)

    thread = args.thread_id or build_thread_id(company, settings=settings)
    resume = _build_resume(args) if args.resume else None
    tmp_ctx = tempfile.TemporaryDirectory() if db_path is None else None
    effective_db = db_path or Path(tmp_ctx.name) / "checkpoints.db"  # type: ignore[union-attr]
    try:
        state, trace = asyncio.run(
            run_research(
                company, settings, effective_db,
                collect_trace=args.trace or args.review,
                resume=resume, thread_id=thread,
            )
        )
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()

    if args.review and "_interrupt" in state:
        info = state["_interrupt"]
        print(json.dumps({
            "status": "interrupted",
            "company": company,
            "thread_id": info["thread_id"],
            "db_path": str(effective_db),
            "interrupt": info["payload"],
            "resume_hint": (
                f"uv run python -m graph.run --resume --case {args.case or 'sufficient'} "
                f"--db {effective_db} --decision approve --show-report"
            ),
        }, ensure_ascii=False, indent=2))
        return

    print(json.dumps(_summarize(state, trace), ensure_ascii=False, indent=2))
    if args.show_report:
        print("\n===== REPORT =====\n")
        print(state.get("report", ""))


if __name__ == "__main__":
    main()
