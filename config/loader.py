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
from pydantic import BaseModel, ConfigDict, Field, SecretStr

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
    # 任务台账后端：memory 是进程内字典（测试/离线默认），postgres 才真落库。
    # 默认 memory 是刻意的——否则任何一次 pytest 都会去连数据库。
    job_store: Literal["memory", "postgres"] = "memory"


class EvidenceConfig(_Strict):
    min_relevance_score: float = Field(ge=0.0, le=1.0)
    min_docs_per_section: int = Field(ge=0)
    require_source_url: bool = True


class DegradeConfig(_Strict):
    # S4：删掉名不副实的 enabled —— 降级拒答是防幻觉红线，不允许关闭
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


class LiveRetrievalConfig(_Strict):
    """Tavily 免费额度护栏。默认值保证「装了 key 也调不动」。"""

    enabled: bool = False
    max_calls_per_run: int = Field(default=0, ge=0, le=100)
    dry_run: bool = False
    cache_dir: str = "./evals/cache/tavily"


class RetrievalConfig(_Strict):
    queries_per_analyst: int = Field(ge=1)
    max_results_per_query: int = Field(ge=1)
    search_depth: str
    topics: dict[str, str]
    rerank: RerankConfig
    live: LiveRetrievalConfig


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
    # S10：默认开启，可关掉做 A/B（关掉即回到「不消歧 / 不标冲突」的 S9 行为）
    entity_guard: bool = True
    conflict_annotation: bool = True


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


class LLMCredentials(_Strict):
    """模型凭据。刻意**不进 Settings**：避免 `model_dump()` / 日志把密钥带出去。"""

    provider: Literal["openrouter", "dashscope", "openai", "gemini"]
    api_key: SecretStr
    base_url: str | None = None

    def resolved_key(self) -> str:
        return self.api_key.get_secret_value()


class MissingLLMCredentials(RuntimeError):
    """live 模式缺 key。不允许悄悄降级回 fixture。"""


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# 阿里云百炼 DashScope 的 OpenAI 兼容端点；用 ChatOpenAI + base_url 接入，
# 不引入额外 SDK。可用 LLM_BASE_URL 覆盖（例如代理或其他兼容服务）。
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

_LLM_PROVIDERS: tuple[tuple[str, str, str | None], ...] = (
    ("openrouter", "OPENROUTER_API_KEY", OPENROUTER_BASE_URL),
    ("dashscope", "DASHSCOPE_API_KEY", DASHSCOPE_BASE_URL),
    ("openai", "OPENAI_API_KEY", None),
    ("gemini", "GEMINI_API_KEY", None),
)


def resolve_llm_credentials(
    environ: Mapping[str, str] | None = None,
) -> LLMCredentials:
    """按 OpenRouter → DashScope → OpenAI → Gemini 顺序解析凭据。

    - `LLM_PROVIDER` 可显式锁定 provider；锁定后**不**回退到其他 key（避免
      本机装了多个 key 时静默打到错误的服务商，白烧额度）。
    - `LLM_BASE_URL` 可覆盖 OpenAI 兼容端点的 base_url。
    - `environ` 显式传入时只读该映射（测试用，避免本机 `.env` 污染）；否则
      加载 `.env` 后读进程环境。缺 key 抛 `MissingLLMCredentials`，不静默回退。
    """
    if environ is None:
        load_dotenv(DEFAULT_ENV_PATH, override=False)
    env = environ if environ is not None else os.environ
    explicit = (env.get("LLM_PROVIDER") or "").strip().lower()
    known = [p for p, _, _ in _LLM_PROVIDERS]
    if explicit and explicit not in known:
        raise MissingLLMCredentials(
            f"未知 LLM_PROVIDER={explicit!r}；可选：{known}"
        )
    override_base = (env.get("LLM_BASE_URL") or "").strip()
    for provider, var, default_base in _LLM_PROVIDERS:
        if explicit and provider != explicit:
            continue
        raw = (env.get(var) or "").strip()
        if not raw:
            if explicit:
                raise MissingLLMCredentials(
                    f"LLM_PROVIDER={provider}，但缺少 {var}；拒绝回退到其他 provider"
                )
            continue
        return LLMCredentials(
            provider=provider,
            api_key=SecretStr(raw),
            base_url=override_base or default_base,
        )
    raise MissingLLMCredentials(
        "live 模式需要 OPENROUTER_API_KEY / DASHSCOPE_API_KEY / "
        "OPENAI_API_KEY / GEMINI_API_KEY 之一；"
        "无 key 请设 APP_MODE=fixture，不会自动回退"
    )


class TavilyCredentials(_Strict):
    """检索凭据。同样刻意不进 Settings，且不进任何日志。"""

    api_key: SecretStr

    def resolved_key(self) -> str:
        return self.api_key.get_secret_value()


class MissingTavilyCredentials(RuntimeError):
    """live 检索缺 key；不允许偷偷回退到 fixture。"""


def resolve_tavily_credentials(
    environ: Mapping[str, str] | None = None,
) -> TavilyCredentials:
    """只从环境变量 / `.env` 读 TAVILY_API_KEY；业务代码禁止直接 `os.getenv`。

    Windows 用户级变量需要重启终端/IDE 才会被进程继承；读不到时明确报错，
    不会自动改用请求体传入的 key，也不会悄悄回退 fixture。
    """
    if environ is None:
        load_dotenv(DEFAULT_ENV_PATH, override=False)
    env = environ if environ is not None else os.environ
    raw = (env.get("TAVILY_API_KEY") or "").strip()
    if not raw:
        raise MissingTavilyCredentials(
            "live 检索需要 TAVILY_API_KEY（建议只设在用户级环境变量）；"
            "非必要不调用，无 key 请保持 APP_MODE=fixture"
        )
    return TavilyCredentials(api_key=SecretStr(raw))


def resolve_live_cache_dir(settings: Settings) -> Path:
    p = Path(settings.retrieval.live.cache_dir)
    return p if p.is_absolute() else (ROOT / p).resolve()


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


def resolve_postgres_dsn(settings: Settings | None = None) -> str:
    """Postgres 的 DSN。空值当错误处理，绝不静默退回 SQLite 冒充持久化。

    示例：`postgresql://postgres:devpass@localhost:5432/research`
    """
    s = settings or get_settings()
    dsn = s.graph.postgres_dsn.strip()
    if not dsn:
        raise ValueError(
            "CHECKPOINTER=postgres（或 JOB_STORE=postgres）但 POSTGRES_DSN 为空；"
            "在 .env 里补一行 POSTGRES_DSN=postgresql://用户:密码@主机:5432/库名"
        )
    if not dsn.startswith(("postgresql://", "postgres://")):
        raise ValueError(f"POSTGRES_DSN 必须是 postgresql:// 开头，当前是 {dsn[:20]!r}")
    return dsn


def resolve_checkpoint_path(settings: Settings | None = None) -> Path:
    """把 `sqlite:///./data/checkpoints.db` 解析成真实文件路径，并确保父目录存在。"""
    s = settings or get_settings()
    if s.graph.checkpointer == "postgres":
        # 走 Postgres 时没有文件路径；这里明确指路，而不是返回一个没人用的路径
        raise ValueError(
            "checkpointer=postgres 没有文件路径，请改用 resolve_postgres_dsn()；"
            "SQLite 与 Postgres 是二选一，不会同时写两份"
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
