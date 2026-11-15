"""S8.4: build the formal human-verified golden set from the user's FINAL decisions.

Inputs (all read-only):

    evals/golden_live_review_filled.jsonl   user's final 25 decisions (exported from the local page)
    evals/golden_live_review.jsonl          AI-assisted source verification / evidence quotes
    evals/golden_live_draft.jsonl           candidate facts + company metadata

Output:

    evals/golden_live.jsonl                 formal golden set, same kind/case/claim
                                           shape as evals/golden.jsonl

Honesty rules baked into the output:
* The user re-reviewed and revised 11 of 25 claims into their final answer.
  Both the original wording and the final wording are recorded; nothing is
  silently overwritten or hidden.
* The 6 unreachable ORIGINAL URLs were replaced. But this project has NOT
  fetched the new pages (0 calls), so `source_content` is null for every
  revised claim and the citation layer is still NOT a usable metric.
* Only Notion currently has a real report (evals/live_run.json). The other
  4 companies / 20 claims have nothing to be scored against yet.
* 0 API calls, 0 Tavily credits, no network access.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILLED = ROOT / "golden_live_review_filled.jsonl"
REVIEW = ROOT / "golden_live_review.jsonl"
DRAFT = ROOT / "golden_live_draft.jsonl"
OUTPUT = ROOT / "golden_live.jsonl"

REPORT_SECTION = {
    "company": "Company Overview",
    "industry": "Industry Overview",
    "financial": "Financial Overview",
    "news": "News",
}


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build() -> list[dict]:
    filled = _read(FILLED)
    review = _read(REVIEW)
    draft = _read(DRAFT)

    meta = next(r for r in filled if r["kind"] == "meta")
    decisions = [r for r in filled if r["kind"] == "claim"]
    checks = {r["id"]: r for r in review if r["kind"] == "claim"}
    claims = {r["id"]: r for r in draft if r["kind"] == "claim"}
    cases = [r for r in draft if r["kind"] == "case"]

    if len(decisions) != 25 or len(claims) != 25 or len(checks) != 25:
        raise ValueError("expected 25 decisions / 25 draft claims / 25 source checks")
    if {r["id"] for r in decisions} != set(claims) or set(claims) != set(checks):
        raise ValueError("id mismatch between decisions, draft and source checks")
    if any(r.get("user_verdict") is None for r in decisions):
        raise ValueError("every claim must carry an explicit user_verdict")
    if meta.get("is_human_verification") is not True:
        raise ValueError("filled review must be declared as human verification")

    by_decision = Counter(r["user_decision"] for r in decisions)
    original_unreachable = [
        r["id"] for r in decisions if not checks[r["id"]].get("source_accessible")
    ]
    ai_flagged = [
        r["id"] for r in decisions if checks[r["id"]].get("ai_check") != "verified"
    ]
    still_unresolved = [
        r["id"] for r in decisions
        if r["user_decision"] == "accept" and checks[r["id"]].get("ai_check") != "verified"
    ]

    def classify(d: dict) -> str:
        check = checks[d["id"]]
        original = claims[d["id"]]["source_url"]
        final = d["final_source_url"]
        if final == original:
            return "original"
        if final and final == check.get("suggested_source_url"):
            return "ai_suggested_and_read"
        return "user_supplied"

    url_kinds = Counter(classify(d) for d in decisions)
    revised_ids = [
        d["id"] for d in decisions
        if d["final_source_url"] != claims[d["id"]]["source_url"]
        or d["final_fact"] != claims[d["id"]]["candidate_fact"]
    ]

    out: list[dict] = [
        {
            "kind": "meta",
            "schema_version": 1,
            "generated_by": "evals/build_golden_live.py",
            "generated_at": date.today().isoformat(),
            "user_reviewed_at": meta.get("generated_at"),
            "provenance": "human-verified",
            "verified_by": "user",
            "source_file": "evals/golden_live_review_filled.jsonl",
            "companies": len(cases),
            "claims": len(decisions),
            "user_decisions": dict(by_decision),
            "claims_revised_by_user": len(revised_ids),
            "revised_claim_ids": revised_ids,
            "fact_layer_verified_by_user": True,
            "fact_layer_note": "用户重新复核并把 11 条改成最终标准答案；事实层以用户最终版本为准",
            "citation_layer_verified": False,
            "citation_layer_usable_as_metric": False,
            "citation_layer_status": (
                "6 条不可访问的原始 URL 已按 AI 核对建议或用户指定换成新 URL；"
                "但本项目没有重新抓取这些新页面（0 调用），新 URL 是否能打开、"
                "页面是否真的印着最终事实，均未在本项目内实测"
            ),
            "metric_scope": "fact_layer_only",
            "original_unreachable_source_urls": len(original_unreachable),
            "original_unreachable_claim_ids": original_unreachable,
            "claims_flagged_by_ai_source_check": len(ai_flagged),
            "claims_flagged_but_left_as_is": len(still_unresolved),
            "final_url_sources": dict(url_kinds),
            "final_url_content_fetched_in_project": False,
            "notes_source": (
                "逐条备注来自复核页面预填的核对说明并由用户采纳；"
                "三个结论按钮仍由用户逐条点选（见 evals/build_review_page.py 的 PRESETS 注释）"
            ),
            "coverage_note": (
                "目前只有 Notion 1 家有真实报告（evals/live_run.json，5 条 golden 事实）；"
                "其余 4 家共 20 条暂无报告可比，不得据此计算全量准确率/召回率"
            ),
            "usage_restriction": (
                "只能用于事实层语义比对；禁止用于 citation_traceability / URL 可访问性 / "
                "hallucination_rate 等引用层指标，也禁止把 S7 fixture 的 1.000 与本集合混为一谈"
            ),
            "what_this_is_not": "不是准确率指标，不含 abstain 样本，不是 30~50 家规模",
            "tavily_credits_used": 0,
            "llm_calls_used": 0,
        }
    ]

    for case in cases:
        out.append(
            {
                "kind": "case",
                "id": f"{case['case']}:case",
                "case": case["case"],
                "company": case.get("company", case["case"]),
                "has_real_report": case["case"] == "notion",
                "real_report_file": "evals/live_run.json" if case["case"] == "notion" else None,
            }
        )

    for decision in decisions:
        cid = decision["id"]
        check = checks[cid]
        draft_claim = claims[cid]
        original_url = draft_claim["source_url"]
        final_url = decision["final_source_url"]
        original_accessible = bool(check.get("source_accessible"))
        url_kind = classify(decision)
        revised = (
            final_url != original_url
            or decision["final_fact"] != draft_claim["candidate_fact"]
        )
        out.append(
            {
                "kind": "claim",
                "id": cid,
                "case": decision["case"],
                "company": next(
                    (c.get("company", c["case"]) for c in cases if c["case"] == decision["case"]),
                    decision["case"],
                ),
                "section": decision["section"],
                "report_section": REPORT_SECTION.get(decision["section"]),
                "expected_text": decision["final_fact"],
                "original_fact": draft_claim["candidate_fact"],
                "source_url": final_url,
                "original_source_url": original_url,
                "original_url_accessible": original_accessible,
                "source_revised": revised,
                "final_url_source": url_kind,
                "source_title": draft_claim.get("source_title", ""),
                # 只有「最终 URL 就是原始 URL 且当时核对过」才允许带原文，
                # 换了 URL 的一律留空，绝不把旧页面的引文冒充新页面的内容。
                "source_content": check.get("evidence_quote") if (final_url == original_url and original_accessible) else None,
                "source_content_for_final_url_verified": False,
                "evidence_quote_from_ai_check": check.get("evidence_quote"),
                "evidence_quote_note": "AI 逐条核对时读到的原文，对应原始或替代来源，不保证对应最终 URL",
                "ai_check": check.get("ai_check"),
                "ai_note": check.get("note", ""),
                "human_verdict": decision["user_verdict"],
                "human_decision": decision["user_decision"],
                "human_note": decision.get("user_note", ""),
                "has_real_report_to_score": decision["case"] == "notion",
            }
        )
    return out


def main() -> Path:
    rows = build()
    OUTPUT.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return OUTPUT


if __name__ == "__main__":
    out = main()
    meta = _read(out)[0]
    print(
        f"wrote {out.name}: {meta['claims']} claims / {meta['companies']} companies, "
        f"{meta['user_decisions']}, {meta['claims_revised_by_user']} revised, "
        f"{meta['original_unreachable_source_urls']} original URLs were unreachable (now replaced), "
        f"0 API calls, 0 credits"
    )
