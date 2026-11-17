"""S3 验收：V2 专项契约的字段约束。

本阶段只定义契约、不接入图、不切换 stub，所以这里只验证契约本身：
- extra="forbid" 生效（模型多塞字段必须报错，不能被静默吞掉）；
- 必填字段、枚举、URL 校验生效；
- Fact 可被嵌套复用（FundingRound.evidence / Competitor.evidence）。

全程离线、无模型调用。
"""

from __future__ import annotations

import pytest
from pydantic import HttpUrl, ValidationError

from graph.contracts import (
    ComparisonMatrix,
    Competitor,
    Fact,
    FundingRound,
    MatrixCell,
    RevenueInfo,
)


def _fact() -> Fact:
    return Fact(
        claim="2021 年完成 A 轮融资 5000 万美元",
        source_url="https://example.org/series-a",  # type: ignore[arg-type]
        confidence=0.9,
    )


def test_funding_round_happy_path() -> None:
    r = FundingRound(
        round_name="A 轮",
        amount="5000 万美元",
        announced_year="2021",
        investors=["红杉"],
        evidence=_fact(),
    )
    assert r.amount == "5000 万美元"  # 金额原样，不改写
    assert r.evidence.source_url == HttpUrl("https://example.org/series-a")


def test_funding_round_optional_fields_default() -> None:
    r = FundingRound(round_name="未披露轮次", amount="未披露金额", evidence=_fact())
    assert r.announced_year is None
    assert r.investors == []


def test_contracts_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        FundingRound(
            round_name="A 轮",
            amount="5000 万美元",
            evidence=_fact(),
            hallucinated_field="模型编的",  # type: ignore[call-arg]
        )


def test_competitor_tier_is_enum() -> None:
    c = Competitor(name="Obsidian", tier="direct", evidence=_fact())
    assert c.tier == "direct"
    with pytest.raises(ValidationError):
        Competitor(name="Obsidian", tier="unknown", evidence=_fact())  # type: ignore[arg-type]


def test_revenue_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        RevenueInfo(model="按席位订阅")  # type: ignore[call-arg]


def test_matrix_cell_url_validation() -> None:
    cell = MatrixCell(
        dimension="部署", company="Notion", text="云端协作", source_url="https://example.org/a"  # type: ignore[arg-type]
    )
    assert cell.text == "云端协作"
    with pytest.raises(ValidationError):
        MatrixCell(dimension="部署", company="Notion", text="x", source_url="not-a-url")  # type: ignore[arg-type]


def test_comparison_matrix_records_missing_without_fabrication() -> None:
    m = ComparisonMatrix(
        company="Notion",
        cells=[
            MatrixCell(
                dimension="部署", company="Notion", text="云端协作",
                source_url="https://example.org/a",  # type: ignore[arg-type]
            )
        ],
        missing=["定价"],  # 无依据的维度只记录，不脑补一格
    )
    assert m.missing == ["定价"]
    assert len(m.cells) == 1


def test_all_new_contracts_reject_extra() -> None:
    payload = dict(
        dimension="部署", company="Notion", text="云端协作",
        source_url="https://example.org/a", fabricated_conclusion="Notion 更高端",  # type: ignore[arg-type]
    )
    with pytest.raises(ValidationError):
        MatrixCell(**payload)
