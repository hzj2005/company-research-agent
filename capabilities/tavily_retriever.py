"""S5-B 真实检索能力：`BaseRetriever` + 免费额度护栏。

设计红线（用户明确要求「非必要不调用、不要把免费额度跑没了」）：

1. **三重 opt-in**：`APP_MODE=live` + `TAVILY_LIVE_ENABLED=true` + `TAVILY_MAX_CALLS>0`。
   默认全关，即使本机装了 `TAVILY_API_KEY` 也调不动（检查在 `retrieval.py` 工具工厂）。
2. **硬预算**：`CallBudget` 进程内计数，用尽抛 `TavilyBudgetExceeded`，不重试、不绕过。
3. **缓存优先**：`(query, 参数)` 的 sha256 落盘；命中缓存直接返回 Document，**不扣额度**。
   这样 S8 若真调一次，之后可反复离线复现，不必再花额度。
4. **dry-run**：只记日志、不发请求、返回空结果，供确认「会发哪些 query」。
5. **测试注入**：`client` / `budget` / `cache_dir` 均可注入，测试用 fake client 与
   `BaseRetriever` 替身，**永不实例化 `AsyncTavilyClient`**。

`AsyncTavilyClient.search()` 的 live 行为在本阶段**未实测**（0 次真实调用）；
本模块只保证编排、护栏与 Document 契约正确。
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

logger = logging.getLogger(__name__)


class LiveRetrievalDisabled(RuntimeError):
    """三重 opt-in 未满足，禁止发起真实请求。"""


class TavilyBudgetExceeded(RuntimeError):
    """本次运行的真实调用额度已用尽。"""


class CallBudget:
    """进程内硬预算 + 可核对的计数器（不是配置文件里的一句声明）。"""

    def __init__(self, max_calls: int, *, dry_run: bool = False):
        self.max_calls = max_calls
        self.dry_run = dry_run
        self.calls_made = 0
        self.cache_hits = 0
        self.dry_runs = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_calls - self.calls_made)

    def consume(self, query: str) -> None:
        if self.remaining <= 0:
            raise TavilyBudgetExceeded(
                f"Tavily 调用预算已用尽（上限 {self.max_calls}）；"
                f"拒绝为 {query!r} 发起第 {self.calls_made + 1} 次真实请求"
            )
        self.calls_made += 1
        logger.warning(
            "Tavily 真实调用 %d/%d（剩余 %d）query=%s",
            self.calls_made, self.max_calls, self.remaining, query,
        )


def cache_key(query: str, *, section: str, max_results: int, search_depth: str, topic: str) -> str:
    raw = json.dumps(
        {"query": query, "section": section, "max_results": max_results,
         "search_depth": search_depth, "topic": topic},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def documents_from_results(results: Any, *, section: str) -> list[Document]:
    """把 Tavily `search()` 的 results 转成带可溯源元数据的 Document。

    无 URL 的结果直接丢弃（`graph.evidence.require_source_url` 的形式约束）；
    分数缺失记 0.0，交给后续 curate 的阈值判定，不在这里伪造高分。
    """
    docs: list[Document] = []
    for item in results or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        try:
            score = float(item.get("score", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        docs.append(
            Document(
                page_content=str(item.get("content") or ""),
                metadata={
                    "url": url,
                    "title": str(item.get("title") or ""),
                    "score": score,
                    "section": section,
                    "source": "tavily",
                },
            )
        )
    return docs


class TavilyRetriever(BaseRetriever):
    """每个栏目一个实例；只走 `ainvoke`，同步路径明确拒绝。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    client: Any = Field(default=None, exclude=True)
    budget: CallBudget = Field(exclude=True)
    cache_dir: Path = Field(exclude=True)
    section: str = "company"
    max_results: int = 3
    search_depth: str = "advanced"
    topic: str = "general"

    def _params(self, query: str) -> str:
        return cache_key(
            query,
            section=self.section,
            max_results=self.max_results,
            search_depth=self.search_depth,
            topic=self.topic,
        )

    def _cache_file(self, query: str) -> Path:
        return self.cache_dir / f"{self._params(query)}.json"

    def _load_cached(self, path: Path) -> list[Document]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [Document(page_content=d["page_content"], metadata=d["metadata"]) for d in raw]

    def _save_cache(self, path: Path, docs: list[Document]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                [{"page_content": d.page_content, "metadata": d.metadata} for d in docs],
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

    def _get_relevant_documents(self, query: str, **kwargs: Any) -> list[Document]:
        raise NotImplementedError(
            "TavilyRetriever 只提供 async 路径；请在 async 节点里用 await retriever.ainvoke(query)"
        )

    async def _aget_relevant_documents(self, query: str, **kwargs: Any) -> list[Document]:
        path = self._cache_file(query)
        if path.exists():
            self.budget.cache_hits += 1
            logger.info("Tavily 缓存命中（不扣额度）query=%s", query)
            return self._load_cached(path)

        if self.budget.dry_run:
            self.budget.dry_runs += 1
            logger.info("[dry-run] 将调用 Tavily，但已拦截：query=%s section=%s", query, self.section)
            return []

        self.budget.consume(query)
        response = await self.client.search(
            query=query,
            max_results=self.max_results,
            search_depth=self.search_depth,
            topic=self.topic,
        )
        results = response.get("results", []) if isinstance(response, dict) else []
        docs = documents_from_results(results, section=self.section)
        self._save_cache(path, docs)
        return docs


def build_live_retrievers(
    settings: Any,
    *,
    client: Any,
    budget: CallBudget,
    cache_dir: Path,
) -> dict[str, BaseRetriever]:
    """按栏目构造 retriever；每栏目每轮最多 1 次请求，避免无谓消耗额度。"""
    cfg = settings.retrieval
    return {
        section: TavilyRetriever(
            client=client,
            budget=budget,
            cache_dir=cache_dir,
            section=section,
            max_results=cfg.max_results_per_query,
            search_depth=cfg.search_depth,
            topic=cfg.topics.get(f"{section}_analyzer", "general"),
        )
        for section in settings.graph.sections
    }
