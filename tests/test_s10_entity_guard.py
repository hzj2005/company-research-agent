"""S10-A 护栏：同名实体消歧必须只挡「另一个同名实体」，不许误杀真身。

用例全部来自 **2026-11-15 那次真实检索的实际返回**（`docs/LIVE_SCORE.md` 的
三类硬伤之一），不是编的假设。标题字符串直接抄自 `evals/cache/tavily/*.json`，
因此即使缓存被清掉，这些回归用例依然能跑。

**0 次网络 / 0 次模型 / 0 次 Tavily 调用。**
"""

from __future__ import annotations

import asyncio
import glob
import json
from pathlib import Path
from typing import Any

import pytest

from capabilities.entity_guard import (
    EntityGuard,
    expansion_after,
    profile_of,
    ticker_binding,
)
from capabilities.retrieval import build_live_query
from capabilities.tavily_retriever import cache_key
from config.loader import apply_overrides, get_settings
from graph.nodes.collect import make_curate_node
from graph.state import initial_state

COMPANY = "Notion"

# ---- 真机证据：这几条字符串逐字来自那次 Tavily 返回 -------------------------
FOREIGN_TITLE = "Notion VTec Berhad (0083.KL) Valuation Measures & Financial Statistics"
FOREIGN_URL = "https://finance.yahoo.com/quote/0083.KL/key-statistics"
FOREIGN_CONTENT = (
    "Notion VTec Berhad (0083.KL) valuation measures and financial statistics: "
    "price-to-book ratio 0.68, shares outstanding 526,939,733, 52 week high 0.7550."
)

SELF_TITLE = "Notion Labs, Inc. entered into a strategic collaboration with Keio University"
SELF_URL = "https://www.keio.ac.jp/en/news/20260227-172922"

# ---- 另一家 Notion：CB Insights 收录的是 notion.online ----------------------
# 正文原文（节选）：`# Notion` / `notion.online` / `Founded Year 2014` /
# "editorial publishing and curation within the music, fashion, and creative
#  industries" / "based in London, England" / "51 Lloyd Baker Street"
# 这**不是**做协作工具的那个 Notion，单看标题却完全看不出来。
CBINSIGHTS_URL = "https://www.cbinsights.com/company/notion"
CBINSIGHTS_TITLE = "Notion - Products, Competitors, Financials, Employees, Headquarters Locations"
CBINSIGHTS_CONTENT = (
    "CB Insights\n\nNotion company logo\n\n# Notion\n\nnotion.online\n\n"
    "## Founded Year\n\n2014\n\n## About Notion\n\n"
    "Notion is a company with a high-level focus on editorial publishing and curation "
    "within the music, fashion, and creative industries. It was founded in 2014 and is "
    "based in London, England.\n\n## Headquarters Location\n\n51 Lloyd Baker Street\n\n"
    "London, England, WC1X 9AA,\n\nUnited Kingdom\n"
)

# 同一批返回里的真身两篇（用于跨文档一致性对照）
PITCHBOOK_URL = "https://pitchbook.com/profiles/company/168506-47"
PITCHBOOK_TITLE = "Notion 2026 Company Profile: Valuation, Funding & Investors | PitchBook"
PITCHBOOK_CONTENT = (
    "# Notion\n\n## Notion Overview\n\n##  Year Founded  2013  Year Founded\n\n"
    "##  Employees  1,200  Employees\n\n##### Website\n\nwww.notion.com\n\n"
    "Developer of an online work collaboration platform designed to boost productivity."
)
CONTRARY_URL = "https://research.contrary.com/report/notion"
CONTRARY_TITLE = "Report: Notion Business Breakdown & Founding Story | Contrary Research"
CONTRARY_CONTENT = (
    "Notion, founded in 2013 by Ivan Zhao and Simon Last, evolved from a no-code "
    "programming tool to an all-in-one workspace and productivity tool."
)

# 单文档规则看不出来的真身标题（`judge` 必须全部放行）
SAME_TITLES = [
    "Report: Notion Business Breakdown & Founding Story | Contrary Research",
    "Notion 2026 Company Profile: Valuation, Funding & Investors | PitchBook",
    "Notion Competitors: Complete List & Market Landscape",
    "Notion: From Near Collapse to a $10B All‑In‑One Workspace Unicorn | by Xiayi Sun | Medium",
    "Notion Reaches $10 Billion Valuation, Boosted By Remote Work",
    "Buzzy Work App Notion Hits $2 Billion Valuation In New Raise",
    "Keio and Notion Launch Strategic Collaboration to Realize a Top Global AI-Native University",
    "ZoomInfo Launches MCP Integration With Notion Through GTM.AI",
    "Sia Partners buys organizational change expert Notion Consulting",
]


def _doc(title: str, url: str = "https://example.org/x", **extra: Any) -> dict[str, Any]:
    return {
        "url": url,
        "title": title,
        "score": 0.7,
        "content": extra.pop("content", ""),
        "section": "financial",
        **extra,
    }


# ------------------------------------------------------------------ 底层解析

def test_ticker_binding_splits_expansion_from_code() -> None:
    assert ticker_binding(FOREIGN_TITLE, COMPANY) == ("VTec Berhad", "0083.KL")


def test_ticker_binding_ignores_title_without_bracket_code() -> None:
    assert ticker_binding("Notion Reaches $10 Billion Valuation", COMPANY) is None


def test_expansion_after_stops_at_bracket() -> None:
    assert expansion_after(FOREIGN_TITLE, COMPANY) == "VTec Berhad"


# ------------------------------------------------------------------ 判定行为

def test_foreign_listing_page_is_rejected() -> None:
    verdict = EntityGuard(COMPANY).judge(_doc(FOREIGN_TITLE, FOREIGN_URL, content=FOREIGN_CONTENT))
    assert verdict.keep is False
    assert verdict.code == "ticker_binding"
    assert verdict.evidence["ticker"] == "0083.KL"
    assert verdict.evidence["suffix"] == "berhad"


@pytest.mark.parametrize("title", SAME_TITLES)
def test_real_titles_from_the_same_run_are_kept(title: str) -> None:
    """同一批真实返回里的其余 10 条一条都不许误杀。"""
    assert EntityGuard(COMPANY).judge(_doc(title)).keep is True


def test_own_legal_entity_is_not_flagged() -> None:
    """`Notion Labs, Inc.` 是 Notion 自己注册的实体名，绝不能当异实体。"""
    verdict = EntityGuard(COMPANY).judge(_doc(SELF_TITLE, SELF_URL))
    assert verdict.keep is True
    assert verdict.code == "same_entity"


def test_generic_suffix_with_ticker_is_kept() -> None:
    """调研 Apple 时 `Apple Inc. (AAPL)` 是自己，不是异实体。"""
    title = "Apple Inc. (AAPL) Valuation Measures & Financial Statistics"
    assert EntityGuard("Apple").judge(_doc(title)).keep is True


def test_listing_page_rule_catches_when_ticker_is_missing() -> None:
    """标题里没有 `(代码)` 时，靠「法域后缀 + 行情页特征」兜底。"""
    doc = _doc(
        "Notion VTec Berhad Shares Outstanding And Valuation Measures",
        content="price-to-book 0.68; shares outstanding 526,939,733",
    )
    verdict = EntityGuard(COMPANY).judge(doc)
    assert verdict.keep is False
    assert verdict.code == "listing_page"


def test_listing_page_rule_needs_real_listing_terms() -> None:
    """只有法域后缀、没有行情页证据 → 不拒绝（宁可漏也不误杀）。"""
    doc = _doc("Notion VTec Berhad announces a factory expansion", content="factory in Penang")
    assert EntityGuard(COMPANY).judge(doc).keep is True


def test_document_without_title_is_kept() -> None:
    assert EntityGuard(COMPANY).judge({"url": "u", "title": "", "content": "x"}).keep is True


def test_switch_off_disables_every_rule() -> None:
    guard = EntityGuard(COMPANY, enabled=False)
    assert guard.judge(_doc(FOREIGN_TITLE, FOREIGN_URL, content=FOREIGN_CONTENT)).keep is True


def test_switch_off_also_stops_the_coherence_rule() -> None:
    """关掉开关必须两阶段都停。

    第一版只停了单文档规则，跨文档一致性还在偷偷改证据集 —— 离线回放对照时
    发现「关掉的版本也拒了 cbinsights」，才补上这道断言。
    """
    result = EntityGuard(COMPANY, enabled=False).filter_docs(_company_docs())
    assert len(result.kept) == 3
    assert result.rejected == []


# ------------------------------------------------------------------ 全灭护栏

def test_all_rejected_falls_back_to_keep_everything() -> None:
    """整栏都是异实体页时，说明规则对这家公司名失效 —— 不许把栏目清空。"""
    docs = [
        _doc(f"Acme Berhad ({code}.KL) Valuation Measures", f"https://x/{code}", content=FOREIGN_CONTENT)
        for code in ("1234", "5678")
    ]
    result = EntityGuard("Acme").filter_docs(docs)
    assert result.all_rejected_fallback is True
    assert len(result.kept) == len(docs)
    assert result.rejected == []


def test_partial_rejection_does_not_trigger_fallback() -> None:
    docs = [
        _doc(FOREIGN_TITLE, FOREIGN_URL, content=FOREIGN_CONTENT),
        _doc("Notion Reaches $10 Billion Valuation", "https://www.forbes.com/x"),
    ]
    result = EntityGuard(COMPANY).filter_docs(docs)
    assert result.all_rejected_fallback is False
    assert [d["url"] for d in result.kept] == ["https://www.forbes.com/x"]


# ------------------------------------------------------------- 真实缓存回放

CACHE_DIR = Path(__file__).resolve().parents[1] / "evals" / "cache" / "tavily"


def notion_cache_files() -> list[Path]:
    """精确定位 Notion 那 4 条 query 对应的缓存文件。

    不能直接 `glob("*.json")` —— 后续跑 Figma / Stripe / Airbnb 会往同一个目录写文件，
    把它们一起读进来就变成了「拿别的公司的语料回放 Notion」。缓存 key 由 query + 参数
    决定，这里用同一套 `cache_key()` 重算，找到的就是当时那 4 个。
    """
    settings = get_settings()
    files: list[Path] = []
    for section in settings.graph.sections:
        key = cache_key(
            build_live_query(COMPANY, section, 0),
            section=section,
            max_results=settings.retrieval.max_results_per_query,
            search_depth=settings.retrieval.search_depth,
            topic=settings.retrieval.topics.get(f"{section}_analyzer", "general"),
        )
        path = CACHE_DIR / f"{key}.json"
        if path.exists():
            files.append(path)
    return files


@pytest.mark.skipif(
    len(notion_cache_files()) < 4,
    reason="Notion 的真实检索缓存不在本地（evals/cache/ 被 gitignore），跳过全量回放",
)
def test_replay_real_tavily_cache_rejects_exactly_two() -> None:
    """用那次真实返回的 12 篇原文回放：恰好拒 2 篇，且就是真机报告里的两处硬伤。

    - `finance.yahoo.com/quote/0083.KL`：马来西亚上市公司 Notion VTec Berhad；
    - `cbinsights.com/company/notion`：另一家 Notion（notion.online，音乐时尚内容公司）。

    剩下 10 篇全部保留 —— 这是「不误杀」的直接证据。
    """
    guard = EntityGuard(COMPANY)
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for path in notion_cache_files():
        raw = json.loads(path.read_text(encoding="utf-8"))
        docs = [
            {
                "url": d["metadata"]["url"],
                "title": d["metadata"]["title"],
                "content": d["page_content"],
                "score": d["metadata"].get("score", 0.0),
                "section": d["metadata"].get("section", ""),
            }
            for d in raw
        ]
        result = guard.filter_docs(docs)
        kept.extend(result.kept)
        rejected.extend(result.rejected)

    assert len(kept) + len(rejected) == 12
    assert len(rejected) == 2, [r["url"] for r in rejected]
    by_url = {r["url"]: r for r in rejected}
    assert by_url[FOREIGN_URL]["code"] == "ticker_binding"
    assert by_url[FOREIGN_URL]["ticker"] == "0083.KL"
    assert by_url[CBINSIGHTS_URL]["code"] == "incoherent_profile"
    assert by_url[CBINSIGHTS_URL]["domains"] == ["notion.online"]
    assert by_url[CBINSIGHTS_URL]["founded_year"] == "2014"
    assert by_url[CBINSIGHTS_URL]["majority_year"] == "2013"

    # 不误杀：留下的 10 篇里不该再有异实体
    for doc in kept:
        assert "VTec" not in doc["title"]
        assert "notion.online" not in doc["content"]


# ------------------------------------------------------- 跨文档一致性（画像）

def test_profile_extracts_domain_and_founding_year() -> None:
    profile = profile_of(
        {"url": CBINSIGHTS_URL, "title": CBINSIGHTS_TITLE, "content": CBINSIGHTS_CONTENT}
    )
    assert profile.domains == ("notion.online",)
    assert profile.founded_year == "2014"


def test_source_site_domain_is_never_treated_as_the_company_website() -> None:
    """`cbinsights.com` 是来源站，不能混进「公司官网」候选。"""
    profile = profile_of(
        {"url": CBINSIGHTS_URL, "title": CBINSIGHTS_TITLE, "content": CBINSIGHTS_CONTENT}
    )
    assert "cbinsights.com" not in profile.domains


def _company_docs() -> list[dict[str, Any]]:
    return [
        _doc(CONTRARY_TITLE, CONTRARY_URL, content=CONTRARY_CONTENT),
        _doc(CBINSIGHTS_TITLE, CBINSIGHTS_URL, content=CBINSIGHTS_CONTENT),
        _doc(PITCHBOOK_TITLE, PITCHBOOK_URL, content=PITCHBOOK_CONTENT),
    ]


def test_two_notions_in_one_section_only_the_odd_one_is_dropped() -> None:
    """真机三篇里，只有 notion.online 那篇被判异实体；两篇真身保留。"""
    result = EntityGuard(COMPANY).filter_docs(_company_docs())
    assert [d["url"] for d in result.kept] == [CONTRARY_URL, PITCHBOOK_URL]
    assert [r["url"] for r in result.rejected] == [CBINSIGHTS_URL]
    record = result.rejected[0]
    assert record["code"] == "incoherent_profile"
    assert record["domains"] == ["notion.online"]
    assert record["majority_year"] == "2013"
    assert CBINSIGHTS_URL in record["url"]  # 留痕里带 url，能直接点开核对


def test_shared_domain_means_same_company() -> None:
    """两篇都指向 notion.com，只是写法不同 → 同一个品牌，不拒。"""
    docs = [
        _doc("Notion company profile", "https://a.example/1",
             content="Founded Year 2013; Website www.notion.com"),
        _doc("Notion overview", "https://b.example/2",
             content="Founded Year 2014; see www.notion.com/about for details"),
    ]
    assert EntityGuard(COMPANY).filter_docs(docs).rejected_count == 0


def test_domain_clash_alone_is_not_enough() -> None:
    """品牌多站点（notion.com / notion.so）但成立年份一致 → 不拒。"""
    docs = [
        _doc("Notion profile", "https://a.example/1", content="Founded 2013; www.notion.com"),
        _doc("Notion docs", "https://b.example/2", content="Founded 2013; www.notion.so"),
    ]
    assert EntityGuard(COMPANY).filter_docs(docs).rejected_count == 0


def test_tied_years_disable_the_coherence_rule() -> None:
    """年份 1:1 时没有多数，规则主动弃权 —— 宁可不判也不瞎判。"""
    docs = [
        _doc("Notion profile", "https://a.example/1", content="Founded 2013; www.notion.com"),
        _doc("Notion other", "https://b.example/2", content="Founded 2014; www.notion.online"),
    ]
    assert EntityGuard(COMPANY).filter_docs(docs).rejected_count == 0


def test_single_document_never_triggers_coherence_check() -> None:
    docs = [_doc(CBINSIGHTS_TITLE, CBINSIGHTS_URL, content=CBINSIGHTS_CONTENT)]
    assert EntityGuard(COMPANY).filter_docs(docs).rejected_count == 0


def test_coherence_rule_needs_body_text_not_just_a_title() -> None:
    """边界：正文里没有官网域名时这条规则看不见它（如实记录，不假装能覆盖）。"""
    docs = [
        _doc(CONTRARY_TITLE, CONTRARY_URL, content=CONTRARY_CONTENT),
        _doc(PITCHBOOK_TITLE, PITCHBOOK_URL, content=PITCHBOOK_CONTENT),
        _doc(CBINSIGHTS_TITLE, CBINSIGHTS_URL, content="Founded Year 2014. Based in London."),
    ]
    assert EntityGuard(COMPANY).filter_docs(docs).rejected_count == 0


def test_mutual_accusation_falls_back_to_keep() -> None:
    """三篇互相都有域名冲突、年份 2:1 —— 只有 2014 那篇是少数派，另外两篇必须留下。"""
    docs = [
        _doc("Notion A", "https://a.example/1", content="Founded 2013; www.notion.com"),
        _doc("Notion B", "https://b.example/2", content="Founded 2014; www.notion.online"),
        _doc("Notion C", "https://c.example/3", content="Founded 2013; www.notion.ai"),
    ]
    result = EntityGuard(COMPANY).filter_docs(docs)
    assert result.all_rejected_fallback is False
    assert [d["url"] for d in result.kept] == ["https://a.example/1", "https://c.example/3"]
    assert [r["url"] for r in result.rejected] == ["https://b.example/2"]


# --------------------------------------------------------------- 接入 curate

def _financial_state() -> dict[str, Any]:
    return {
        **initial_state(COMPANY),
        "financial_data": {
            FOREIGN_URL: _doc(FOREIGN_TITLE, FOREIGN_URL, content=FOREIGN_CONTENT),
            "https://www.forbes.com/x": _doc(
                "Notion Reaches $10 Billion Valuation", "https://www.forbes.com/x"
            ),
        },
    }


def _curate(state: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    settings = apply_overrides(get_settings(), overrides) if overrides else get_settings()
    return asyncio.run(make_curate_node(settings)(state))


def test_curate_drops_foreign_doc_from_evidence_and_references() -> None:
    out = _curate(_financial_state())
    assert FOREIGN_URL not in out["curated_data"]
    assert FOREIGN_URL not in out["references"]
    assert "https://www.forbes.com/x" in out["curated_data"]


def test_curate_writes_an_auditable_guard_note() -> None:
    out = _curate(_financial_state())
    notes = [n for n in out["review_notes"] if n["node"] == "entity_guard"]
    assert len(notes) == 1
    note = notes[0]
    assert note["section"] == "financial"
    assert note["candidates"] == 2
    assert note["kept"] == 1
    assert note["rejected"][0]["url"] == FOREIGN_URL
    assert note["rejected"][0]["ticker"] == "0083.KL"
    assert "Notion VTec Berhad" in note["rejected"][0]["reason"]


def test_curate_switch_off_keeps_the_foreign_doc() -> None:
    """A/B：关掉开关，同一份输入里那一篇会回来 —— 证明是开关在起作用。"""
    out = _curate(_financial_state(), **{"features.entity_guard": False})
    assert FOREIGN_URL in out["curated_data"]
    assert not [n for n in out["review_notes"] if n["node"] == "entity_guard"]


def test_curate_stays_quiet_when_nothing_is_rejected() -> None:
    state = {
        **initial_state(COMPANY),
        "financial_data": {
            "https://www.forbes.com/x": _doc(
                "Notion Reaches $10 Billion Valuation", "https://www.forbes.com/x"
            )
        },
    }
    out = _curate(state)
    assert not [n for n in out["review_notes"] if n["node"] == "entity_guard"]


# --------------------------------------------- 端到端回放：引用清单前后对照

FIELD_BY_SECTION = {
    "company": "company_data",
    "industry": "industry_data",
    "financial": "financial_data",
    "news": "news_data",
}


def _replay_state() -> dict[str, Any]:
    state = initial_state(COMPANY)
    for path in notion_cache_files():
        for d in json.loads(path.read_text(encoding="utf-8")):
            meta = d["metadata"]
            state[FIELD_BY_SECTION[meta["section"]]][meta["url"]] = {
                "url": meta["url"],
                "title": meta["title"],
                "score": meta.get("score", 0.0),
                "content": d["page_content"],
                "section": meta["section"],
                "round": 0,
                "source": "tavily",
            }
    return state


@pytest.mark.skipif(
    len(notion_cache_files()) < 4,
    reason="Notion 的真实检索缓存不在本地（evals/cache/ 被 gitignore），跳过端到端回放",
)
def test_replay_reference_list_shrinks_from_11_to_9() -> None:
    """同一批真实检索原文，开关前后 References 从 11 条变 9 条，多的那两条正是硬伤。

    11 这个数字与真机产物 `evals/live_run.json` 的 References 条数一致，
    说明回放用的就是那次真实运行的语料。
    """
    state = _replay_state()
    off = _curate(state, **{"features.entity_guard": False})
    on = _curate(state)

    assert len(off["references"]) == 11
    assert len(on["references"]) == 9

    removed = set(off["references"]) - set(on["references"])
    assert removed == {FOREIGN_URL, CBINSIGHTS_URL}

    # 其余 9 条一条不动
    assert set(off["references"]) & set(on["references"]) == set(on["references"])
