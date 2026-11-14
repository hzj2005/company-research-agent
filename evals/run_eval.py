"""S7 评测台：一条命令跑全量 → 出 scorecard → 与上一版比对 → 定位退化用例。

    uv run python -m evals.run_eval
    uv run python -m evals.run_eval --compare evals/scorecard.json --output evals/scorecard.next.json
    uv run python -m evals.run_eval --ab self_correction_off

⚠️ 额度护栏（对应用户「谨慎使用 Tavily 免费额度」的要求）：
1. 只在 `APP_MODE=fixture` 下运行，其它模式直接拒绝启动；
2. 运行期间给 `socket.connect` 装守卫，非回环连接立即抛错。
   所以本脚本**不可能**消耗任何 Tavily / 模型额度，即使配置被误改。

⚠️ 指标边界：全部指标只在合成 fixture 语料上有意义，`provenance` 写进 scorecard。
真实准确率 / 延迟 / 成本需要 live 语料与人工核验 golden（S8）。
scorecard 不含时间戳，确定性指标跨机器可复现；`p95_latency_ms` 被列为
非确定性指标，不参与 CI 回归比对与 A/B 差异判定。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import socket
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from capabilities.retrieval import resolve_fixture_path
from config.loader import (
    ROOT,
    DEFAULT_EVAL_PATH,
    DEFAULT_SETTINGS_PATH,
    Settings,
    apply_overrides,
    get_settings,
)
from evals.config import EvalConfig, dataset_path, load_eval_config, scorecard_path
from evals.metrics import (
    GoldenSet,
    aggregate_metrics,
    check_gate,
    compare_scorecards,
    compute_ab_effect,
    evaluate_case,
    load_golden,
)
from graph.run import run_research

SCHEMA_VERSION = 1
DISCLAIMER = (
    "fixture 合成语料上的可机器核验契约指标，不是真实世界准确率/成本。"
    "citation_traceability 为词法包含代理判定，不等价语义蕴含；"
    "真实指标需 APP_MODE=live + 人工核验 golden（S8）。"
)


@contextmanager
def eval_offline_guard() -> Iterator[list[Any]]:
    """禁网守卫：回环放行（Windows asyncio 需要），外部连接记录并抛错。"""
    original = socket.socket.connect
    attempts: list[Any] = []

    def guarded(self: socket.socket, address: Any, *args: Any, **kwargs: Any) -> Any:
        host = str(address[0]) if isinstance(address, tuple) and address else str(address)
        if host.startswith("127.") or host in ("::1", "localhost"):
            return original(self, address, *args, **kwargs)
        attempts.append(address)
        raise AssertionError(f"S7 评测禁止外部连接：{address!r}（保护 Tavily/模型额度）")

    socket.socket.connect = guarded  # type: ignore[method-assign]
    try:
        yield attempts
    finally:
        socket.socket.connect = original  # type: ignore[method-assign]


def _hash_files(paths: Iterable[Path]) -> str:
    """按「相对仓库根的 posix 路径」排序后逐文件 hash，保证 Windows/Linux 一致。"""
    entries: list[tuple[str, Path]] = []
    for p in set(paths):
        rp = p.resolve()
        try:
            label = rp.relative_to(ROOT).as_posix()
        except ValueError:
            label = rp.name
        entries.append((label, rp))
    h = hashlib.sha256()
    for label, rp in sorted(entries):
        h.update(label.encode("utf-8"))
        h.update(rp.read_bytes())
    return h.hexdigest()[:16]


# 影响一次评测结果的代码面：图、能力层、持久化、配置解析、评测内核本身。
# 不含 tests/ 与 docs/（改测试/文档不改变分数），也不含上游 backend/（评测不经过它）。
_CODE_DIRS = ("graph", "capabilities", "persistence")
_CODE_FILES = (
    "config/loader.py",
    "evals/build_golden.py",
    "evals/config.py",
    "evals/metrics.py",
    "evals/run_eval.py",
)


def code_sha256() -> str:
    paths: list[Path] = [
        p
        for d in _CODE_DIRS
        for p in (ROOT / d).rglob("*.py")
        if "__pycache__" not in p.parts
    ]
    paths += [ROOT / f for f in _CODE_FILES]
    return _hash_files(paths)


def inputs_sha256(
    cfg: EvalConfig,
    settings: Settings,
    eval_config_path: str | Path | None = None,
) -> str:
    """锁定四份数据输入；代码变化由 `code_sha256()` 单独锁定（S7 复查 P2/P6）。"""
    eval_path = Path(eval_config_path) if eval_config_path else DEFAULT_EVAL_PATH
    return _hash_files(
        {
            DEFAULT_SETTINGS_PATH,
            eval_path,
            dataset_path(cfg),
            resolve_fixture_path(settings),
        }
    )


async def _run_group(
    name: str,
    overrides: dict[str, Any],
    cfg: EvalConfig,
    base: Settings,
    golden: GoldenSet,
    case_by_key: dict[str, dict[str, Any]],
    tmp: Path,
) -> dict[str, Any]:
    settings = apply_overrides(base, overrides)
    results: list[dict[str, Any]] = []
    for case_key in cfg.fixture.cases:
        item = case_by_key[case_key]
        db = tmp / f"{name}__{case_key}.db"
        start = time.perf_counter()
        state, trace = await run_research(
            item["company"], settings, db, collect_trace=True
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        if "_interrupt" in state:
            raise RuntimeError(
                f"{name}/{case_key} 停在 interrupt：评测台要求无人值守，"
                "请保持 features.human_review=false 或 auto_approve_review=true"
            )
        results.append(
            evaluate_case(
                case_item=item,
                state=state,
                trace=trace,
                elapsed_ms=elapsed_ms,
                golden=golden,
                settings=settings,
            )
        )
    metrics, counts = aggregate_metrics(results, cfg)
    return {
        "status": "baseline" if name == "baseline" else "ab",
        "overrides": dict(overrides),
        "metrics": metrics,
        "counts": counts,
        "cases": results,
        "gate": check_gate(metrics, cfg) if name == "baseline" else None,
    }


def build_scorecard(
    cfg: EvalConfig,
    base: Settings,
    golden: GoldenSet,
    ab_names: list[str] | None = None,
    eval_config_path: str | Path | None = None,
) -> tuple[dict[str, Any], list[Any]]:
    """跑全部 A/B 组并组装 scorecard；返回 (scorecard, 外部连接尝试列表)。"""
    if base.app.mode != "fixture":
        raise RuntimeError(
            "S7 评测台只在 APP_MODE=fixture 下运行（0 次真实调用）。"
            "live 实测属于 S8，需模型 key + 用户明确放行 Tavily 额度。"
        )
    # 健全性：空 golden / 样本不足时拒绝出分，避免"没东西可测"也拿到满分（S7 复查 P5）
    if len(golden.cases) < cfg.dataset.min_companies:
        raise ValueError(
            f"golden 只有 {len(golden.cases)} 个 case，"
            f"少于 config/eval.yaml 的 min_companies={cfg.dataset.min_companies}"
        )
    if not golden.claims or not golden.abstains:
        raise ValueError("golden 必须同时包含 claim 与 abstain 样本，拒绝产出可能假满分的 scorecard")

    case_by_key = {c["case"]: c for c in golden.cases}
    missing = [k for k in cfg.fixture.cases if k not in case_by_key]
    if missing:
        raise ValueError(f"config/eval.yaml 里的 case 不在 golden 中：{missing}")

    by_name = {ab.name: ab.overrides for ab in cfg.ab_tests}
    if ab_names:
        unknown = [n for n in ab_names if n not in by_name]
        if unknown:
            raise ValueError(f"未知的 A/B 组名 {unknown}；可选：{sorted(by_name)}")
    selected = ["baseline"]
    for ab in cfg.ab_tests:
        if ab.name == "baseline":
            continue
        if ab_names is None or ab.name in ab_names:
            selected.append(ab.name)

    with tempfile.TemporaryDirectory(prefix="s7-eval-") as td:
        tmp = Path(td)
        with eval_offline_guard() as attempts:

            async def _all() -> dict[str, Any]:
                runs: dict[str, Any] = {}
                for name in selected:
                    runs[name] = await _run_group(
                        name, by_name[name], cfg, base, golden, case_by_key, tmp
                    )
                return runs

            runs = asyncio.run(_all())
        external_attempts = list(attempts)

    # 硬保证：只要守卫拦到过一次外部连接，本次结果就作废，不允许出一份"看起来 0 调用"的分数
    if external_attempts:
        raise RuntimeError(
            f"评测期间检测到 {len(external_attempts)} 次外部连接尝试，结果作废：{external_attempts[:3]}"
        )

    baseline = runs["baseline"]["metrics"]
    effects = {
        name: compute_ab_effect(runs[name]["metrics"], baseline, cfg)
        for name in selected
        if name != "baseline"
    }
    failed_case_ids = sorted(
        {
            f"{name}:{item_id}"
            for name, run in runs.items()
            for case in run["cases"]
            for item_id in case["failures"]
        }
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "provenance": cfg.dataset.provenance,
        "mode": base.app.mode,
        "disclaimer": DISCLAIMER,
        "inputs_sha256": inputs_sha256(cfg, base, eval_config_path),
        "code_sha256": code_sha256(),
        "external_calls": {
            "tavily": 0,
            "llm": 0,
            "blocked_connection_attempts": len(external_attempts),
        },
        "dataset": {
            "path": str(dataset_path(cfg).relative_to(ROOT)).replace("\\", "/"),
            "cases": len(golden.cases),
            "claim_items": len(golden.claims),
            "abstain_items": len(golden.abstains),
            "meta": {k: golden.meta[k] for k in ("generated_by", "provenance", "settings_fingerprint")},
        },
        "config": {
            "metric_direction": dict(cfg.metric_direction),
            "non_deterministic_metrics": list(cfg.non_deterministic_metrics),
            "thresholds": cfg.thresholds.model_dump(),
            "protected_metrics": list(cfg.ci.protected_metrics),
            "regression_tolerance": cfg.ci.regression_tolerance,
        },
        "runs": runs,
        "ab_effects": effects,
        "summary": {
            "baseline_gate_passed": bool(runs["baseline"]["gate"]["passed"]),
            "groups_run": selected,
            "failed_case_ids": failed_case_ids,
        },
    }, external_attempts


def _print_summary(card: dict[str, Any], regression: dict[str, Any] | None) -> None:
    m = card["runs"]["baseline"]["metrics"]
    d = card["dataset"]
    print(f"S7 scorecard  mode={card['mode']}  provenance={card['provenance']}")
    print(
        f"dataset: {d['cases']} cases / {d['claim_items']} claim items / "
        f"{d['abstain_items']} abstain items  inputs={card['inputs_sha256']}"
    )
    print(
        "baseline: "
        f"fact_accuracy={m['fact_accuracy']:.3f}  "
        f"citation_traceability={m['citation_traceability']:.3f}  "
        f"abstain_rate={m['abstain_rate']:.3f}  "
        f"hallucination_rate={m['hallucination_rate']:.3f}  "
        f"self_correction={m['self_correction_success']}  "
        f"avg_retry={m['avg_retry_rounds']:.3f}"
    )
    gate = card["runs"]["baseline"]["gate"]
    print(f"  gate: {'PASS' if gate['passed'] else 'FAIL'}  {gate['violations'] or ''}")
    print("A/B:")
    for name, effect in card["ab_effects"].items():
        print(f"  {name:<22} {effect['status']:<10} {effect['delta_vs_baseline']}")
    ids = card["summary"]["failed_case_ids"]
    print(f"failed case ids: {ids[:8] if ids else '[]'}{' ...' if len(ids) > 8 else ''}")
    if regression is not None:
        print(
            f"regression vs previous: {'PASS' if regression['passed'] else 'FAIL'}"
            f"  degraded_case_ids={regression['degraded_case_ids']}"
        )
        for v in regression["violations"]:
            print(f"  - {v}")
    print(f"external calls: {card['external_calls']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S7 评测台：golden set + 指标 + A/B + CI 回归")
    parser.add_argument("--config", default=None, help="评测配置路径，默认 config/eval.yaml")
    parser.add_argument("--golden", default=None, help="golden.jsonl 路径，覆盖配置")
    parser.add_argument("--output", default=None, help="scorecard 输出路径，默认配置里的 ci.scorecard_path")
    parser.add_argument(
        "--compare", nargs="?", const="__default__", default=None,
        help="与上一版 scorecard 比对；省略路径则用配置里的 ci.scorecard_path",
    )
    parser.add_argument("--ab", action="append", default=None, help="只跑指定 A/B 组（baseline 始终跑）")
    parser.add_argument("--baseline-only", action="store_true", help="只跑 baseline，用于快速自检")
    args = parser.parse_args(argv)
    if args.baseline_only and args.ab:
        parser.error("--baseline-only 与 --ab 不能同时使用")

    cfg = load_eval_config(args.config)
    golden = load_golden(args.golden or dataset_path(cfg))
    base = get_settings()

    prev: dict[str, Any] | None = None
    if args.compare is not None:
        prev_path = scorecard_path(cfg) if args.compare == "__default__" else Path(args.compare)
        if prev_path.exists():
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
        else:
            print(f"[WARN] 上一版 scorecard 不存在：{prev_path}，跳过回归比对（首次运行属正常）")

    card, _ = build_scorecard(
        cfg, base, golden,
        ab_names=[] if args.baseline_only else args.ab,
        eval_config_path=args.config,
    )
    regression = (
        compare_scorecards(prev, card, cfg) if prev is not None else None
    )
    if regression is not None:
        card["regression"] = regression

    out = Path(args.output) if args.output else scorecard_path(cfg)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(card, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _print_summary(card, regression)
    print(f"[OK] scorecard -> {out}")

    failed = not card["runs"]["baseline"]["gate"]["passed"]
    if regression is not None and cfg.ci.fail_on_regression and not regression["passed"]:
        failed = True
    if failed:
        print("[FAIL] 门禁或回归比对未通过")
        return 1
    print("[OK] 评测通过（0 次真实外部调用）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
