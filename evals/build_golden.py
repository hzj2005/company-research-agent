"""S7 golden set 派生器：从 fixture 语料 + 配置规则算出「系统应当产出什么」。

为什么是"派生"而不是"手写 30~50 家公司的事实"：
- `evals/fixtures/tavily_responses.json` 首行明确写着「合成样本，禁止当作评测
  指标或事实来源」。在没有模型 key、没有真实检索语料的阶段，手写公司事实
  等于编造标注，产出的准确率不能写进简历，一问就穿。
- 因此 golden 的 expected 全部来自 fixture 语料，按 `config/settings.yaml` 的
  evidence 阈值规则**独立重算**：哪些文档合格、需要几轮回退、哪些栏目应拒答。
  本文件不 import 任何图节点，也不读被测系统的输出——不用被测系统给自己出标准答案。
- 每条 claim item 自带 `source_content`，评测器不需要回读 fixture。
  S8 换成真实语料/人工标注时，只要产出同样 schema 的 jsonl，`run_eval.py` 不用改。

用法：
    uv run python -m evals.build_golden              # 写入 evals/golden.jsonl
    uv run python -m evals.build_golden --check      # CI：校验 golden 与 fixture/settings 同步
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from config.loader import Settings, get_settings
from evals.config import dataset_path, load_eval_config

SCHEMA_VERSION = 1
PROVENANCE = "synthetic-fixture-derived"


def _settings_fingerprint(settings: Settings) -> str:
    """只把影响 golden 派生的配置字段纳入指纹；改了就该重新生成。"""
    payload = {
        "sections": settings.graph.sections,
        "min_relevance_score": settings.graph.evidence.min_relevance_score,
        "min_docs_per_section": settings.graph.evidence.min_docs_per_section,
        "require_source_url": settings.graph.evidence.require_source_url,
        "max_retry": settings.graph.max_retry,
        "degrade_message": settings.graph.degrade.message,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]


def _qualified(doc: dict[str, Any], settings: Settings) -> bool:
    """与 graph/nodes/collect.py:make_curate_node 的过滤规则同构，但不调用它。"""
    if settings.graph.evidence.require_source_url and not doc.get("url"):
        return False
    try:
        score = float(doc.get("score", 0) or 0)
    except (TypeError, ValueError):
        return False
    return score >= settings.graph.evidence.min_relevance_score


def _simulate_case(case: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """按规范逐轮推进：首轮全栏目派发，之后只对不足栏目重搜，用尽额度即降级。

    与 graph/conditions.py:route_after_evidence 的三路分支语义一致，但这里是
    **独立于实现的规范计算**（不读取任何 State / 图输出）。
    """
    sections = list(settings.graph.sections)
    rounds = case.get("rounds", [])
    min_docs = settings.graph.evidence.min_docs_per_section
    max_retry = settings.graph.max_retry

    accumulated: dict[str, dict[str, dict[str, Any]]] = {s: {} for s in sections}
    pending = list(sections)
    first_round_insufficient = False
    degraded: list[str] = []
    round_no = 0

    while True:
        raw = rounds[round_no] if round_no < len(rounds) else {}
        active = list(sections) if round_no == 0 else list(pending)
        for section in active:
            for doc in raw.get(section, []):
                if not _qualified(doc, settings):
                    continue
                accumulated[section][str(doc["url"])] = {
                    "url": str(doc["url"]),
                    "text": str(doc.get("content", "")),
                    "content": str(doc.get("content", "")),
                    "title": str(doc.get("title", "")),
                    "score": float(doc.get("score", 0) or 0),
                }
        pending = [s for s in sections if len(accumulated[s]) < min_docs]
        if round_no == 0:
            first_round_insufficient = bool(pending)
        if not pending:
            break
        # 只看「重试额度」，不看 fixture 还剩几轮：图在 store.fetch() 轮数用尽后
        # 会拿到空结果并继续空转，直到 retry_count >= max_retry 才 degrade。
        # 早期版本在这里提前 break，导致 expected_research_runs 少算（S7 复查 P3）。
        if round_no >= max_retry:
            degraded = list(pending)
            break
        round_no += 1

    return {
        "accumulated": accumulated,
        "degraded": degraded,
        "first_round_insufficient": first_round_insufficient,
        "expected_research_runs": round_no + 1,
        "expect_self_correction": first_round_insufficient and not degraded,
    }


def derive_golden(fixture: dict[str, Any], settings: Settings) -> list[dict[str, Any]]:
    """返回可直接写成 jsonl 的 item 列表（顺序确定，便于 diff）。"""
    items: list[dict[str, Any]] = [
        {
            "kind": "meta",
            "schema_version": SCHEMA_VERSION,
            "generated_by": "evals/build_golden.py",
            "provenance": PROVENANCE,
            "source_fixture": str(settings.models.fixture.responses_path),
            "settings_fingerprint": _settings_fingerprint(settings),
            "note": (
                "合成语料派生的机器可核验契约，不是真实世界事实；"
                "禁止把本文件产出的指标当作模型准确率写进简历。"
                "真实指标需 APP_MODE=live + 真实语料/人工核验 golden（S8）。"
            ),
        }
    ]

    for case_key in sorted(fixture["cases"]):
        case = fixture["cases"][case_key]
        sim = _simulate_case(case, settings)
        degraded = set(sim["degraded"])
        company = str(case["company"])

        items.append(
            {
                "kind": "case",
                "id": f"{case_key}:case",
                "case": case_key,
                "company": company,
                "first_round_insufficient": sim["first_round_insufficient"],
                "expect_self_correction": sim["expect_self_correction"],
                "expected_research_runs": sim["expected_research_runs"],
                "expected_degraded_sections": sim["degraded"],
            }
        )

        for section in settings.graph.sections:
            if section in degraded:
                items.append(
                    {
                        "kind": "abstain",
                        "id": f"{case_key}:{section}:abstain",
                        "case": case_key,
                        "company": company,
                        "section": section,
                        "expected_message": settings.graph.degrade.message,
                    }
                )
                continue
            docs = sorted(
                sim["accumulated"][section].values(), key=lambda d: d["url"]
            )
            for i, doc in enumerate(docs):
                items.append(
                    {
                        "kind": "claim",
                        "id": f"{case_key}:{section}:{i}",
                        "case": case_key,
                        "company": company,
                        "section": section,
                        "expected_text": doc["text"],
                        "source_url": doc["url"],
                        "source_content": doc["content"],
                        "source_title": doc["title"],
                    }
                )
    return items


def _fixture_path(settings: Settings) -> Path:
    from capabilities.retrieval import resolve_fixture_path

    return resolve_fixture_path(settings)


def build_items(settings: Settings | None = None) -> list[dict[str, Any]]:
    s = settings or get_settings()
    fixture = json.loads(_fixture_path(s).read_text(encoding="utf-8"))
    return derive_golden(fixture, s)


def _serialize(items: list[dict[str, Any]]) -> str:
    return "\n".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True) for item in items
    ) + "\n"


def _target_path() -> Path:
    return dataset_path(load_eval_config())


def main() -> int:
    parser = argparse.ArgumentParser(description="S7 golden set 派生 / 同步校验")
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    parser.add_argument("--stdout", action="store_true", help="打印到标准输出")
    args = parser.parse_args()

    settings = get_settings()
    expected = _serialize(build_items(settings))
    target = _target_path()

    if args.stdout:
        sys.stdout.write(expected)
        return 0

    if args.check:
        if not target.exists():
            print(f"[FAIL] {target} 不存在，请先运行 python -m evals.build_golden")
            return 1
        actual = target.read_text(encoding="utf-8")
        if actual != expected:
            print(f"[FAIL] {target} 与 fixture/settings 不同步，请重新生成")
            exp_lines, act_lines = expected.splitlines(), actual.splitlines()
            for i in range(max(len(exp_lines), len(act_lines))):
                e = exp_lines[i] if i < len(exp_lines) else "<缺失>"
                a = act_lines[i] if i < len(act_lines) else "<缺失>"
                if e != a:
                    print(f"  第 {i + 1} 行期望: {e[:160]}")
                    print(f"  第 {i + 1} 行实际: {a[:160]}")
                    break
            return 1
        print(f"[OK] {target} 与 fixture/settings 同步（{len(expected.splitlines())} 行）")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(expected, encoding="utf-8")
    kinds: dict[str, int] = {}
    for item in build_items(settings):
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    print(f"[OK] 已写入 {target}")
    print(f"     items: {kinds}（provenance={PROVENANCE}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
