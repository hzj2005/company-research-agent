"""R3 验收：子图内消歧（迁移自旧 test_s4_multi_agent 的三个用例）。

新架构里消歧下沉进子图 pipeline（do_guard=True），验证：
异实体文档被挡掉，不进 paragraph 的 references；全灭时护栏放行。
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.tools import tool

from config.loader import get_settings
from graph.agents.company.nodes import make_company_pipeline_node
from graph.agents.financial.nodes import make_financial_pipeline_node


def _doc(url: str, title: str, content: str) -> dict[str, Any]:
    return {"url": url, "title": title, "content": content, "score": 0.9, "source": "test"}


def _offline(docs: dict[str, list[dict[str, Any]]]) -> Any:
    @tool
    async def fetch_company_documents(
        company: str, sections: list[str], round_no: int
    ) -> dict[str, list[dict[str, Any]]]:
        """离线返回给定文档，不联网。"""
        return {s: docs.get(s, []) for s in sections}

    return fetch_company_documents


def test_company_pipeline_rejects_same_name_foreign_entity() -> None:
    s = get_settings()
    docs = {
        "company": [
            _doc("https://e.org/real", "Notion 产品概览", "Notion 提供协作工作区。"),
            _doc("https://e.org/fake", "Notion VTec Berhad (0083.KL) Valuation Measures",
                 "Notion VTec Berhad 是马来西亚上市公司。"),
        ]
    }
    node = make_company_pipeline_node(s, _offline(docs))
    out = asyncio.run(node({"company": "Notion", "round_no": 0}))
    para = out["company_paragraph"]
    assert "https://e.org/real" in para["references"]
    assert "https://e.org/fake" not in para["references"], "异实体应被挡掉"
    guards = [n for n in out["review_notes"] if n.get("node") == "entity_guard"]
    assert guards and guards[0]["rejected"][0]["code"] == "ticker_binding"


def test_financial_pipeline_rejects_ticker_page() -> None:
    s = get_settings()
    docs = {
        "financial": [
            _doc("https://e.org/real", "Notion 融资信息", "2021 年完成 A 轮融资。"),
            _doc("https://e.org/fake", "Notion VTec Berhad (0083.KL) Key Statistics",
                 "market cap and shares outstanding data here."),
        ]
    }
    node = make_financial_pipeline_node(s, _offline(docs))
    out = asyncio.run(node({"company": "Notion", "round_no": 0}))
    para = out["financial_paragraph"]
    assert "https://e.org/real" in para["references"]
    assert "https://e.org/fake" not in para["references"]


def test_financial_all_rejected_fallback_keeps_docs() -> None:
    s = get_settings()
    docs = {"financial": [_doc("https://e.org/a", "Notion VTec Berhad (0083.KL) Valuation", "x")]}
    node = make_financial_pipeline_node(s, _offline(docs))
    out = asyncio.run(node({"company": "Notion", "round_no": 0}))
    para = out["financial_paragraph"]
    assert "https://e.org/a" in para["references"], "全灭护栏应放行"
    guards = [n for n in out["review_notes"] if n.get("node") == "entity_guard"]
    assert guards and guards[0]["all_rejected_fallback"] is True
