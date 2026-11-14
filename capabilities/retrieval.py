"""文档数据源（S3）。

按 AGENT.md 第 7.3 条把数据源封装成 LangChain `@tool`，节点里不直接读文件、
不 new 第三方 client。当前只实现 `fixture` 模式：`evals/fixtures/tavily_responses.json`
里的三类合成样本，按「公司 / 栏目 / 轮次」取回结果，无需任何 API key。

`live` 模式（真实 Tavily Retriever）留到 S5，这里显式抛 NotImplementedError，
不伪装成已实现、也不悄悄回退到 fixture。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool, tool

from config.loader import ROOT, Settings, get_settings

logger = logging.getLogger(__name__)

SECTION_FIELDS: dict[str, str] = {
    "company": "company_data",
    "industry": "industry_data",
    "financial": "financial_data",
    "news": "news_data",
}


def resolve_fixture_path(settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    p = Path(s.models.fixture.responses_path)
    return p if p.is_absolute() else (ROOT / p).resolve()


class FixtureStore:
    """只读合成样本库。rounds 的索引就是回退轮次，用尽后返回空结果。"""

    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    @property
    def cases(self) -> dict[str, dict[str, Any]]:
        return self._data["cases"]

    def case_by_key(self, key: str) -> dict[str, Any]:
        return self.cases[key]

    def find_case(self, company: str) -> dict[str, Any] | None:
        for case in self.cases.values():
            if case["company"].lower() == company.lower():
                return case
        return None

    def fetch(self, company: str, sections: list[str], round_no: int) -> dict[str, list[dict[str, Any]]]:
        case = self.find_case(company)
        rounds = case["rounds"] if case else []
        raw = rounds[round_no] if round_no < len(rounds) else {}
        out: dict[str, list[dict[str, Any]]] = {}
        for section in sections:
            docs = []
            for item in raw.get(section, []):
                doc = dict(item)
                doc["section"] = section
                doc["round"] = round_no
                docs.append(doc)
            out[section] = docs
        return out


def load_fixture_store(settings: Settings | None = None) -> FixtureStore:
    s = settings or get_settings()
    if s.app.mode != "fixture":
        raise NotImplementedError(
            "live 检索将在 S5 用 BaseRetriever 接入 Tavily；当前请先设 APP_MODE=fixture"
        )
    return FixtureStore(resolve_fixture_path(s))


def make_document_tool(settings: Settings | None = None) -> StructuredTool:
    """构造供 research 节点调用的工具；模式差异只在这层，业务节点无分支判断。"""
    s = settings or get_settings()
    store = load_fixture_store(s)

    @tool
    async def fetch_company_documents(
        company: str, sections: list[str], round_no: int
    ) -> dict[str, list[dict[str, Any]]]:
        """按公司名、栏目列表和回退轮次取回检索文档。返回 {栏目: [文档]}。"""
        result = store.fetch(company, sections, round_no)
        logger.info(
            "fixture fetch company=%s round=%s sections=%s docs=%s",
            company, round_no, sections, sum(len(v) for v in result.values()),
        )
        return result

    return fetch_company_documents
