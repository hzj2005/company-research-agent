"""S2 / 补账：配置加载、环境变量契约与 A/B overrides 的回归测试。"""

from __future__ import annotations

import datetime

import pytest

from config.loader import (
    apply_overrides,
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


def test_feature_switches_are_env_overridable() -> None:
    """补账：features.* 之前是硬编码 true，命令行关不掉 A/B 开关。"""
    s = load_settings(
        environ={
            "APP_MODE": "fixture",
            "FEATURES_SELF_CORRECTION": "false",
            "FEATURES_INLINE_CITATIONS": "false",
        }
    )
    assert s.features.self_correction is False
    assert s.features.inline_citations is False
    assert s.features.structured_output is True, "未覆盖的开关保留默认"


def test_apply_overrides_updates_nested_keys_without_mutating() -> None:
    s = load_settings(environ={"APP_MODE": "fixture"})
    out = apply_overrides(
        s,
        {
            "features.self_correction": False,
            "retrieval.max_results_per_query": 1,
            "graph.max_retry": 3,
        },
    )
    assert out.features.self_correction is False
    assert out.retrieval.max_results_per_query == 1
    assert out.graph.max_retry == 3
    assert s.features.self_correction is True, "原对象不得被修改"


def test_apply_overrides_rejects_invalid_paths() -> None:
    s = load_settings(environ={"APP_MODE": "fixture"})
    for bad in (
        {"features.nope": True},
        {"features.self_correction.deep": True},
        {"nope": 1},
    ):
        with pytest.raises(ValueError):
            apply_overrides(s, bad)


def test_all_eval_ab_overrides_are_applicable() -> None:
    """eval.yaml 的 4 组 A/B 不能是写了没人解析的一纸空文。"""
    s = load_settings(environ={"APP_MODE": "fixture"})
    for ab in load_eval_config()["ab_tests"]:
        apply_overrides(s, ab["overrides"])  # 路径/字段非法会抛 ValueError


def test_resolve_checkpoint_path_and_thread_id() -> None:
    s = load_settings(environ={"APP_MODE": "fixture"})
    p = resolve_checkpoint_path(s)
    assert p.name == "checkpoints.db"
    assert p.parent.is_dir()
    assert build_thread_id("Notion", settings=s) == "Notion:" + datetime.date.today().isoformat()


def test_eval_config_parses() -> None:
    d = load_eval_config()
    assert {"dataset", "metrics", "ab_tests", "ci"} <= set(d.keys())
