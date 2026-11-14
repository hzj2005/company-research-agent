"""S7 评测指标内核：纯函数，不跑图、不联网。

刻意与 `run_eval.py` 的编排分离：每个判定都能用手工构造的 state 单测，
不需要重跑 15 次 LangGraph 才能验证一个指标公式。

关于 `citation_traceability` 的诚实定义：
fixture 阶段没有 LLM judge，这里用 **词法包含**（claim 文本归一化后必须出现在
其 source_url 对应的来源正文里）作为可机器核验的代理指标。它能抓到「引用拼错
URL」「张冠李戴」「凭空造句」，但**不等价于语义蕴含**——来源写「未查到融资」
而结论写「已完成 A 轮」，词法上不相似会被抓到；换成更隐蔽的语义扭曲则未必。
因此 scorecard 里该指标名带 `_lexical_proxy` 说明，真实语义判定归 S8。

`hallucination_rate` 定义为 `1 - citation_traceability`（互补指标，不是独立证据），
避免把同一个数字当成两次验证。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from config.loader import Settings
from evals.config import EvalConfig

_REF_LINE = re.compile(r"^\[(\d+)\]\s+(.+?)\s+—\s+(\S+)\s*$")
_CLAIM_LINE = re.compile(r"^-\s+(.*?)(?:\s+\[(\d+)\])?\s*$")
_HEADING = re.compile(r"^##\s+(.+?)\s*$")

SUPPORTED = "ok"
NO_URL = "no_marker_or_url"
UNKNOWN_URL = "url_not_in_golden_corpus"
MISMATCH = "content_mismatch"


def norm_text(value: Any) -> str:
    """归一化文本：去所有空白，避免中英文排版差异影响词法包含判定。"""
    return re.sub(r"\s+", "", str(value or ""))


def norm_url(value: Any) -> str:
    """HttpUrl 会给裸域名补尾斜杠，比对前统一去掉。"""
    return str(value or "").rstrip("/")


@dataclass(frozen=True)
class ParsedClaim:
    section: str
    text: str
    marker: int | None
    url: str | None
    is_abstain: bool


@dataclass
class ParsedReport:
    claims: list[ParsedClaim] = field(default_factory=list)
    references: dict[int, str] = field(default_factory=dict)
    section_lines: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class GoldenSet:
    items: list[dict[str, Any]]
    meta: dict[str, Any]
    cases: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    abstains: list[dict[str, Any]]
    corpus: dict[str, list[str]]
    # (case, section, 归一化文本) -> url，供 inline_citations=false 时回推来源
    text_index: dict[tuple[str, str, str], str]


def load_golden(path: str | Path) -> GoldenSet:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"golden set 不存在：{p}；先运行 python -m evals.build_golden")
    items = [
        json.loads(line)
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not items or items[0].get("kind") != "meta":
        raise ValueError(f"{p} 第一行必须是 kind=meta（由 build_golden.py 生成）")
    corpus: dict[str, list[str]] = {}
    text_index: dict[tuple[str, str, str], str] = {}
    for item in items:
        if item["kind"] != "claim":
            continue
        key = norm_url(item["source_url"])
        corpus.setdefault(key, []).append(str(item.get("source_content", "")))
        text_index[(item["case"], item["section"], norm_text(item["expected_text"]))] = key
    return GoldenSet(
        items=items,
        meta=items[0],
        cases=[i for i in items if i["kind"] == "case"],
        claims=[i for i in items if i["kind"] == "claim"],
        abstains=[i for i in items if i["kind"] == "abstain"],
        corpus=corpus,
        text_index=text_index,
    )


def parse_report(
    report: str,
    settings: Settings,
    *,
    text_index: Mapping[tuple[str, str, str], str] | None = None,
    case: str = "",
) -> ParsedReport:
    """把最终报告还原成 (section, claim, url) 三元组。

    行内引用 [n] 与末尾 References 同源（report.py 的硬约定），所以 [n] 可以
    直接映射回 URL。`inline_citations=false` 时没有 [n]，按「文本唯一确定来源」
    从 golden 回推并标注 `url_from_text_index`，不做隐式猜测。
    """
    heading_map = dict(zip(settings.report.headings, settings.graph.sections))
    sections = list(settings.graph.sections)
    parsed = ParsedReport(section_lines={s: [] for s in sections})
    current: str | None = None
    in_refs = False
    degrade = settings.graph.degrade.message

    for raw in report.splitlines():
        line = raw.strip()
        heading = _HEADING.match(line)
        if heading:
            name = heading.group(1)
            in_refs = name == settings.report.headings[-1]
            current = None if in_refs else heading_map.get(name)
            continue
        if in_refs:
            ref = _REF_LINE.match(line)
            if ref:
                parsed.references[int(ref.group(1))] = ref.group(3)
            continue
        if current is None:
            continue
        claim = _CLAIM_LINE.match(line)
        if not claim:
            continue
        text = claim.group(1).strip()
        marker = int(claim.group(2)) if claim.group(2) else None
        url = parsed.references.get(marker) if marker is not None else None
        if url is None and marker is None and text_index is not None:
            url = text_index.get((case, current, norm_text(text)))
        parsed.section_lines.setdefault(current, []).append(text)
        parsed.claims.append(
            ParsedClaim(
                section=current,
                text=text,
                marker=marker,
                url=norm_url(url) if url else None,
                is_abstain=norm_text(text) == norm_text(degrade),
            )
        )
    # References 段在正文之后，第一轮解析时 [n]->url 还没建好，这里回填
    if parsed.references:
        parsed.claims = [
            ParsedClaim(
                section=c.section,
                text=c.text,
                marker=c.marker,
                url=norm_url(parsed.references.get(c.marker)) if c.marker is not None and c.url is None else c.url,
                is_abstain=c.is_abstain,
            )
            for c in parsed.claims
        ]
    return parsed


def is_supported(text: str, url: str | None, corpus: Mapping[str, list[str]]) -> tuple[bool, str]:
    if not url:
        return False, NO_URL
    contents = corpus.get(norm_url(url))
    if not contents:
        return False, UNKNOWN_URL
    needle = norm_text(text)
    if not needle:
        return False, MISMATCH
    for content in contents:
        hay = norm_text(content)
        if hay and (needle in hay or hay in needle):
            return True, SUPPORTED
    return False, MISMATCH


def evaluate_case(
    *,
    case_item: dict[str, Any],
    state: Mapping[str, Any],
    trace: Iterable[str],
    elapsed_ms: float,
    golden: GoldenSet,
    settings: Settings,
) -> dict[str, Any]:
    """评估单个 case，返回用例级明细（含失败 golden item id，供 CI 定位退化）。"""
    case = case_item["case"]
    trace_list = list(trace)
    parsed = parse_report(
        str(state.get("report", "")), settings,
        text_index=golden.text_index, case=case,
    )
    by_section: dict[str, list[ParsedClaim]] = {}
    for claim in parsed.claims:
        by_section.setdefault(claim.section, []).append(claim)

    failures: list[str] = []
    claim_items = [i for i in golden.claims if i["case"] == case]
    matched = 0
    for item in claim_items:
        section, expected = item["section"], norm_text(item["expected_text"])
        wanted_url = norm_url(item["source_url"])
        hit = any(
            norm_text(c.text) == expected and c.url == wanted_url and not c.is_abstain
            for c in by_section.get(section, [])
        )
        if hit:
            matched += 1
        else:
            failures.append(item["id"])

    abstain_items = [i for i in golden.abstains if i["case"] == case]
    abstain_passed = 0
    degraded_sections = set(state.get("degraded_sections", []))
    for item in abstain_items:
        section = item["section"]
        lines = [c for c in by_section.get(section, [])]
        abstain_line = any(
            c.is_abstain and norm_text(c.text) == norm_text(item["expected_message"])
            for c in lines
        )
        no_facts = not [c for c in lines if not c.is_abstain]
        if abstain_line and no_facts and section in degraded_sections:
            abstain_passed += 1
        else:
            failures.append(item["id"])

    claim_records: list[dict[str, Any]] = []
    for claim in parsed.claims:
        if claim.is_abstain:
            continue
        ok, reason = is_supported(claim.text, claim.url, golden.corpus)
        claim_records.append(
            {
                "section": claim.section,
                "text": claim.text,
                "url": claim.url,
                "marker": claim.marker,
                "supported": ok,
                "reason": reason,
            }
        )

    retry_count = dict(state.get("retry_count", {}) or {})
    rounds = max(retry_count.values(), default=0)
    degraded = bool(state.get("degraded", False)) or bool(degraded_sections)
    verdicts = dict(state.get("evidence_verdict", {}) or {})
    corrected = (
        bool(case_item.get("expect_self_correction"))
        and rounds > 0
        and not degraded
        and all(v == "sufficient" for v in verdicts.values())
    )

    return {
        "case": case,
        "company": case_item["company"],
        "passed": not failures,
        "failures": failures,
        "expected_claims": len(claim_items),
        "matched_claims": matched,
        "expected_abstains": len(abstain_items),
        "passed_abstains": abstain_passed,
        "claim_records": claim_records,
        "retry_rounds": rounds,
        "research_runs": trace_list.count("research"),
        "expected_research_runs": case_item.get("expected_research_runs"),
        "degraded_sections": sorted(degraded_sections),
        "self_correction_denominator": 1 if case_item.get("expect_self_correction") else 0,
        "self_correction_success": 1 if corrected else 0,
        "elapsed_ms": round(elapsed_ms, 3),
        "report_chars": len(str(state.get("report", ""))),
        "reference_count": len(state.get("references", {}) or {}),
    }


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return round(ordered[min(idx, len(ordered) - 1)], 3)


def aggregate_metrics(case_results: list[dict[str, Any]], cfg: EvalConfig) -> tuple[dict[str, Any], dict[str, Any]]:
    """汇总一组 A/B 的 8 项指标；返回 (metrics, counts)。"""
    expected = sum(c["expected_claims"] for c in case_results)
    matched = sum(c["matched_claims"] for c in case_results)
    abstain_total = sum(c["expected_abstains"] for c in case_results)
    abstain_ok = sum(c["passed_abstains"] for c in case_results)
    records = [r for c in case_results for r in c["claim_records"]]
    supported = sum(1 for r in records if r["supported"])

    # 没有结论 = 没有无依据结论；分母为 0 时记 1.0 并在 counts 里留痕，不静默给满分
    traceability = supported / len(records) if records else 1.0
    denom = sum(c["self_correction_denominator"] for c in case_results)
    correction = (
        sum(c["self_correction_success"] for c in case_results) / denom if denom else None
    )

    metrics = {
        "fact_accuracy": round(matched / expected, 6) if expected else 0.0,
        "citation_traceability": round(traceability, 6),
        "abstain_rate": round(abstain_ok / abstain_total, 6) if abstain_total else 1.0,
        "hallucination_rate": round(1 - traceability, 6),
        "self_correction_success": round(correction, 6) if correction is not None else None,
        "avg_retry_rounds": round(
            sum(c["retry_rounds"] for c in case_results) / len(case_results), 6
        ) if case_results else 0.0,
        "p95_latency_ms": _p95([c["elapsed_ms"] for c in case_results]),
        # fixture 下 0 次真实模型/检索调用，成本恒为 0；这不是真实单次成本
        "cost_per_report": 0.0,
    }
    counts = {
        "cases": len(case_results),
        "expected_claims": expected,
        "matched_claims": matched,
        "report_claims": len(records),
        "supported_claims": supported,
        "unsupported_reasons": {
            reason: sum(1 for r in records if r["reason"] == reason)
            for reason in (NO_URL, UNKNOWN_URL, MISMATCH)
        },
        "abstain_items": abstain_total,
        "abstain_passed": abstain_ok,
        "self_correction_denominator": denom,
        "empty_traceability_denominator": not records,
    }
    return metrics, counts


def check_gate(metrics: Mapping[str, Any], cfg: EvalConfig) -> dict[str, Any]:
    """阈值只对 baseline 组生效；A/B 组是"关掉能力"的对照，本就会退化。"""
    t = cfg.thresholds
    checks = {
        "fact_accuracy_min": metrics["fact_accuracy"] >= t.fact_accuracy_min,
        "citation_traceability_min": metrics["citation_traceability"] >= t.citation_traceability_min,
        "hallucination_rate_max": metrics["hallucination_rate"] <= t.hallucination_rate_max,
        "abstain_rate_min": metrics["abstain_rate"] >= t.abstain_rate_min,
        "max_avg_retry_rounds": metrics["avg_retry_rounds"] <= t.max_avg_retry_rounds,
    }
    violations = [name for name, ok in checks.items() if not ok]
    return {"passed": not violations, "checks": checks, "violations": violations}


def compute_ab_effect(
    group_metrics: Mapping[str, Any],
    baseline_metrics: Mapping[str, Any],
    cfg: EvalConfig,
) -> dict[str, Any]:
    """A/B 是否真的改变了可观测行为：只比确定性指标，排除 p95_latency_ms。

    fixture 下有些 override 天然是空操作（例如检索参数不被 fixture 文档工具
    消费、human_review 默认就是关的）。这里如实标 `no_effect`，不伪造对照收益。
    """
    delta: dict[str, float | None] = {}
    for metric in cfg.deterministic_metrics():
        a, b = baseline_metrics.get(metric), group_metrics.get(metric)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            delta[metric] = round(b - a, 6)
        else:
            delta[metric] = None
    changed = any(v not in (None, 0, 0.0) for v in delta.values())
    return {
        "status": "changed" if changed else "no_effect",
        "delta_vs_baseline": delta,
        "note": (
            "确定性指标向量与 baseline 一致；该 override 在当前 fixture 配置下"
            "未改变任何可观测行为（详见 docs/ACTION_PLAN.md 第 11 节）"
            if not changed else
            "确定性指标与 baseline 存在差异，差异项见 delta_vs_baseline"
        ),
    }


def _failure_ids(scorecard: Mapping[str, Any], group: str = "baseline") -> set[str]:
    """golden item id 本身已含 case 前缀（如 `sparse:company:2`），全局唯一。"""
    run = scorecard.get("runs", {}).get(group, {})
    return {
        item_id
        for case in run.get("cases", [])
        for item_id in case.get("failures", [])
    }


def compare_scorecards(
    prev: Mapping[str, Any], cur: Mapping[str, Any], cfg: EvalConfig
) -> dict[str, Any]:
    """与上一版 scorecard 比对：核心指标回退超容差 → 失败，并列出退化用例 id。"""
    tol = cfg.ci.regression_tolerance
    p = prev.get("runs", {}).get("baseline", {}).get("metrics", {})
    c = cur.get("runs", {}).get("baseline", {}).get("metrics", {})
    violations: list[str] = []
    details: list[dict[str, Any]] = []

    for metric in cfg.ci.protected_metrics:
        before, after = p.get(metric), c.get(metric)
        if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
            violations.append(f"{metric}: 上一版或本版缺少数值，无法比对")
            continue
        direction = cfg.metric_direction.get(metric)
        regressed = (
            after < before - tol if direction == "higher"
            else after > before + tol if direction == "lower"
            else False
        )
        details.append(
            {"metric": metric, "before": before, "after": after, "delta": round(after - before, 6), "regressed": regressed}
        )
        if regressed:
            violations.append(
                f"{metric}: {before} -> {after}（回退 {abs(after - before):.4f} > 容差 {tol}）"
            )

    prev_fail, cur_fail = _failure_ids(prev), _failure_ids(cur)
    degraded_case_ids = sorted(cur_fail - prev_fail)
    if degraded_case_ids:
        violations.append(f"新增失败用例 {len(degraded_case_ids)} 个（见 degraded_case_ids）")

    return {
        "compared_metrics": details,
        "tolerance": tol,
        "protected_metrics": list(cfg.ci.protected_metrics),
        "degraded_case_ids": degraded_case_ids,
        "violations": violations,
        "passed": not violations,
    }
