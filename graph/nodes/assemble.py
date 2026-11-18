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


def _render_conflict(conflict: Any, norm_index: dict[str, int]) -> str:
    """结构化冲突 → 一行引用块文本（编号在此统一分配，子图不碰编号）。

    兼容两种形态：字符串原样返回（旧测试/手写）；dict 渲染成带 [n] 的说明。
    """
    if isinstance(conflict, str):
        return conflict
    label = str(conflict.get("label") or conflict.get("slot") or "该字段")
    values = conflict.get("values") or []
    parts: list[str] = []
    for v in values:
        display = str(v.get("display", ""))
        nums = "".join(
            f"[{n}]"
            for n in (norm_index.get(_norm(u)) for u in (v.get("urls") or []))
            if n is not None
        )
        parts.append(f"{display} {nums}".strip())
    joined = " / ".join(parts)
    return (
        f"**来源冲突**：{label}出现 {len(values)} 个取值 —— {joined}，"
        f"来源之间不一致，未判定哪个正确"
    )


def _cite(urls: list[str], norm_index: dict[str, int]) -> str:
    return "".join(
        f"[{n}]"
        for n in (norm_index.get(_norm(u)) for u in urls)
        if n is not None
    )


def _render_analysis(
    key: str, analysis: dict[str, Any], norm_index: dict[str, int]
) -> list[str]:
    """栏目附加分析 → 引用块行（不以 `- ` 开头，不参与事实 bullet 统计）。

    仅当 features.postprocess 开启时调用（便于"渲染 vs 不渲染"的 A/B）。
    内容全部来自已抽取的结构化产物，不新增结论、不做评价。
    """
    lines: list[str] = []

    if key == "financial":
        timeline = analysis.get("timeline") or []
        if timeline:
            parts = []
            for r in timeline:
                piece = f"{r.get('year') or '年份不明'} {r.get('round')}"
                if r.get("amount"):
                    piece += f" {r['amount']}"
                c = _cite([str(r.get("source_url", ""))], norm_index)
                parts.append(f"{piece} {c}".strip())
            lines.append(f"> 融资时间线：{' → '.join(parts)}")
        unverified = analysis.get("unverified") or []
        if unverified:
            lines.append(
                f"> 数字待核：{len(unverified)} 笔金额未在本栏目原文中找到，"
                f"已保留原值但标注为未核实"
            )

    elif key == "industry":
        competitors = analysis.get("competitors") or []
        if competitors:
            names = "、".join(
                f"{c.get('name')}（{c.get('tier')}）" for c in competitors[:6]
            )
            lines.append(f"> 竞品识别：{names}")
        matrix = analysis.get("comparison_matrix") or {}
        if matrix.get("missing"):
            lines.append(
                f"> 对比矩阵尚有 {len(matrix['missing'])} 个格子缺少公开信息，"
                f"未做推断填补"
            )

    elif key == "news":
        events = analysis.get("events") or []
        multi = [e for e in events if e.get("multi_source")]
        if multi:
            desc = "、".join(
                f"{e['event_key'].split(':')[0]}（{e['count']} 条来源）" for e in multi[:5]
            )
            lines.append(f"> 多来源事件：{desc}")
        stale = analysis.get("stale_count") or 0
        if stale:
            lines.append(f"> 时效提示：{stale} 条事实日期较早，已保留但需注意时效")

    return lines


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
            briefings[key] = {
                "status": status if status != "ok" else "no_evidence",
                "conflicts": list(sec.get("conflicts", [])),
            }
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
                lines.append(f"> {_render_conflict(conflict, norm_index)}")
            # 栏目附加分析（R4，仅 postprocess 开启时渲染；引用块，不改正文 bullet）
            if settings.features.postprocess:
                for extra in _render_analysis(key, sec.get("analysis") or {}, norm_index):
                    lines.append(extra)
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
