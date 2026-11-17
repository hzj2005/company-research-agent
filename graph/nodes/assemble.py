"""R3 报告拼装器：把四个子图写好的栏目段落，统一编号 + References 拼成报告。

职责（用户 2026-11-17 决策）：
- 子图：检索 → 抽取 → 校验 → 写自己栏目的段落（facts 带 source_url，**不碰编号**）；
- 报告层：只做拼装工——收集所有栏目的 facts → 统一编号 → 生成 References → 拼 Markdown。

两条硬约定（继承原报告层，不能丢）：
1. 正文 [n] 与末尾 References 来自同一份 URL 集合；
2. 降级栏目直接输出拒答话术，不拿低分内容硬凑。

纯函数、0 模型 0 网络、可单测。
"""

from __future__ import annotations

from typing import Any

from config.loader import Settings


def _norm(url: Any) -> str:
    return str(url).rstrip("/")


def assemble_report(
    company: str,
    sections: list[dict[str, Any]],
    settings: Settings,
) -> tuple[str, dict[str, dict[str, Any]]]:
    """把四段栏目产物拼成完整报告。

    `sections` 每项：
      {
        "key": "company"|"industry"|"financial"|"news",
        "heading": "公司概况",           # 或由 settings.report.headings 按序取
        "facts": [{"claim","source_url"}],
        "status": "ok"|"degraded"|"no_evidence",
        "conflicts": [str],              # 可选，冲突标注行
        "references": {url: {"title":..., "score":...}},  # 该栏目文档中选中的
      }

    返回 (report_text, briefings)。
    """
    heading_by_key = dict(zip(settings.graph.sections, settings.report.headings))
    degrade_msg = settings.graph.degrade.message

    # ① 收集全局 URL 集合（所有栏目 facts 的 source_url + 各栏目 references）
    all_urls: set[str] = set()
    ref_meta: dict[str, dict[str, Any]] = {}
    for sec in sections:
        for fact in sec.get("facts", []):
            u = str(fact.get("source_url", ""))
            if u:
                all_urls.add(u)
        for url, meta in (sec.get("references") or {}).items():
            all_urls.add(str(url))
            ref_meta[str(url)] = meta

    # ② 统一编号：按 score 降序、URL 字典序（与原 _select_documents 同规则）
    ordered = sorted(
        all_urls,
        key=lambda u: (-float(ref_meta.get(u, {}).get("score", 0) or 0), u),
    )
    index = {u: i + 1 for i, u in enumerate(ordered)}
    norm_index = {_norm(u): n for u, n in index.items()}

    # ③ 逐段渲染
    lines: list[str] = [f"# {company} 研究报告", ""]
    briefings: dict[str, dict[str, Any]] = {}
    for sec in sections:
        key = sec["key"]
        lines.extend([f"## {heading_by_key.get(key, key)}", ""])
        status = sec.get("status", "ok")
        facts = sec.get("facts", [])

        if status != "ok" or not facts:
            lines.append(f"- {degrade_msg}")
            briefings[key] = {"status": status if status != "ok" else "no_evidence"}
        else:
            for fact in facts:
                claim = str(fact.get("claim", ""))
                url = str(fact.get("source_url", ""))
                marker = ""
                if settings.features.inline_citations and url:
                    n = norm_index.get(_norm(url))
                    if n is not None:
                        marker = f" [{n}]"
                lines.append(f"- {claim}{marker}")
            # 冲突标注（引用块，不参与"每条 bullet 带引用"统计）
            for conflict in sec.get("conflicts", []):
                lines.append(f"> {conflict}")
            briefings[key] = {
                "status": "ok",
                "facts": list(facts),
                "conflicts": list(sec.get("conflicts", [])),
            }
        lines.append("")

    # ④ References（与正文同源）
    lines.extend(["## References", ""])
    for url in ordered:
        meta = ref_meta.get(url, {})
        lines.append(f"[{index[url]}] {meta.get('title', '')} — {url}")

    return "\n".join(lines).rstrip() + "\n", briefings
