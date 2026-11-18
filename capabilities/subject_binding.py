"""财务栏目：主体绑定——先确认「这是哪家公司」，再谈钱。

为什么财务需要单独一步（R7）：
财务事实的主体一旦搞错，错误会以「数字」的形式出现，读者无法察觉。实测
（2026-11-15 / 11-18 两次真实检索）都撞到同一类污染：`Notion VTec Berhad
(0083.KL)` 是马来西亚上市公司，被当成 Notion 的财报读进来。

`EntityGuard` 解决的是「明显异实体混入」（法域后缀 + 行情词），本模块解决的是
另一个问题：**这家公司到底上没上市**。它决定财务段落该不该出现市值/股价，
也决定有没有一个 ticker 可以用来约束后续证据。

判定策略（只在高精度信号上开口，宁可 unknown 也不猜）：
1. 公司名后**紧邻**括号里的代码（`Notion (NYSE: NOTN)` / `Notion (0083.KL)`）
   → listed。要求紧邻，所以 `Notion VTec Berhad (0083.KL)` 不会误命中。
2. 独立的交易所代码句式（`NASDAQ: NOTN`）且同一文档出现公司名 → listed。
3. `未上市 / 非上市 / privately held / unlisted` → not_listed。
4. 一类有一类无、或都没命中 → unknown。

**unknown 不等于 not_listed**：没搜到不代表没上市。调用方不得据此删除任何数据，
只影响措辞。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

_EXCHANGES = r"NASDAQ|NYSE|AMEX|HKEX|LSE|TSE|SSE|SZSE"
_UNLISTED = re.compile(
    r"未上市|非上市|未公开上市|private(?:ly)?\s+(?:held|company|owned)|unlisted",
    re.IGNORECASE,
)
_EXCHANGE_CODE = re.compile(
    rf"\b(?P<ex>{_EXCHANGES})\s*[:：]\s*(?P<code>[A-Z]{{1,6}})\b"
)
_CODE_AFTER_NAME = re.compile(
    r"\(\s*(?:(?P<ex>[A-Za-z]{2,10})\s*[:：]\s*)?(?P<code>[A-Z]{1,6}|\d{4}\.[A-Z]{2})\s*\)"
)

SIGNAL_CHARS = 600


@dataclass(frozen=True)
class SubjectBinding:
    status: str  # listed / not_listed / unknown
    ticker: str | None = None
    exchange: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ticker": self.ticker,
            "exchange": self.exchange,
            "evidence": list(self.evidence),
            "reason": self.reason,
        }


def _code_after_name(text: str, name: str) -> tuple[str, str] | None:
    """公司名紧邻括号代码才算数（避免 `X VTec Berhad (0083.KL)` 误判）。"""
    if not name:
        return None
    pattern = re.compile(
        re.escape(name) + r"\s*" + _CODE_AFTER_NAME.pattern, re.IGNORECASE
    )
    m = pattern.search(text)
    if not m:
        return None
    return (m.group("ex") or "", m.group("code"))


def bind_subject(company: str, docs: Iterable[dict[str, Any]]) -> SubjectBinding:
    """从已消歧的文档里判定目标公司的上市状态。"""
    listed: list[dict[str, Any]] = []
    unlisted: list[dict[str, Any]] = []
    ticker: str | None = None
    exchange: str | None = None

    for doc in docs:
        url = str(doc.get("url") or "")
        text = f"{doc.get('title') or ''}\n{(doc.get('content') or '')[:SIGNAL_CHARS]}"

        hit = _code_after_name(text, company)
        if hit:
            exchange, ticker = exchange or (hit[0] or None), ticker or hit[1]
            listed.append({"url": url, "signal": "code_after_name", "code": hit[1]})
            continue

        m = _EXCHANGE_CODE.search(text)
        if m and company.lower() in text.lower():
            exchange = exchange or m.group("ex")
            ticker = ticker or m.group("code")
            listed.append({"url": url, "signal": "exchange_code", "code": m.group("code")})
            continue

        if _UNLISTED.search(text) and company.lower() in text.lower():
            unlisted.append({"url": url, "signal": "unlisted_phrase"})

    if listed and unlisted:
        # 两类信号同时存在：多半是两篇文档在讲不同主体，不猜
        return SubjectBinding(
            status="unknown",
            evidence=[*listed, *unlisted],
            reason="listed_and_unlisted_signals_conflict",
        )
    if listed:
        return SubjectBinding(
            status="listed", ticker=ticker, exchange=exchange,
            evidence=listed, reason="ticker_or_exchange_code_found",
        )
    if unlisted:
        return SubjectBinding(
            status="not_listed", evidence=unlisted, reason="unlisted_phrase_found",
        )
    return SubjectBinding(status="unknown", reason="no_listing_signal")
