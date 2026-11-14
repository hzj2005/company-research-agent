"""S2：配置加载与环境变量契约的回归测试。"""

from __future__ import annotations

import datetime

from config.loader import (
    build_thread_id,
    expand_env,
    load_eval_config,
    load_settings,
    resolve_checkpoint_path,
)


def test_expand_env_uses_environ_before_default() -> None:
    raw = {
        "mode": "${APP_MODE:-fixture}",
        "model": "${OPENROUTER_MODEL:-google/gemini-3.8-flash}",
        "nested": ["${EMPTY_VAR:-}", 2],
    }
    got = expand_env(raw, {"APP_MODE": "live", "EMPTY_VAR": "filled"})
    assert got == {
        "mode": "live",
        "model": "google/gemini-3.8-flash",
        "nested": ["filled", 2],
    }


def test_load_settings_real_yaml() -> None:
    s = load_settings(environ={"APP_MODE": "fixture"})
    assert s.app.mode == "fixture"
    assert s.graph.max_retry == 2
    assert s.graph.sections == ["company", "industry", "financial", "news"]
    assert s.graph.evidence.min_relevance_score == 0.4
    assert s.graph.evidence.min_docs_per_section == 2
    assert s.graph.checkpointer == "sqlite"
    assert s.features.self_correction is True
    assert s.report.headings[-1] == "References"


def test_env_overrides_yaml_defaults() -> None:
    s = load_settings(environ={"APP_MODE": "live", "LOG_LEVEL": "DEBUG"})
    assert s.app.mode == "live"
    assert s.app.log_level == "DEBUG"


def test_resolve_checkpoint_path_and_thread_id() -> None:
    s = load_settings(environ={"APP_MODE": "fixture"})
    p = resolve_checkpoint_path(s)
    assert p.name == "checkpoints.db"
    assert p.parent.is_dir()
    assert build_thread_id("Notion", settings=s) == "Notion:" + datetime.date.today().isoformat()


def test_eval_config_parses() -> None:
    d = load_eval_config()
    assert {"dataset", "metrics", "ab_tests", "ci"} <= set(d.keys())
