"""R7 验收：四个子图的工作流必须真的不同。

R3 的教训：四张子图都是「1 个节点 + 2 条边」，指向同一个 228 行的 pipeline，
拓扑完全相同，只在 prompt 和 analyzer 上有差别。这个测试锁住 R7 的改造结果，
防止以后有人为了"少写代码"再把流程合并回去。
"""

from __future__ import annotations

from capabilities.retrieval import make_document_tool
from config.loader import get_settings
from graph.agents.factory import build_all_agent_subgraphs


def _nodes(sub) -> set[str]:
    return {n for n in sub.get_graph().nodes if not n.startswith("__")}


def _agents() -> dict[str, object]:
    s = get_settings()
    return build_all_agent_subgraphs(s, make_document_tool(s))


def test_four_subgraphs_have_four_distinct_topologies() -> None:
    agents = _agents()
    topologies = {frozenset(_nodes(sub)) for sub in agents.values()}
    assert len(topologies) == 4, "四个子图的节点集合必须两两不同"
    sizes = sorted(len(_nodes(sub)) for sub in agents.values())
    assert sizes != [sizes[0]] * 4, "节点数不能全部相同"


def test_each_section_owns_a_distinct_stage() -> None:
    agents = _agents()
    assert {"conflict"} <= _nodes(agents["company"])
    assert {"bind_subject", "verify_amount"} <= _nodes(agents["financial"])
    assert {"filter_entity"} <= _nodes(agents["news"])
    assert {"scan", "fetch", "extract2"} <= _nodes(agents["industry"])


def test_section_specific_stages_do_not_leak_across_sections() -> None:
    agents = _agents()
    company, financial = _nodes(agents["company"]), _nodes(agents["financial"])
    news, industry = _nodes(agents["news"]), _nodes(agents["industry"])

    assert "bind_subject" not in company | news | industry
    assert "filter_entity" not in company | financial | industry
    assert "fetch" not in company | financial | news
    assert "conflict" not in financial | news | industry


def test_retry_loop_exists_in_every_section() -> None:
    """返工是四栏目共有的底线能力，不能因为差异化被删掉。"""
    for name, sub in _agents().items():
        assert any(
            getattr(e, "conditional", False) for e in sub.get_graph().edges
        ), f"{name} 缺少条件边（返工路由）"
