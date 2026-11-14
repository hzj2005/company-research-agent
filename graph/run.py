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

from capabilities.retrieval import load_fixture_store, make_document_tool
from config.loader import Settings, build_thread_id, get_settings
from graph.builder import build_graph
from graph.state import initial_state
from persistence.checkpointer import CheckpointSession


async def run_research(
    company: str,
    settings: Settings,
    db_path: Path | str | None = None,
    *,
    collect_trace: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """跑完整图，返回 (最终 State, 节点执行轨迹)。"""
    async with CheckpointSession(settings=settings, path=db_path) as session:
        compiled = session.compile(build_graph(settings, make_document_tool(settings)))
        config = session.config_for(build_thread_id(company, settings=settings))
        if not collect_trace:
            result = await compiled.ainvoke(initial_state(company), config=config)
            return result, []

        trace: list[str] = []
        async for chunk in compiled.astream(
            initial_state(company), config=config, stream_mode="updates"
        ):
            trace.extend(chunk.keys())
        snapshot = await compiled.aget_state(config)
        return dict(snapshot.values), trace


def _summarize(state: dict[str, Any], trace: list[str]) -> dict[str, Any]:
    return {
        "company": state.get("company"),
        "evidence_verdict": state.get("evidence_verdict"),
        "retry_count": state.get("retry_count"),
        "degraded": state.get("degraded"),
        "degraded_sections": state.get("degraded_sections"),
        "curated_docs": len(state.get("curated_data", {})),
        "reference_count": len(state.get("references", {})),
        "report_chars": len(state.get("report", "")),
        "node_trace": trace,
        "research_runs": trace.count("research") if trace else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="S3 自纠正回路 fixture 演示")
    parser.add_argument("--case", choices=["sufficient", "sparse", "empty"])
    parser.add_argument("--company", default=None, help="直接指定公司名（需存在于 fixture）")
    parser.add_argument("--db", default=None, help="复用指定 SQLite 库；默认每次临时库")
    parser.add_argument("--show-report", action="store_true")
    parser.add_argument("--trace", action="store_true", help="记录节点执行轨迹")
    args = parser.parse_args()

    settings = get_settings()
    store = load_fixture_store(settings)
    if args.case:
        company = store.case_by_key(args.case)["company"]
    elif args.company:
        company = args.company
    else:
        company = store.case_by_key("sufficient")["company"]

    if args.db:
        state, trace = asyncio.run(
            run_research(company, settings, Path(args.db), collect_trace=args.trace)
        )
    else:
        with tempfile.TemporaryDirectory() as td:
            state, trace = asyncio.run(
                run_research(company, settings, Path(td) / "checkpoints.db", collect_trace=args.trace)
            )

    print(json.dumps(_summarize(state, trace), ensure_ascii=False, indent=2))
    if args.show_report:
        print("\n===== REPORT =====\n")
        print(state.get("report", ""))


if __name__ == "__main__":
    main()
