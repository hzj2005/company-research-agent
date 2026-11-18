"""文档数据源工厂（S3 fixture → S5-B 双模式）。

业务节点只见到一个 `@tool`：`fetch_company_documents(company, sections, round_no)`，
模式差异全部收敛在这层，节点里没有 `if app.mode == ...` 的分支判断。

- **fixture（默认）**：只读 `evals/fixtures/tavily_responses.json` 的合成样本，
  0 次网络请求、0 次 Tavily 调用、不需要任何 key。
- **live**：`TavilyRetriever(BaseRetriever)` + 三重 opt-in 护栏；未放行、缺 key、
  额度用尽一律明确抛错，**绝不悄悄回退 fixture**。测试通过 `retriever_factory`
  注入离线替身，同样 0 次真实调用。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import StructuredTool, tool

from capabilities.tavily_retriever import (
    CallBudget,
    DryRunSentinel,
    LiveRetrievalDisabled,
    build_live_retrievers,
)
from config.loader import (
    ROOT,
    Settings,
    get_settings,
    resolve_live_cache_dir,
    resolve_tavily_credentials,
)

logger = logging.getLogger(__name__)

SECTION_FIELDS: dict[str, str] = {
    "company": "company_data",
    "industry": "industry_data",
    "financial": "financial_data",
    "news": "news_data",
}

# 每栏目每轮只发 1 条 query（原版是 2 条）；护栏优先，宁可少召回也不浪费额度
_SECTION_QUERY_HINTS = {
    "company": "company overview background products",
    "industry": "industry market landscape competitors",
    "financial": "financial results revenue funding valuation",
    "news": "recent news announcements partnerships",
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

    def fetch(
        self,
        company: str,
        sections: list[str],
        round_no: int,
        queries: list[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        case = self.find_case(company)
        if queries:
            return {
                section: _dedup_urls(
                    self._fetch_by_queries(case, section, queries, round_no)
                )
                for section in sections
            }
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

    def _fetch_by_queries(
        self,
        case: dict[str, Any] | None,
        section: str,
        queries: list[str],
        round_no: int,
    ) -> list[dict[str, Any]]:
        """按 query 取样本：用 `competitor_docs` 的 key 做包含匹配（取最长命中）。

        没录入的 query 返回空 —— 与真实检索「搜不到」语义一致，不允许兜底成
        栏目样本，否则「两阶段检索」会看起来永远成功。
        """
        if not case:
            return []
        table = case.get("competitor_docs") or {}
        docs: list[dict[str, Any]] = []
        for q in queries:
            low = q.lower()
            hit = max(
                (name for name in table if name.lower() in low),
                key=len,
                default=None,
            )
            for item in table.get(hit, []) if hit else []:
                doc = dict(item)
                doc["section"] = section
                doc["round"] = round_no
                doc["query"] = q
                docs.append(doc)
        return docs


def load_fixture_store(settings: Settings | None = None) -> FixtureStore:
    s = settings or get_settings()
    if s.app.mode != "fixture":
        raise LiveRetrievalDisabled(
            "fixture 样本库只在 APP_MODE=fixture 下可用；live 请走 make_document_tool 的检索工具"
        )
    return FixtureStore(resolve_fixture_path(s))


def build_live_query(company: str, section: str, round_no: int, variant: int = 0) -> str:
    """确定性 query：回退轮换措辞，让缓存 key 与首轮不同。

    `variant` 用于「同一栏发多条 query」：措辞必须稳定，否则缓存失效、
    同一家公司重复跑也要重新花钱。
    """
    hint = _SECTION_QUERY_HINTS.get(section, section)
    suffix = "" if round_no <= 0 else f" refined round {round_no}"
    if variant:
        suffix += f" variant {variant}"
    return f"{company} {hint}{suffix}"


def _dedup_urls(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 URL 去重，保留首次出现顺序；无 URL 的文档保留（交由下游守卫丢）。"""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in docs:
        url = str(doc.get("url") or "")
        if url and url in seen:
            continue
        if url:
            seen.add(url)
        out.append(doc)
    return out


def _document_to_dict(doc: Any, section: str, round_no: int) -> dict[str, Any]:
    meta = doc.metadata if hasattr(doc, "metadata") else {}
    return {
        "url": meta.get("url", ""),
        "title": meta.get("title", ""),
        "score": float(meta.get("score", 0.0) or 0.0),
        "content": getattr(doc, "page_content", ""),
        "section": section,
        "round": round_no,
        "source": meta.get("source", "tavily"),
    }


def make_document_tool(
    settings: Settings | None = None,
    *,
    retriever_factory: Callable[[Settings], dict[str, BaseRetriever]] | None = None,
    budget: CallBudget | None = None,
    cache_dir: Path | None = None,
    live_client: Any = None,
) -> StructuredTool:
    """构造供 research 子图调用的检索工具；模式差异只在这层。

    `retriever_factory` / `live_client` 是**离线编排注入点**：传入时跳过
    `AsyncTavilyClient` 构造与凭据解析，供测试和 CI 在 0 次真实调用下验证链路。
    生产 live 路径不传这些参数，凭据只从环境变量解析。
    """
    s = settings or get_settings()

    if s.app.mode == "fixture":
        store = load_fixture_store(s)

        @tool
        async def fetch_company_documents(
            company: str,
            sections: list[str],
            round_no: int,
            queries: list[str] | None = None,
        ) -> dict[str, list[dict[str, Any]]]:
            """按公司名、栏目列表和回退轮次取回检索文档。返回 {栏目: [文档]}。

            传 `queries` 时改为「按给定 query 检索」：sections 必须只有一个栏目，
            用于行业栏目拿竞品名单去补检索。不传则走栏目默认 query。
            """
            result = store.fetch(company, sections, round_no, queries)
            logger.info(
                "fixture fetch company=%s round=%s sections=%s queries=%s docs=%s",
                company, round_no, sections, len(queries or []),
                sum(len(v) for v in result.values()),
            )
            return result

        return fetch_company_documents

    # ---- live：真实调用需三重 opt-in；dry-run 是独立的 0 请求预演路径 ----------
    live = s.retrieval.live
    if live.dry_run:
        # 预演：不需要 key、不需要放行额度、不构造 AsyncTavilyClient。
        # 只设 APP_MODE=live + TAVILY_DRY_RUN=true 即可看到完整 query 清单。
        active_budget = budget or CallBudget(0, dry_run=True)
        if not active_budget.dry_run:
            raise LiveRetrievalDisabled(
                "TAVILY_DRY_RUN=true 时注入的 CallBudget 必须也是 dry_run=True，"
                "拒绝用真实预算跑预演"
            )
        # 双重保险：即便调用方误传了真实 AsyncTavilyClient，预演里也一律替换成
        # 哨兵。这样「预算被改坏」和「client 被传错」单独发生都出不了网。
        live_client = DryRunSentinel()
    else:
        if not live.enabled or live.max_calls_per_run <= 0:
            raise LiveRetrievalDisabled(
                "Tavily 真实检索默认禁用（保护免费额度）。需同时设置 "
                "APP_MODE=live、TAVILY_LIVE_ENABLED=true、TAVILY_MAX_CALLS>0；"
                "仅查看会发哪些 query 请用 TAVILY_DRY_RUN=true"
            )
        active_budget = budget or CallBudget(live.max_calls_per_run, dry_run=False)

    if retriever_factory is not None:
        retrievers = retriever_factory(s)
    else:
        if live_client is None:
            creds = resolve_tavily_credentials()
            from tavily import AsyncTavilyClient

            live_client = AsyncTavilyClient(api_key=creds.resolved_key())
        retrievers = build_live_retrievers(
            s,
            client=live_client,
            budget=active_budget,
            cache_dir=cache_dir or resolve_live_cache_dir(s),
        )

    @tool
    async def fetch_company_documents(
        company: str,
        sections: list[str],
        round_no: int,
        queries: list[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """按公司名、栏目列表和回退轮次取回检索文档。返回 {栏目: [文档]}。

        传 `queries` 时改为「按给定 query 检索」：sections 必须只有一个栏目，
        用于行业栏目拿竞品名单去补检索。不传则走栏目默认 query。
        """
        if queries:
            if len(sections) != 1:
                raise ValueError("queries 模式一次只能查一个栏目")
            section = sections[0]
            retriever = retrievers.get(section)
            merged: list[dict[str, Any]] = []
            if retriever is not None:
                seen: set[str] = set()
                for q in queries:
                    docs = await retriever.ainvoke(q)
                    for d in docs:
                        item = _document_to_dict(d, section, round_no)
                        url = str(item.get("url") or "")
                        if url and url in seen:
                            continue
                        seen.add(url)
                        merged.append(item)
            logger.info(
                "live fetch-by-query company=%s section=%s queries=%s docs=%s budget=%s/%s",
                company, section, len(queries), len(merged),
                active_budget.calls_made, active_budget.max_calls,
            )
            return {section: merged}

        out: dict[str, list[dict[str, Any]]] = {}
        per_section = max(1, int(s.retrieval.queries_per_analyst))
        for section in sections:
            retriever = retrievers.get(section)
            if retriever is None:
                out[section] = []
                continue
            merged: list[dict[str, Any]] = []
            seen: set[str] = set()
            for variant in range(per_section):
                query = build_live_query(company, section, round_no, variant)
                docs = await retriever.ainvoke(query)
                for d in docs:
                    item = _document_to_dict(d, section, round_no)
                    url = str(item.get("url") or "")
                    if url and url in seen:
                        continue
                    seen.add(url)
                    merged.append(item)
            out[section] = merged
        logger.info(
            "live fetch company=%s round=%s sections=%s docs=%s budget=%s/%s cache_hits=%s",
            company, round_no, sections, sum(len(v) for v in out.values()),
            active_budget.calls_made, active_budget.max_calls, active_budget.cache_hits,
        )
        return out

    return fetch_company_documents
