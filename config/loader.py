"""配置加载：`.env` → 环境变量占位展开 → Pydantic 校验 → 强类型 Settings。

设计约定（AGENT.md 第 5、8 条）：
- 业务代码禁止直接读 yaml / os.environ，统一用 `get_settings()`。
- `fixture` / `live` 切换只允许改 `.env`，不得在节点里散落模式判断。
- 所有阈值、上限、模型名、路径来自本模块，禁止硬编码魔法数字。

用法：
    from config.loader import get_settings, resolve_checkpoint_path, build_thread_id
    settings = get_settings()
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SETTINGS_PATH = ROOT / "config" / "settings.yaml"
DEFAULT_EVAL_PATH = ROOT / "config" / "eval.yaml"
DEFAULT_ENV_PATH = ROOT / ".env"

# 匹配 ${VAR} 与 ${VAR:-default}
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand_env(value: Any, environ: Mapping[str, str] | None = None) -> Any:
    """递归展开字符串里的 ${VAR:-default}；环境变量优先于 yaml 默认值。"""
    env = environ if environ is not None else os.environ

    def _sub(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        return env.get(name, default if default is not None else "")

    if isinstance(value, str):
        return _ENV_PATTERN.sub(_sub, value)
    if isinstance(value, dict):
        return {k: expand_env(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v, env) for v in value]
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppConfig(_Strict):
    mode: Literal["fixture", "live"] = "fixture"
    log_level: str = "INFO"


class EvidenceConfig(_Strict):
    min_relevance_score: float = Field(ge=0.0, le=1.0)
    min_docs_per_section: int = Field(ge=0)
    require_source_url: bool = True


class DegradeConfig(_Strict):
    enabled: bool = True
    message: str


class GraphConfig(_Strict):
    max_retry: int = Field(ge=0, le=10)
    sections: list[str]
    evidence: EvidenceConfig
    degrade: DegradeConfig
    checkpointer: Literal["sqlite", "postgres"] = "sqlite"
    dsn: str
    postgres_dsn: str = ""
    thread_id_template: str


class RerankConfig(_Strict):
    enabled: bool
    strategy: str


class RetrievalConfig(_Strict):
    queries_per_analyst: int = Field(ge=1)
    max_results_per_query: int = Field(ge=1)
    search_depth: str
    topics: dict[str, str]
    rerank: RerankConfig


class FixtureConfig(_Strict):
    stub: bool
    responses_path: str


class ModelsConfig(_Strict):
    temperature: float
    max_retries: int = Field(ge=0)
    roles: dict[str, str]
    fixture: FixtureConfig


class FeaturesConfig(_Strict):
    self_correction: bool
    structured_output: bool
    inline_citations: bool
    human_review: bool
    auto_approve_review: bool


class ReportConfig(_Strict):
    headings: list[str]
    max_references: int = Field(ge=1)


class Settings(_Strict):
    app: AppConfig
    graph: GraphConfig
    retrieval: RetrievalConfig
    models: ModelsConfig
    features: FeaturesConfig
    report: ReportConfig


def load_settings(
    path: str | Path | None = None,
    *,
    env_file: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    """加载并校验主配置。env_file 缺省读仓库根 `.env`（不存在则忽略）。"""
    load_dotenv(env_file or DEFAULT_ENV_PATH, override=False)
    p = Path(path) if path else DEFAULT_SETTINGS_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{p} 顶层必须是 mapping，实际为 {type(raw).__name__}")
    return Settings.model_validate(expand_env(raw, environ))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例。测试要覆盖配置时请直接调用 load_settings(environ=...)。"""
    return load_settings()


def load_eval_config(path: str | Path | None = None) -> dict[str, Any]:
    """评测配置的原始 dict；S7 实现 evals/run_eval.py 时再收紧为 Pydantic model。"""
    p = Path(path) if path else DEFAULT_EVAL_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{p} 顶层必须是 mapping")
    return expand_env(raw)


def apply_overrides(settings: Settings, overrides: Mapping[str, Any]) -> Settings:
    """把 `config/eval.yaml` 里 `ab_tests[].overrides` 的点号路径应用到 Settings 副本。

    例：`{"features.self_correction": False, "retrieval.max_results_per_query": 1}`。
    未知字段或中间路径不是对象时直接抛错，避免 A/B 开关静默失效却仍出分。
    返回新对象，不修改传入的 settings（纯函数，便于多组实验复用同一基线）。
    """
    data = settings.model_dump(mode="python")
    for dotted, value in overrides.items():
        parts = dotted.split(".")
        cursor: dict[str, Any] = data
        for part in parts[:-1]:
            nxt = cursor.get(part)
            if not isinstance(nxt, dict):
                raise ValueError(f"无效的 overrides 路径 {dotted!r}：{part!r} 不是对象")
            cursor = nxt
        leaf = parts[-1]
        if leaf not in cursor:
            raise ValueError(f"无效的 overrides 路径 {dotted!r}：未知字段 {leaf!r}")
        cursor[leaf] = value
    return Settings.model_validate(data)


def resolve_checkpoint_path(settings: Settings | None = None) -> Path:
    """把 `sqlite:///./data/checkpoints.db` 解析成真实文件路径，并确保父目录存在。"""
    s = settings or get_settings()
    if s.graph.checkpointer == "postgres":
        raise NotImplementedError(
            "PostgresSaver 留到 S8 真实实测阶段；当前请设 CHECKPOINTER=sqlite"
        )
    dsn = s.graph.dsn
    prefix = "sqlite:///"
    if not dsn.startswith(prefix):
        raise ValueError(f"不支持的 sqlite dsn: {dsn!r}（应为 sqlite:///相对路径）")
    relative = dsn[len(prefix):]
    path = (ROOT / relative).resolve() if not Path(relative).is_absolute() else Path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def build_thread_id(
    company: str,
    *,
    settings: Settings | None = None,
    on_date: _dt.date | None = None,
) -> str:
    """按配置模板生成 thread_id；禁止在业务代码里硬编码或留空。"""
    s = settings or get_settings()
    day = (on_date or _dt.date.today()).isoformat()
    return s.graph.thread_id_template.format(company=company, date=day)
