"""fixture 样本契约测试（S3 前置）。

`config/settings.yaml` 与 `AGENT.md` 第 4 节都承诺了 `evals/fixtures/tavily_responses.json`，
S2 复查时该文件缺失。这里锁住三类样本的形状，保证 S3 的回退/降级用例
不是靠临时拼数据，且阈值一律从配置读（禁止硬编码魔法数字）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config.loader import get_settings

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "evals" / "fixtures" / "tavily_responses.json"


def _load() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _usable(docs: list[dict[str, Any]], min_score: float) -> list[dict[str, Any]]:
    return [d for d in docs if d.get("url") and float(d.get("score", 0)) >= min_score]


def test_fixture_file_exists_with_three_cases() -> None:
    data = _load()
    assert data["schema_version"] == 1
    assert set(data["cases"]) == {"sufficient", "sparse", "empty"}
    assert "合成" in data["note"], "必须声明样本是合成的，避免被误当作真实数据"


def test_every_doc_has_url_title_and_score() -> None:
    for case_name, case in _load()["cases"].items():
        for i, round_ in enumerate(case["rounds"]):
            for section, docs in round_.items():
                for doc in docs:
                    assert doc.get("url"), f"{case_name}/round{i}/{section} 缺 url"
                    assert doc.get("title"), f"{case_name}/round{i}/{section} 缺 title"
                    assert isinstance(doc.get("score"), (int, float))
                    assert doc.get("content"), f"{case_name}/round{i}/{section} 缺 content"


def test_sufficient_passes_in_first_round() -> None:
    s = get_settings()
    need = s.graph.evidence.min_docs_per_section
    threshold = s.graph.evidence.min_relevance_score
    first = _load()["cases"]["sufficient"]["rounds"][0]
    for section in s.graph.sections:
        assert len(_usable(first[section], threshold)) >= need, f"{section} 应首轮即充分"


def test_sparse_is_insufficient_first_then_recovers() -> None:
    s = get_settings()
    need = s.graph.evidence.min_docs_per_section
    threshold = s.graph.evidence.min_relevance_score
    rounds = _load()["cases"]["sparse"]["rounds"]
    assert len(_usable(rounds[0]["company"], threshold)) < need, "sparse 首轮必须触发回退"
    accumulated = _usable(rounds[0]["company"], threshold)
    accumulated += _usable(rounds[1]["company"], threshold)
    urls = {d["url"] for d in accumulated}
    assert len(urls) >= need, "sparse 第二轮必须补足且与首轮 URL 不重复"


def test_empty_never_produces_usable_company_docs() -> None:
    s = get_settings()
    threshold = s.graph.evidence.min_relevance_score
    for i, round_ in enumerate(_load()["cases"]["empty"]["rounds"]):
        assert not _usable(round_["company"], threshold), f"empty 第 {i} 轮不应有合格文档"
