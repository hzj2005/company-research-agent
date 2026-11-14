"""S5-B 复查补账回归：简报后端 client 生命周期 + stub 契约。

对应两条实锤问题：
1. `make_briefing_backend()` 的 `httpx.AsyncClient` 在生产路径从未 `aclose()`
   （复查实测：5 次运行 → 5 个未关闭）；
2. `ACTION_PLAN` 9.4 承诺 `Fact.confidence=score`，代码却硬编码 0.9。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from capabilities.briefing import (
    _score_as_confidence,
    briefing_backend_scope,
    make_briefing_backend,
)
from capabilities.structured import extract_section_brief
from config.loader import get_settings
from graph.run import run_research


def test_production_paths_close_every_http_client(tmp_path: Path) -> None:
    """CLI 与 FastAPI 后台任务都必须在图跑完后关掉自己创建的 client。"""
    import application
    from backend.classes.state import job_status

    created: list[httpx.AsyncClient] = []
    original_init = httpx.AsyncClient.__init__

    def counting(self: httpx.AsyncClient, *args: object, **kwargs: object) -> None:
        original_init(self, *args, **kwargs)
        created.append(self)

    with patch.object(httpx.AsyncClient, "__init__", counting):
        for i in range(3):
            asyncio.run(run_research("Notion", get_settings(), tmp_path / f"cli{i}.db"))

        jid = "s5-audit-lifecycle-1"
        job_status[jid] = {"status": "pending", "company": "Notion"}
        asyncio.run(
            application.process_research(
                jid,
                application.ResearchRequest(company="Notion"),
                db_path=tmp_path / "api.db",
            )
        )
        assert job_status[jid]["status"] == "completed"

    assert len(created) >= 4, "探针必须真的观测到 client 创建"
    assert all(c.is_closed for c in created), "生产路径不得泄漏 httpx.AsyncClient"


def test_scope_closes_client_even_when_graph_raises() -> None:
    """`finally` 而非正常路径才关：失败请求同样不能泄漏。"""
    seen: list[httpx.AsyncClient | None] = []

    async def boom() -> None:
        async with briefing_backend_scope(get_settings()) as backend:
            seen.append(backend.client)
            raise RuntimeError("simulated graph failure")

    with pytest.raises(RuntimeError, match="simulated"):
        asyncio.run(boom())
    assert seen and seen[0] is not None and seen[0].is_closed


def test_fixture_stub_confidence_equals_document_score() -> None:
    """兑现 9.4：confidence 来自文档 score，且 score 必须真的出现在 prompt 里。"""
    settings = get_settings()
    backend = make_briefing_backend(settings)
    try:
        docs = [
            {"url": "https://e.org/low", "title": "low", "content": "低分事实", "score": 0.41},
            {"url": "https://e.org/high", "title": "high", "content": "高分事实", "score": 0.93},
        ]
        result = asyncio.run(
            extract_section_brief(
                backend.chain, section="company", company="X", docs=docs, settings=settings
            )
        )
        assert [f.confidence for f in result.brief.facts] == [0.41, 0.93]
        assert '"score"' in backend.seen[0], "score 必须进 prompt，不能由 mock 硬编码"
    finally:
        asyncio.run(backend.aclose())

    # 非数值 / 越界都不伪造置信度，夹到契约区间
    assert _score_as_confidence({"score": "not-a-number"}) == 0.0
    assert _score_as_confidence({"score": 3.7}) == 1.0
    assert _score_as_confidence({}) == 0.0
