"""S5 后处理层：对已抽取的 facts 做 Industry/News 专项加工。

设计红线（PROJECT_PLAN_V2.md 4.1.3/4.1.4）：
- **只搬运已有事实，不生成新判断**。竞品来自 facts 里出现过的名字；对比矩阵
  每格带 source_url；没有依据的维度记进 missing，不脑补。
- **不做重要性排序 / 情感判断**——推断性结论无 source_url，破坏可溯源红线。
- 纯规则、0 模型、0 网络。输出是新契约（Competitor/ComparisonMatrix），
  不改写原报告文本，因此 S7 基线（31 claims）不受影响。

接入方式：作为可选后处理，由上层在抽取后调用；默认关闭，回滚只需关开关。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable

from graph.contracts import ComparisonMatrix, Competitor, Fact, MatrixCell

logger = logging.getLogger(__name__)

# 竞品别名 → (归一名, 分层)。只认词表里的名字，绝不从模型自由生成竞品。
# tier: direct=直接竞品 / substitute=替代 / adjacent=相邻玩家
_COMPETITOR_ALIASES: dict[str, tuple[str, str]] = {
    "obsidian": ("Obsidian", "direct"),
    "obsidian.md": ("Obsidian", "direct"),
    "coda": ("Coda", "direct"),
    "notion": ("Notion", "direct"),
    "word": ("Word", "substitute"),
    "google docs": ("Google Docs", "substitute"),
    "confluence": ("Confluence", "substitute"),
    "figma": ("Figma", "adjacent"),
    "airtable": ("Airtable", "adjacent"),
}

# 框架槽位关键词：把 fact 归到固定维度，供报告结构化展示
_SLOT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "市场规模": ("市场", "规模", "亿美元", "billion"),
    "增速": ("增长", "增速", "cagr", "%"),
    "竞争格局": ("竞品", "竞争", "差异化", "对手"),
    "技术趋势": ("ai", "自动化", "技术", "趋势"),
    "主要挑战": ("挑战", "困难", "同质化", "风险"),
}

# 正文日期：`YYYY 年 M 月` 或 `YYYY-MM-DD`。抠不到就标"推断日期"缺席。
_DATE_PATTERNS = (
    re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月"),
    re.compile(r"(20\d{2})-(\d{1,2})-(\d{1,2})"),
    # 兜底：只有年份（"2024 年发布…"），放最后以免抢走更精确的年月
    re.compile(r"(20\d{2})\s*年"),
)
# 事件动作词：用于同一事件的粗粒度归并。
# 每组第一个是归并键；组内是同一动作的不同说法（"推出"与"发布"应聚成一组）。
_EVENT_ACTIONS: tuple[tuple[str, ...], ...] = (
    ("发布", "推出", "上线", "面世", "发行", "问世"),
    ("融资", "获得融资", "完成融资", "募集", "获投"),
    ("合作", "联手", "携手", "达成合作"),
    ("获奖", "入选", "获评", "被评为"),
    ("收购", "并购", "买下"),
    ("上市", "挂牌", "IPO"),
    ("裁员", "裁撤", "缩减团队"),
    ("达成", "签署", "签订"),
)


def _fact_from(item: dict[str, Any]) -> Fact | None:
    """从 briefings 里 dump 出来的 fact dict 还原成 Fact；来源缺失则跳过。"""
    try:
        return Fact(
            claim=str(item["claim"]),
            source_url=item["source_url"],
            confidence=float(item.get("confidence", 0.0)),
        )
    except (KeyError, TypeError, ValueError):
        return None


# 竞品句式：`竞品包括 X 与 Y` / `对标 X、Y` / `主要对手 X`。
# 只在明确句式里抽名字，绝不从任意文本凭空生成（防幻觉红线）。
_COMPETITOR_PATTERNS = (
    re.compile(r"竞品(?:包括|有|是|包含)\s*([^，。；]{1,80})"),
    re.compile(r"对标\s*([^，。；]{1,80})"),
    re.compile(r"(?:主要|直接)?竞争对手(?:包括|是|有)?\s*([^，。；]{1,80})"),
    # 「与 X 对标」「和 X 对标」——名字在前的语序同样常见
    re.compile(r"(?:与|和)\s*([^，。；]{2,40}?)\s*对标"),
)
# 从抽到的片段里切出候选名：大写开头的英文词，或 2-6 字中文专名
_NAME_TOKEN = re.compile(r"[A-Z][A-Za-z0-9.]{1,20}|[\u4e00-\u9fa5]{2,6}")
# 通用词黑名单：抽到这些说明句式里的不是真名字
_STOP_NAMES = frozenset({
    "竞品", "对手", "工具", "产品", "公司", "同类", "其他", "以下", "包括",
    "直接", "主要", "间接", "以及", "多家", "市场", "生态", "模板", "协作",
})


def _names_from_phrase(facts: Iterable[Fact]) -> dict[str, str]:
    """从竞品句式里抽候选名 → {名字: 归一化名}。抽不到就是空，不脑补。"""
    candidates: dict[str, str] = {}
    for fact in facts:
        for pattern in _COMPETITOR_PATTERNS:
            for match in pattern.finditer(fact.claim):
                for token in _NAME_TOKEN.findall(match.group(1)):
                    clean = token.strip(".,")
                    if clean in _STOP_NAMES or len(clean) < 2:
                        continue
                    # 词表里有归一名就用它，否则保留原文抽取的词
                    canonical = _COMPETITOR_ALIASES.get(clean.lower(), (clean, "direct"))[0]
                    candidates.setdefault(canonical, clean)
    return candidates


def _tier_for(name: str) -> str:
    """优先用词表标注的分层；词表外的按句式默认 direct，并留痕是推断。"""
    for alias, (canonical, tier) in _COMPETITOR_ALIASES.items():
        if canonical == name:
            return tier
    return "direct"


def _detect_competitors(facts: Iterable[Fact]) -> list[Competitor]:
    """识别竞品：词表命中 + 明确句式抽取，两者都带 evidence fact。

    防幻觉：词表外名字只有在"竞品包括/对标 X"这类明确句式里出现才采信；
    无句式、无依据的文本不生成竞品（保留 test_unknown_name 的红线）。
    """
    found: dict[str, Competitor] = {}
    for fact in facts:
        text = fact.claim.lower()
        # ① 词表命中（原有能力）
        for alias, (canonical, tier) in _COMPETITOR_ALIASES.items():
            if alias in text and canonical not in found:
                found[canonical] = Competitor(
                    name=canonical, tier=tier, evidence=fact  # type: ignore[arg-type]
                )
        # ② 句式抽取（新增，突破固定词表）
        for canonical in _names_from_phrase([fact]):
            if canonical not in found:
                from_wordlist = any(
                    v[0] == canonical for v in _COMPETITOR_ALIASES.values()
                )
                found[canonical] = Competitor(
                    name=canonical,
                    tier=_tier_for(canonical),  # type: ignore[arg-type]
                    # 词表外名字的分层是推断，显式留痕，不伪装成有据标注
                    tier_inferred=not from_wordlist,
                    evidence=fact,
                )
    return list(found.values())


def _classify_slots(facts: Iterable[Fact]) -> dict[str, list[Fact]]:
    """把 facts 归到固定框架槽位；归不进的不丢，放 other。"""
    slots: dict[str, list[Fact]] = {k: [] for k in _SLOT_KEYWORDS}
    slots["other"] = []
    for fact in facts:
        text = fact.claim.lower()
        matched = False
        for slot, keywords in _SLOT_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                slots[slot].append(fact)
                matched = True
                break
        if not matched:
            slots["other"].append(fact)
    return slots


def _build_comparison_matrix(
    company: str, facts: list[Fact], competitors: list[Competitor]
) -> ComparisonMatrix:
    """事实对比矩阵：每个维度找一条提到该主体的原文 fact 搬运，不生成判断。

    无对应事实的 (维度, 主体) 记进 missing，绝不脑补。
    """
    cells: list[MatrixCell] = []
    missing: list[str] = []
    targets = [company] + [c.name for c in competitors]
    for dimension in _SLOT_KEYWORDS:
        for target in targets:
            hit = next(
                (
                    f
                    for f in facts
                    if target.lower() in f.claim.lower()
                    and any(kw in f.claim.lower() for kw in _SLOT_KEYWORDS[dimension])
                ),
                None,
            )
            if hit is None:
                missing.append(f"{dimension}/{target}")
                continue
            cells.append(
                MatrixCell(
                    dimension=dimension,
                    company=target,
                    text=hit.claim,  # 原文搬运
                    source_url=hit.source_url,
                )
            )
    return ComparisonMatrix(company=company, cells=cells, missing=missing)


def industry_postprocess(facts: list[Fact], *, company: str) -> dict[str, Any]:
    """行业栏目后处理：竞品识别 + 框架归类 + 事实对比矩阵。"""
    competitors = _detect_competitors(facts)
    slots = _classify_slots(facts)
    matrix = _build_comparison_matrix(company, facts, competitors)
    return {
        "competitors": [c.model_dump(mode="json") for c in competitors],
        "slots": {k: [f.model_dump(mode="json") for f in v] for k, v in slots.items()},
        "comparison_matrix": matrix.model_dump(mode="json"),
    }


def _extract_year(text: str) -> int | None:
    for pattern in _DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            return int(m.group(1))
    return None


def news_postprocess(facts: list[Fact], *, reference_year: int) -> dict[str, Any]:
    """新闻栏目后处理：时效标注（推断日期）+ 事件去重（保留多来源）。

    不删事实——只给每条 fact 附加推断年份，并把"同一事件多条"聚成组。
    是否过滤由上层决定；这里保留全部并标注，避免误删（日期是从正文抠的，不精确）。
    """
    enriched: list[dict[str, Any]] = []
    for fact in facts:
        year = _extract_year(fact.claim)
        enriched.append(
            {
                **fact.model_dump(mode="json"),
                "inferred_year": year,
                "date_is_inferred": year is not None,  # 正文抠的，非结构化字段
                "stale": year is not None and year < reference_year - 1,
            }
        )

    # 事件去重：按 (动作组, 推断年份) 分组；无动作词的各自单独
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in enriched:
        action_key = None
        for action_group in _EVENT_ACTIONS:
            if any(word in item["claim"] for word in action_group):
                action_key = action_group[0]  # 归并键用组内第一个词
                break
        key = f"{action_key or 'other'}:{item['inferred_year']}"
        groups.setdefault(key, []).append(item)

    deduped = []
    for key, items in groups.items():
        urls = sorted({str(i["source_url"]) for i in items})
        deduped.append(
            {
                "event_key": key,
                "count": len(items),
                "multi_source": len(urls) >= 2,  # 客观计数，不判重要性
                "source_urls": urls,
                "claims": [i["claim"] for i in items],
            }
        )
    return {
        "items": enriched,
        "events": deduped,
        "reference_year": reference_year,
    }


def postprocess_from_briefing(
    briefings: dict[str, dict[str, Any]],
    *,
    company: str,
    reference_year: int,
    source_docs: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """从 briefing 节点的 briefings 输出跑后处理，供上层可选接入。

    处理 industry / news / financial 三栏；其它栏目原样不动。
    `source_docs` 提供时，financial 用它做数字保真（金额回原文核对）。
    """
    from capabilities.finance_postprocess import finance_postprocess

    out: dict[str, Any] = {}

    def to_facts(section: str) -> list[Fact]:
        result = []
        for raw in briefings.get(section, {}).get("facts", []):
            fact = _fact_from(raw)
            if fact is not None:
                result.append(fact)
        return result

    ind_facts = to_facts("industry")
    if ind_facts:
        out["industry"] = industry_postprocess(ind_facts, company=company)
    news_facts = to_facts("news")
    if news_facts:
        out["news"] = news_postprocess(news_facts, reference_year=reference_year)
    fin_facts = to_facts("financial")
    if fin_facts:
        fin_docs = (source_docs or {}).get("financial", [])
        source_texts = {str(d["url"]): str(d.get("content", "")) for d in fin_docs}
        out["financial"] = finance_postprocess(fin_facts, source_texts=source_texts)
    return out
