"""R7 验收：财务主体绑定（上市状态判定）。

验证「只在高精度信号上开口」：
- 公司名**紧邻**括号代码才算上市；
- `Notion VTec Berhad (0083.KL)` 这类同名异实体不能算；
- 未上市信号单独成立；
- 都没有 → unknown（不得当作未上市）。
"""

from __future__ import annotations

from capabilities.subject_binding import bind_subject


def _doc(url: str, title: str, content: str = "") -> dict:
    return {"url": url, "title": title, "content": content}


def test_code_right_after_name_is_listed() -> None:
    docs = [_doc("https://e.org/a", "Notion (NYSE: NOTN) 股价与财报")]
    b = bind_subject("Notion", docs)
    assert b.status == "listed"
    assert b.ticker == "NOTN"
    assert b.exchange == "NYSE"


def test_same_name_foreign_entity_does_not_make_our_company_listed() -> None:
    """`Notion VTec Berhad (0083.KL)` 是另一家公司，不能当 Notion 上市的证据。"""
    docs = [_doc("https://e.org/fake", "Notion VTec Berhad (0083.KL) Valuation Measures")]
    b = bind_subject("Notion", docs)
    assert b.status == "unknown", "名字不紧邻括号时不能认成上市"


def test_unlisted_phrase_is_not_listed() -> None:
    docs = [_doc("https://e.org/b", "Notion 公司介绍", "Notion 是一家未上市私人公司。")]
    b = bind_subject("Notion", docs)
    assert b.status == "not_listed"


def test_no_signal_is_unknown_not_unlisted() -> None:
    docs = [_doc("https://e.org/c", "Notion 产品介绍", "协作工作区工具。")]
    b = bind_subject("Notion", docs)
    assert b.status == "unknown"
    assert b.reason == "no_listing_signal"


def test_conflicting_signals_stay_unknown() -> None:
    docs = [
        _doc("https://e.org/d", "Notion (NASDAQ: NOTN) 财报"),
        _doc("https://e.org/e", "Notion 简介", "Notion 未上市。"),
    ]
    b = bind_subject("Notion", docs)
    assert b.status == "unknown"
    assert b.reason == "listed_and_unlisted_signals_conflict"
