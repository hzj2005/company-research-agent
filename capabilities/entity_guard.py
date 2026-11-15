"""S10-A 同名实体消歧：在证据进入合成之前，把「名字里带这家公司、但根本不是这家公司」的文档挡掉。

真机证据（2026-11-15 那次真实检索，`evals/cache/tavily/` 可离线复现）：
financial 栏目 3 条里有一条标题是
`Notion VTec Berhad (0083.KL) Valuation Measures & Financial Statistics`
—— 马来西亚上市公司，与 Notion 毫无关系。抽取层把这一篇拆成 10 条 fact，
占满了整个 Financial 栏目，也是 S8.4 judge 判 refuted 的直接原因。

**判定策略：只在高精度信号上动手，宁可漏也不误杀。**

1. `ticker_binding`：标题里出现 `{公司名} <扩展名> (<交易所代码>)`，且扩展名里含有
   **法域后缀**（Berhad / Bhd / Sdn / Pte / GmbH / AG / SA / NV / BV / KK / SpA / Oy / AB）。
   `Notion VTec Berhad (0083.KL)` 命中；`Apple Inc. (AAPL)` 不命中（`Inc.` 是通用后缀）。
2. `listing_page`：标题里公司名后面的扩展名含法域后缀，**且**文档命中 ≥2 个股票行情词
   （price-to-book / shares outstanding / 52 week …）。这是「一张行情页」的特征，
   没有 ticker 括号时靠它兜底。
3. `incoherent_profile`（跨文档）：同一栏目里几篇文档指向**不同的公司官网域名**，
   且其中一篇的成立年份与栏目内多数不同 —— 说明它们讲的不是同一家公司。

第 3 条来自另一个真机发现。原本以为是「2013 / 2014 两个来源说法冲突」，回看原文才
看清：CB Insights 那页写的是 `notion.online`，「editorial publishing and curation
within the music, fashion, and creative industries」，2014 年在伦敦成立 —— 那是一家
做音乐时尚内容与半年刊杂志的英国公司，不是做协作工具的那个 Notion。所以「自相矛盾」
和「总部写成伦敦门牌」两个症状其实是同一个根因：**同名不同实体**。

判定只在两个信号同时成立时才动手：域名互不相同（说明是两个品牌）**且** 成立年份与
栏目多数不符（说明其中一篇是少数派）。只有域名冲突、年份一致时不拒 —— 那可能是同一
公司的多品牌站点。

**刻意不做的事**：不猜 `Sia Partners buys … Notion Consulting` 这类同名不同业务的
公司。它们没有行情页特征，任何纯字面规则都会误杀 —— `Notion Labs, Inc.` 就是 Notion
自己注册的实体名，把带后缀的名字一律当异实体是错的。这类留给人工复核，不自动拒绝；
本模块只承担「上市公司代码混入」这一种最高危、也最容易确证的情形。

**全灭护栏**：如果某个栏目里所有文档都被判为异实体，说明规则在这家公司名上失效
（例如用户调研的正是那家带法域后缀的外国公司），此时**全部放行**并留痕
`all_rejected_fallback=True`。隔离器不允许把一个栏目清空。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)

# 通用企业后缀：跟在公司名后面不构成「另一个实体」。
# `Notion Labs, Inc.` 是 Notion 自己的实体名，必须放行。
GENERIC_SUFFIX = frozenset({
    "labs", "lab", "inc", "inc.", "incorporated", "ltd", "ltd.", "limited",
    "llc", "llp", "corp", "corp.", "corporation", "co", "co.", "company",
    "group", "holding", "holdings", "technologies", "technology", "software",
    "systems", "solutions", "platform", "platforms", "ai", "pbc", "global",
})

# 法域后缀：语言体系之外的公司注册形态。它们几乎只出现在「另一个法域的实体」上。
JURISDICTION_SUFFIX = frozenset({
    "berhad", "bhd", "bhd.", "sdn", "pte", "pte.", "pty", "gmbh", "ag", "sa",
    "s.a.", "nv", "bv", "kk", "k.k.", "spa", "s.p.a.", "oy", "ab", "plc",
    "kft", "zrt", "as", "asa",
})

# 股票行情页的典型词；命中 >= 2 个才认为「这是一张行情页」
LISTING_TERMS = (
    "price-to-book", "price-to-sales", "price-to-earnings", "shares outstanding",
    "52 week", "fifty-two week", "market price", "dividend rate", "dividend yield",
    "enterprise-to-revenue", "valuation measures", "key statistics",
    "market cap", "stock price", "share price", "p/e ratio",
)

# 交易所代码：0083.KL / 7203.T / 600519.SS（只认「数字 + 点 + 字母」，
# 不认 `NOTN:US` 这类冒号形式 —— 冒号在正文里太常见，误报率高）
_TICKER = r"[0-9]{3,6}\.[A-Z]{1,3}"

_WORD = r"[A-Za-z][\w&.\-]*"


def _norm_words(text: str) -> list[str]:
    return [w.lower().strip(".,;:()") for w in text.split()]


def _has_jurisdiction_suffix(expansion: str) -> str | None:
    """扩展名里是否出现法域后缀；返回命中的那个词，便于写进留痕。"""
    for word in _norm_words(expansion):
        if word in JURISDICTION_SUFFIX:
            return word
    return None


def ticker_binding(title: str, company: str) -> tuple[str, str] | None:
    """标题里形如 `{公司名} <扩展名> (<交易所代码>)` 的绑定；返回 (扩展名, 代码)。"""
    if not company or not title:
        return None
    pattern = re.compile(
        r"(?<![\w])" + re.escape(company) + r"\s+"
        r"(?P<ext>" + _WORD + r"(?:\s+" + _WORD + r"){0,4})"
        r"\s*\(\s*(?P<ticker>" + _TICKER + r")\s*\)",
        re.IGNORECASE,
    )
    m = pattern.search(title)
    if not m:
        return None
    return m.group("ext").strip(), m.group("ticker")


def expansion_after(title: str, company: str) -> str | None:
    """标题里紧跟在公司名之后的 1–4 个词（到括号或标点为止）。"""
    if not company or not title:
        return None
    pattern = re.compile(
        r"(?<![\w])" + re.escape(company) + r"\s+"
        r"(?P<ext>" + _WORD + r"(?:\s+" + _WORD + r"){0,3})",
        re.IGNORECASE,
    )
    m = pattern.search(title)
    return m.group("ext").strip() if m else None


def listing_term_hits(text: str) -> list[str]:
    low = text.lower()
    return [t for t in LISTING_TERMS if t in low]


# ---- 跨文档「实体画像」比对用的抽取 ----------------------------------------

# 独占一行的裸域名：CB Insights 那页把 `notion.online` 单独放在标题下面
_DOMAIN_ONLY_LINE = re.compile(
    r"(?m)^\s*(?:https?://)?(?:www\.)?"
    r"([a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+)*\.[a-z]{2,10})\s*$",
    re.IGNORECASE,
)
# `www.xxx.com` 形式：PitchBook 那页在 `Website` 下面写 `www.notion.com`
_WWW_DOMAIN = re.compile(
    r"\bwww\.([a-z0-9][a-z0-9\-]*(?:\.[a-z0-9\-]+)*\.[a-z]{2,10})\b",
    re.IGNORECASE,
)
_FOUNDED = re.compile(
    r"(?:founded|established|incorporated)\b\D{0,24}?\b((?:1[89]|20)\d{2})\b",
    re.IGNORECASE,
)


def _hostname(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "", re.IGNORECASE)
    return m.group(1).lower().removeprefix("www.") if m else ""


def _same_site(a: str, b: str) -> bool:
    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def official_domains(content: str, source_url: str) -> list[str]:
    """文档里出现的「公司官网域名」，已排除来源站自身的域名。"""
    src = _hostname(source_url)
    found = {m.group(1).lower() for m in _WWW_DOMAIN.finditer(content)}
    found |= {m.group(1).lower() for m in _DOMAIN_ONLY_LINE.finditer(content)}
    return sorted(d for d in found if not _same_site(d, src))


@dataclass(frozen=True)
class DocProfile:
    """一篇文档的实体画像：官网域名 + 成立年份。"""

    url: str
    domains: tuple[str, ...]
    founded_year: str | None


def profile_of(doc: Mapping[str, Any]) -> DocProfile:
    content = str(doc.get("content") or "")
    url = str(doc.get("url") or "")
    m = _FOUNDED.search(content)
    return DocProfile(
        url=url,
        domains=tuple(official_domains(content, url)),
        founded_year=m.group(1) if m else None,
    )


def _majority(values: list[str]) -> str | None:
    """唯一多数；出现并列第一就返回 None（无法判定，宁可不动作）。"""
    if not values:
        return None
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    top = max(counts.values())
    winners = [v for v, c in counts.items() if c == top]
    return winners[0] if len(winners) == 1 else None


def find_incoherent(docs: list[Mapping[str, Any]]) -> list[tuple[Mapping[str, Any], dict[str, Any]]]:
    """找出「讲的不是同一家公司」的文档；返回 [(文档, 留痕记录)]。

    两个条件必须同时成立，缺一不拒：
    - 官网域名与另一篇**完全没有交集**（两个品牌，而不是同品牌的多站点）；
    - 成立年份与栏目内唯一多数不同（说明这篇是少数派）。
    """
    profiles = [profile_of(d) for d in docs]
    majority_year = _majority([p.founded_year for p in profiles if p.founded_year])

    flagged: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    for index, profile in enumerate(profiles):
        if not profile.domains or not profile.founded_year:
            continue
        clashes = [
            other.url
            for j, other in enumerate(profiles)
            if j != index
            and other.domains
            and not (set(profile.domains) & set(other.domains))
        ]
        if not clashes:
            continue
        if majority_year is None or profile.founded_year == majority_year:
            continue
        flagged.append(
            (
                docs[index],
                {
                    "code": "incoherent_profile",
                    "reason": (
                        f"官网域名 {'/'.join(profile.domains)} 与同栏目其它来源不一致，"
                        f"且成立年份 {profile.founded_year} 与栏目多数 {majority_year} 不同"
                    ),
                    "domains": list(profile.domains),
                    "founded_year": profile.founded_year,
                    "majority_year": majority_year,
                    "conflicting_urls": clashes,
                },
            )
        )
    return flagged


@dataclass(frozen=True)
class GuardVerdict:
    """一篇文档的实体判定结果。`keep=False` 表示「不是这家公司」。"""

    keep: bool
    code: str
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GuardResult:
    kept: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    all_rejected_fallback: bool = False

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


class EntityGuard:
    """按公司名给文档做实体一致性判定。纯字符串运算，0 次网络/模型调用。"""

    def __init__(self, company: str, *, enabled: bool = True):
        self.company = (company or "").strip()
        self.enabled = bool(enabled) and bool(self.company)

    def judge(self, doc: Mapping[str, Any]) -> GuardVerdict:
        if not self.enabled:
            return GuardVerdict(True, "guard_disabled", "消歧开关关闭")
        title = str(doc.get("title") or "").strip()
        content = str(doc.get("content") or "")[:300]
        if not title:
            # 没有标题就无法判断实体；不拿内容硬猜，保持原行为
            return GuardVerdict(True, "no_title", "该文档没有标题，不做实体判定")

        bound = ticker_binding(title, self.company)
        if bound:
            expansion, ticker = bound
            suffix = _has_jurisdiction_suffix(expansion)
            if suffix:
                return GuardVerdict(
                    False,
                    "ticker_binding",
                    f"标题把公司名扩张成「{self.company} {expansion}」并绑定了交易所代码 {ticker}",
                    {"expansion": expansion, "ticker": ticker, "suffix": suffix},
                )

        expansion = expansion_after(title, self.company)
        if expansion:
            suffix = _has_jurisdiction_suffix(expansion)
            if suffix:
                hits = listing_term_hits(f"{title} {content}")
                if len(hits) >= 2:
                    return GuardVerdict(
                        False,
                        "listing_page",
                        f"标题扩张名含法域后缀「{suffix}」且正文是股票行情页（命中 {len(hits)} 个行情词）",
                        {"expansion": expansion, "suffix": suffix, "listing_terms": hits},
                    )

        # 弱信号一律放行：`Notion Reaches $10 Billion`、`Notion Consulting` 都属于
        # 下一条规则管不了的情形，宁可漏过也不误杀
        return GuardVerdict(True, "same_entity", "未发现异实体信号")

    def filter_docs(
        self, docs: Iterable[Mapping[str, Any]]
    ) -> GuardResult:
        """分批判定并应用全灭护栏。

        `docs` 里的元素必须带 `url`，留痕要用；缺 url 的按空串记。
        """
        items = [dict(d) for d in docs]
        kept: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []

        # 开关关闭时两阶段都要停：否则「关掉消歧」只是关掉了单文档规则，
        # 跨文档一致性还在偷偷改证据集，A/B 对照会失真（第一版实测踩到）。
        if not self.enabled:
            return GuardResult(kept=items, rejected=[])

        for doc in items:
            verdict = self.judge(doc)
            if not verdict.keep:
                rejected.append(
                    {
                        "url": str(doc.get("url") or ""),
                        "title": str(doc.get("title") or "")[:160],
                        "code": verdict.code,
                        "reason": verdict.reason,
                        **verdict.evidence,
                    }
                )
            else:
                kept.append(doc)

        if items and not kept:
            logger.warning(
                "实体消歧把栏目清空了（%d 篇全部被拒），判定规则可能不适用于该公司名，"
                "本次全部放行并留痕", len(items),
            )
            return GuardResult(kept=items, rejected=[], all_rejected_fallback=True)

        # 阶段 2：跨文档一致性。至少两篇才有比较对象。
        if len(kept) >= 2:
            flagged = find_incoherent(kept)
            flagged_urls = {str(doc.get("url") or "") for doc, _ in flagged}
            for doc, record in flagged:
                rejected.append(
                    {
                        "url": str(doc.get("url") or ""),
                        "title": str(doc.get("title") or "")[:160],
                        **record,
                    }
                )
            if flagged_urls:
                kept = [
                    doc for doc in kept if str(doc.get("url") or "") not in flagged_urls
                ]

        if rejected:
            logger.info(
                "实体消歧拒绝 %d / %d 篇：%s",
                len(rejected), len(items), [r["url"] for r in rejected],
            )
        return GuardResult(kept=kept, rejected=rejected)
