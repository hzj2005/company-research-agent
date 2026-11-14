"""S7：把 config/eval.yaml 收紧成强类型评测配置。

`config.loader.load_eval_config()` 在 S1 只做 YAML 语法解析，返回裸 dict；
本模块按 AGENT.md 第 8 条补上 Pydantic 校验（`extra="forbid"`），
写错字段/少字段会当场失败，而不是让 A/B 开关静默失效后仍出一份分数。

路径解析统一相对仓库根，避免从不同工作目录调用时读不到 golden/scorecard。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field

from config.loader import DEFAULT_EVAL_PATH, ROOT, expand_env


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetConfig(_Strict):
    path: str
    provenance: Literal["synthetic-fixture-derived", "human-verified", "live-derived"]
    min_companies: int = Field(ge=1)
    facts_per_company: int = Field(ge=1)
    fields: list[str] = Field(default_factory=list)


class FixtureConfig(_Strict):
    cases: list[str] = Field(min_length=1)


class ThresholdsConfig(_Strict):
    fact_accuracy_min: float = Field(ge=0, le=1)
    citation_traceability_min: float = Field(ge=0, le=1)
    hallucination_rate_max: float = Field(ge=0, le=1)
    abstain_rate_min: float = Field(ge=0, le=1)
    max_avg_retry_rounds: float = Field(ge=0)


class ABTestConfig(_Strict):
    name: str = Field(min_length=1)
    overrides: dict[str, Any] = Field(default_factory=dict)


class CIConfig(_Strict):
    scorecard_path: str
    fail_on_regression: bool
    regression_tolerance: float = Field(ge=0, le=1)
    protected_metrics: list[str] = Field(min_length=1)


class EvalConfig(_Strict):
    dataset: DatasetConfig
    fixture: FixtureConfig
    metrics: list[str] = Field(min_length=1)
    metric_direction: dict[str, Literal["higher", "lower"]]
    non_deterministic_metrics: list[str] = Field(default_factory=list)
    thresholds: ThresholdsConfig
    ab_tests: list[ABTestConfig] = Field(min_length=1)
    ci: CIConfig

    def deterministic_metrics(self) -> list[str]:
        """可复现、可跨机器比对的指标（排除负载相关项）。"""
        skipped = set(self.non_deterministic_metrics)
        return [m for m in self.metrics if m not in skipped]


def load_eval_config(
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> EvalConfig:
    p = Path(path) if path else DEFAULT_EVAL_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{p} 顶层必须是 mapping")
    return EvalConfig.model_validate(expand_env(raw, environ))


def resolve_path(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (ROOT / p).resolve()


def dataset_path(cfg: EvalConfig) -> Path:
    return resolve_path(cfg.dataset.path)


def scorecard_path(cfg: EvalConfig) -> Path:
    return resolve_path(cfg.ci.scorecard_path)
