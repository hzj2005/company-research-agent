"""S8.3 真实报告的词法质量检查（0 次外部调用）。

读 `evals/live_run.json` 里已经产出的报告，做**可机器核验**的结构/一致性检查：
1. 正文每条 `[n]` 是否都能映射到 References 的编号（引用完整性）；
2. 同一栏目里同一谓词（如 founded in YYYY）是否出现互相矛盾的取值；
3. 来源域名分布（只列出，不做可信度打分）。

**边界**：这是词法检查，不是事实核验。「Notion 总部在伦敦」是否错误，
必须由人工核验的 golden 或 judge 判定；本脚本只负责把「同一份报告里
同时出现 2013 和 2014 两个创立年份」这类硬矛盾自动抓出来。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from config.loader import ROOT

INPUT = ROOT / "evals" / "live_run.json"
OUTPUT = ROOT / "evals" / "live_quality.json"

_CLAIM = re.compile(r"^-\s+(.+?)\s*\[(\d+)\]\s*$", flags=re.MULTILINE)
_REF = re.compile(r"^\[(\d+)\]\s+(.+)$", flags=re.MULTILINE)
_FOUNDED = re.compile(r"\bfounded in (\d{4})\b", flags=re.IGNORECASE)
_URL = re.compile(r"https?://[^\s\)\]]+")


def analyse(report: str) -> dict[str, Any]:
    body, sep, refs = report.partition("## References")
    if not sep:
        body, refs = report, ""

    claims: list[dict[str, Any]] = []
    section: str | None = None
    for line in body.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        else:
            matched = _CLAIM.match(line)
            if matched:
                claims.append(
                    {
                        "section": section,
                        "text": matched.group(1).strip(),
                        "marker": int(matched.group(2)),
                    }
                )

    ref_map = {int(n): text.strip() for n, text in _REF.findall(refs)}
    missing_markers = sorted({c["marker"] for c in claims if c["marker"] not in ref_map})
    used_markers = sorted({c["marker"] for c in claims})

    founded_by_section: dict[str, set[int]] = {}
    for c in claims:
        for year in _FOUNDED.findall(c["text"]):
            founded_by_section.setdefault(str(c["section"]), set()).add(int(year))
    contradictions = [
        {"section": sec, "predicate": "founded in YYYY", "values": sorted(years)}
        for sec, years in founded_by_section.items()
        if len(years) > 1
    ]

    domains = [
        re.sub(r"https?://(www\.)?([^/]+).*", r"\2", url)
        for url in _URL.findall(refs)
    ]
    return {
        "claims_count": len(claims),
        "sections": list(dict.fromkeys(str(c["section"]) for c in claims)),
        "inline_markers_used": used_markers,
        "reference_numbers": sorted(ref_map),
        "markers_without_reference": missing_markers,
        "citation_integrity_ok": not missing_markers and len(used_markers) > 0,
        "contradictions": contradictions,
        "contradiction_count": len(contradictions),
        "source_domains": dict(Counter(domains)),
        "source_domain_count": len(set(domains)),
        "method": "词法/结构检查，非语义事实核验",
        "note": (
            "引用完整性只证明 [n] 有对应编号，不证明该 URL 真的支持结论；"
            "矛盾检测只覆盖 founded in YYYY 这类显式模式，未覆盖同义改写的事实冲突"
        ),
    }


def main() -> int:
    if not INPUT.exists():
        raise SystemExit(f"缺少 {INPUT}，请先运行 evals/live_run.py（需真实额度）")
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    report = str(data.get("report", ""))
    result = {
        "purpose": "S8.3 真实报告词法质量检查（0 次外部调用）",
        "source_artifact": "evals/live_run.json",
        "company": data.get("company"),
        "live_run_status": data.get("status"),
        "checks": analyse(report) if report else None,
        "verdict_note": (
            "本文件不产出准确率。真实事实是否正确，须由人工核验的 golden + judge 判定（S8.4）。"
        ),
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    c = result["checks"]
    print(f"[S8.3 quality] -> {OUTPUT.relative_to(ROOT)}")
    if c:
        print(f"  claims={c['claims_count']} citation_integrity_ok={c['citation_integrity_ok']}")
        print(f"  contradictions={c['contradiction_count']} {c['contradictions']}")
        print(f"  source_domains={c['source_domain_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
