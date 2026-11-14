"""S1 基线采集：真实构造并编译上游 LangGraph 图，导出可核查的结构证据。

运行：
    .venv/Scripts/python.exe baseline/inspect_upstream.py

边界（务必如实对外说明）：
- 本脚本**不发起任何外部网络请求**。占位 key 仅用于让上游构造函数通过
  `TAVILY_API_KEY` / LLM key 的非空校验（backend/nodes/researchers/base.py L20-25、
  backend/llm.py L74-79），不会真的调用 Tavily 或模型。
- 因此它证明的是「原版图能被真实构造、编译，结构可导出」，**不等于**跑通了
  /research 的完整调研。完整链路需要真实 key，见 docs/ACTION_PLAN.md S8。
- 另外会真实执行 3 个不依赖外部服务的纯逻辑节点，作为可运行性证据。
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import sys
from datetime import datetime
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 占位 key：只让上游构造函数通过校验，绝不用于发起请求
os.environ["TAVILY_API_KEY"] = "fixture-placeholder-no-network"
os.environ["OPENROUTER_API_KEY"] = "fixture-placeholder-no-network"
os.environ["OPENROUTER_MODEL"] = "google/gemini-3.8-flash"

OUT = ROOT / "baseline" / "upstream_graph.json"


def dep_versions() -> dict[str, str]:
    names = [
        "langchain", "langchain-core", "langchain-openai", "langchain-community",
        "langgraph", "langgraph-checkpoint", "pydantic", "tavily-python",
        "fastapi", "pytest", "PyYAML",
    ]
    out = {}
    for n in names:
        try:
            out[n] = metadata.version(n)
        except metadata.PackageNotFoundError:
            out[n] = "(not installed)"
    return out


def inspect_graph() -> dict:
    """真实构造 + 编译上游图，并从图对象导出结构（而非 grep 源码）。"""
    from backend.graph import Graph

    g = Graph(
        company="Notion",
        url="notion.so",
        hq_location="San Francisco",
        industry="Productivity Software",
        job_id="baseline-001",
    )
    compiled = g.compile()
    drawable = compiled.get_graph()

    nodes = sorted(drawable.nodes.keys())
    edges = []
    for e in drawable.edges:
        edges.append({
            "source": getattr(e, "source", None),
            "target": getattr(e, "target", None),
            "conditional": bool(getattr(e, "conditional", False)),
        })
    edges.sort(key=lambda x: (str(x["source"]), str(x["target"])))

    # 输入 schema 的动态证据：原版只有 InputState 的字段
    schema_fields = []
    try:
        schema = compiled.get_input_schema().model_json_schema()
        schema_fields = sorted((schema.get("properties") or {}).keys())
    except Exception as exc:  # noqa: BLE001 - 基线脚本需记录失败原因而非中断
        schema_fields = [f"(schema introspection failed: {type(exc).__name__}: {exc})"]

    return {
        "compiled_type": type(compiled).__name__,
        "nodes": nodes,
        "node_count": len(nodes),
        "edges": edges,
        "edge_count": len(edges),
        "conditional_edge_count": sum(1 for e in edges if e["conditional"]),
        "input_schema_fields": schema_fields,
        "entry_point": [n for n in ("grounding",) if n in nodes],
        "state_schema_class": type(g.workflow).__name__,
        "compile_with_checkpointer": False,  # 原版 graph.py L98/L107 为裸 compile()
    }


def sample_state() -> dict:
    """构造一份不依赖外部服务的 State，用于真跑纯逻辑节点。"""
    def doc(url: str, score: float, title: str) -> dict:
        return {"url": url, "title": title, "score": score, "content": "fixture content"}

    return {
        "company": "Notion",
        "company_url": "notion.so",
        "hq_location": "San Francisco",
        "industry": "Productivity Software",
        "job_id": "baseline-001",
        "messages": [],
        "financial_data": {
            "https://example.com/funding": doc("https://example.com/funding", 0.91, "Funding round"),
            "https://example.com/low": doc("https://example.com/low", 0.12, "Low score"),
        },
        "news_data": {
            "https://example.com/news": doc("https://example.com/news", 0.77, "Product launch"),
        },
        "industry_data": {},
        "company_data": {
            "https://notion.so/about": doc("https://notion.so/about", 0.05, "About"),
        },
    }


def run_pure_nodes() -> dict:
    """真跑 grounding / collector / curator 三个不联网节点，记录输入与输出差异。"""
    from backend.nodes.collector import Collector
    from backend.nodes.curator import Curator
    from backend.nodes.grounding import GroundingNode

    async def _main() -> dict:
        grounding = await GroundingNode().run({
            "company": "Notion",
            "company_url": "notion.so",
            "hq_location": "San Francisco",
            "industry": "Productivity Software",
            "job_id": "baseline-001",
            "messages": [],
        })

        state = sample_state()
        before_keys = sorted(state.keys())
        await Collector().run(state)
        after_collector_keys = sorted(state.keys())
        await Curator().run(state)
        after_curator_keys = sorted(state.keys())

        return {
            "grounding_output_keys": sorted(grounding.keys()),
            "grounding_company": grounding.get("company"),
            "collector_added_keys": sorted(set(after_collector_keys) - set(before_keys)),
            "curator_added_keys": sorted(set(after_curator_keys) - set(after_collector_keys)),
            "curator_kept_financial": len(state.get("curated_financial_data", {})),
            "curator_kept_news": len(state.get("curated_news_data", {})),
            "curator_kept_company": len(state.get("curated_company_data", {})),
            "references_count": len(state.get("references", [])),
            "nodes_mutate_state_in_place": True,  # curator.py L147/L155-157 直接写 state
        }

    return asyncio.run(_main())


def main() -> int:
    result = {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "upstream_commit": "23fe92d48ea05750e6fd7cffdb78799cea5278d8",
        "network_calls": "none (placeholder keys only)",
        "dependencies": dep_versions(),
    }
    try:
        result["graph"] = inspect_graph()
        print("[OK] 上游 StateGraph 构造 + compile() 成功")
    except Exception as exc:  # noqa: BLE001
        result["graph_error"] = f"{type(exc).__name__}: {exc}"
        print(f"[FAIL] 图构造失败: {result['graph_error']}")

    try:
        result["pure_nodes"] = run_pure_nodes()
        print("[OK] grounding / collector / curator 三个纯节点真实执行成功")
    except Exception as exc:  # noqa: BLE001
        result["pure_nodes_error"] = f"{type(exc).__name__}: {exc}"
        print(f"[FAIL] 纯节点执行失败: {result['pure_nodes_error']}")

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 基线已写入 {OUT.relative_to(ROOT)}")

    if "graph" in result:
        g = result["graph"]
        print(f"     节点 {g['node_count']} 个 / 边 {g['edge_count']} 条 / 条件边 {g['conditional_edge_count']} 条")
        print(f"     输入 schema 字段: {g['input_schema_fields']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
