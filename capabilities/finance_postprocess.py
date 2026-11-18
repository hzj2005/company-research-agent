"""S5 财务后处理：数字保真 + 融资时间线 + 同轮冲突标注 + FundingRound 构造。

补齐 PROJECT_PLAN_V2.md 4.1.2 里因"抽取链下沉风险大"而搁置的 4 个能力。
关键发现（2026-11-17）：这 4 个节点里只有 finance_extract 真正需要 LLM，
其余 3 个用正则即可；且 fixture 财务文档的金额/年份/轮次都能规则抠出
（实测 series-a=5000万美元/2021/A轮，series-b=2亿美元/2023/B轮）。
所以不走"抽取链下沉"的高风险路线，改用纯规则后处理，零报告漂移。

设计红线：
- **数字保真**：金额必须原样出现在原文，否则标注 money_not_in_source，不静默采信；
- **时间线**：不同轮次的金额不同 = 正常时间序列，**不判冲突**；
- **同轮冲突**：只有同一轮次出现两个不同金额才标注；
- **估值≠融资**："融资 2 亿，估值 100 亿"只取融资额，估值不能当融资金额。

纯规则、0 模型 0 网络。默认随 features.postprocess 开关，不改报告文本。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable

from graph.contracts import Fact, FundingRound

logger = logging.getLogger(__name__)

# 轮次：A 轮 / B 轮 / Pre-A 轮 / 种子轮 ...
_ROUND = re.compile(r"((?:Pre-?[A-D]|[A-D])\s*轮|种子轮|天使轮)", re.IGNORECASE)
# 年份
_YEAR = re.compile(r"((?:19|20)\d{2})\s*年")
# 金额：数字 + 单位（万美元/亿美元/万元/亿元/美元/万/亿）
_MONEY = re.compile(r"(\d[\d,.]*\s*(?:万亿美元|亿美元|百万美元|万美元|亿元|万元|亿美元|美元|万|亿))")
# "融资"后紧跟的金额（避开"估值 100 亿"这类干扰）
_FINANCING_MONEY = re.compile(r"融资\s*(\d[\d,.]*\s*(?:万亿美元|亿美元|百万美元|万美元|亿元|万元|美元|万|亿))")
# 投资方："由 X 领投" / "X 参投"
_INVESTOR = re.compile(r"(?:由\s*)?([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z]{1,12})(?:领投|参投)")


def _norm_money(value: str) -> str:
    """归一化金额串用于比对（去空格、去逗号），但展示保留原文。"""
    return re.sub(r"[\s,]", "", value)


# 金额换算表：中英文两套写法都要认，否则「原文 $10 billion、事实 100 亿美元」
# 会被误判成「金额不在原文」（2026-11-18 真实 live 报告实测：4/4 全部误判）
_CN_UNIT = {
    "万亿美元": 1e12, "亿美元": 1e8, "百万美元": 1e6, "万美元": 1e4,
    "亿元": 1e8, "万元": 1e4, "美元": 1.0, "万": 1e4, "亿": 1e8,
}
_EN_UNIT = {"trillion": 1e12, "billion": 1e9, "million": 1e6, "thousand": 1e3}
_CN_MONEY = re.compile(r"(\d[\d,.]*)\s*(万亿美元|亿美元|百万美元|万美元|亿元|万元|美元|万|亿)")
_EN_MONEY = re.compile(
    r"\$\s*(\d[\d,.]*)\s*(trillion|billion|million|thousand)?", re.IGNORECASE
)


def _money_values(text: str) -> list[float]:
    """把一段文本里的金额全部折算成美元数值（只用于比对，不用于展示）。"""
    out: list[float] = []
    for m in _CN_MONEY.finditer(text):
        try:
            out.append(float(m.group(1).replace(",", "")) * _CN_UNIT[m.group(2)])
        except (ValueError, KeyError):
            continue
    for m in _EN_MONEY.finditer(text):
        try:
            scale = _EN_UNIT.get((m.group(2) or "").lower(), 1.0)
            out.append(float(m.group(1).replace(",", "")) * scale)
        except (ValueError, KeyError):
            continue
    return out


def _money_match(amount: str, source_text: str) -> str | None:
    """金额是否出现在原文：先字面，再跨语言数值等价。

    返回 `literal` / `value` / `None`，调用方据此区分「原文直接写了」和
    「原文写的是等价的外文金额」——后者也不算编造，但值得让读者知道是换算过的。
    """
    if _norm_money(amount) in _norm_money(source_text):
        return "literal"
    target = _money_values(amount)
    if not target:
        return None
    for got in _money_values(source_text):
        if abs(got - target[0]) <= max(abs(target[0]) * 0.005, 1.0):
            return "value"
    return None


def _money_in_source(amount: str, source_text: str) -> bool:
    """数字保真：金额归一化后必须能在原文找到（含跨语言数值等价）。"""
    return _money_match(amount, source_text) is not None


def _fact_from(item: dict[str, Any]) -> Fact | None:
    try:
        return Fact(
            claim=str(item["claim"]),
            source_url=item["source_url"],
            confidence=float(item.get("confidence", 0.0)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _extract_round(claim: str) -> str | None:
    m = _ROUND.search(claim)
    # 归一化：'A 轮' -> 'A轮'，便于同轮分组比对
    return re.sub(r"\s+", "", m.group(1)) if m else None


def _extract_year(claim: str) -> str | None:
    m = _YEAR.search(claim)
    return m.group(1) if m else None


def _extract_amount(claim: str) -> str | None:
    """优先取'融资'后的金额，避免把估值当融资额。"""
    m = _FINANCING_MONEY.search(claim)
    if m:
        return m.group(1)
    # 没有"融资"字样时退回第一个金额，但标注为推断（由调用方处理）
    fallback = _MONEY.search(claim)
    return fallback.group(1) if fallback else None


def _extract_investors(claim: str) -> list[str]:
    return list(dict.fromkeys(m.group(1) for m in _INVESTOR.finditer(claim)))


def finance_postprocess(
    facts: list[Fact], *, source_texts: dict[str, str] | None = None
) -> dict[str, Any]:
    """财务栏目后处理：时间线 + 数字保真 + 同轮冲突 + FundingRound 契约。

    `source_texts`: url -> 原文 content。提供时做数字保真；不提供则跳过该校验。
    """
    rounds: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []

    for fact in facts:
        claim = fact.claim
        round_name = _extract_round(claim)
        if not round_name:
            continue  # 没有轮次的融资描述不进时间线（如"已披露多轮融资"）
        amount = _extract_amount(claim)
        year = _extract_year(claim)
        investors = _extract_investors(claim)

        entry: dict[str, Any] = {
            "round": round_name,
            "amount": amount,
            "year": year,
            "investors": investors,
            "claim": claim,
            "source_url": str(fact.source_url),
        }

        # 数字保真：金额必须原样出现在原文，否则标注（不静默采信）
        if amount and source_texts:
            source = source_texts.get(str(fact.source_url), "")
            entry["amount_in_source"] = _money_in_source(amount, source)
            if not entry["amount_in_source"]:
                unverified.append(
                    {
                        "source_url": str(fact.source_url),
                        "amount": amount,
                        "reason": "money_not_in_source",
                    }
                )
        rounds.append(entry)

    # 时间线：按年份排序（年份缺失的排最后，稳定）
    timeline = sorted(
        rounds,
        key=lambda r: (r["year"] is None, r["year"] or "", r["round"]),
    )

    # 同轮冲突：只有同一轮次出现不同金额才标注（跨轮差异是正常时间序列）
    by_round: dict[str, set[str]] = {}
    for entry in rounds:
        if entry["amount"]:
            by_round.setdefault(entry["round"], set()).add(_norm_money(entry["amount"]))
    conflicts = [
        {"round": r, "amounts": sorted(amounts)}
        for r, amounts in by_round.items()
        if len(amounts) > 1
    ]

    # B2：用规则把字段填进 S3 定义的 FundingRound 契约（fixture 下够用）
    funding_rounds: list[FundingRound] = []
    for entry in timeline:
        if not entry["amount"]:
            continue
        try:
            funding_rounds.append(
                FundingRound(
                    round_name=entry["round"],
                    amount=entry["amount"],  # 原样保留，不换算
                    announced_year=entry["year"],
                    investors=entry["investors"],
                    evidence=fact_for(entry, facts),
                )
            )
        except (ValueError, TypeError) as exc:
            logger.warning("规则构造 FundingRound 失败，跳过：%s", exc)

    return {
        "timeline": timeline,
        "conflicts": conflicts,
        "unverified_amounts": unverified,
        "funding_rounds": [r.model_dump(mode="json") for r in funding_rounds],
    }


def verify_amounts(
    facts: Iterable[Fact], *, source_texts: dict[str, str] | None = None
) -> dict[str, Any]:
    """只做数字保真：金额是否原样出现在原文。

    与 `finance_postprocess` 内部同源同规则，但**单独可用**——R7 把它提成抽取后
    的独立节点，让「金额核对」有独立留痕，而不是埋在时间线计算里。纯规则、0 调用。
    """
    verified: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []
    unchecked: list[dict[str, Any]] = []

    for fact in facts:
        amount = _extract_amount(fact.claim)
        if not amount:
            continue
        url = str(fact.source_url)
        source = (source_texts or {}).get(url, "")
        item = {"source_url": url, "amount": amount}
        if not source:
            unchecked.append({**item, "reason": "no_source_text"})
            continue
        match = _money_match(amount, source)
        if match:
            verified.append({**item, "match": match})
        else:
            unverified.append({**item, "reason": "money_not_in_source"})

    return {"verified": verified, "unverified": unverified, "unchecked": unchecked}


def fact_for(entry: dict[str, Any], facts: Iterable[Fact]) -> Fact:
    """按 source_url 找回原始 Fact 作为 evidence（必须是真实抽出的那条）。"""
    for fact in facts:
        if str(fact.source_url) == entry["source_url"]:
            return fact
    # 理论上不会发生；保底构造一条同源 Fact，仍指向真实 URL
    return Fact(claim=entry["claim"], source_url=entry["source_url"], confidence=0.0)  # type: ignore[arg-type]
