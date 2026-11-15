"""Generate a zero-network, zero-credit local HTML page for human golden review.

Reads the two *draft* artifacts (never writes a verdict itself):

    evals/golden_live_draft.jsonl    25 candidate facts (5 companies x 5)
    evals/golden_live_review.jsonl  AI-assisted source verification (25 claims)

Writes:

    evals/golden_review.html        self-contained page, all data inlined

The page pre-fills only the *editable* fields (recommended final fact / source
URL / note) from PRESETS below. It does NOT pre-select any verdict button,
does NOT call any API, and does NOT fetch any external resource. The verdict
stays a human click, so the exported `is_human_verification: true` record is
still true. The real evals/golden_live.jsonl is produced later from those
decisions.

Usage:
    uv run python -m evals.build_review_page
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DRAFT = ROOT / "golden_live_draft.jsonl"
REVIEW = ROOT / "golden_live_review.jsonl"
OUTPUT = ROOT / "golden_review.html"

# 逐条复核建议：只填「修正后的事实 / 出处 URL / 备注」，不替用户按结论按钮。
# fact/url 是为「按建议修正」准备的值；note 里写明建议结论与依据。
PRESETS: dict[str, dict[str, str]] = {
    "notion:company:0": {
        "fact": "Notion 于 2013 年创办",
        "url": "https://www.cnbc.com/id/108295653",
        "note": "建议：采纳原样。CNBC 顶部字段就是 Launched: 2013，2025 版同样是 2013。",
    },
    "notion:company:1": {
        "fact": "Notion 总部位于旧金山",
        "url": "https://www.cnbc.com/id/108295653",
        "note": "建议：采纳原样。顶部字段 Headquarters: San Francisco。",
    },
    "notion:company:2": {
        "fact": "CNBC 榜单列出的创始人为 Ivan Zhao（CEO）、Simon Last、Akshay Kothari",
        "url": "https://www.cnbc.com/id/108295653",
        "note": "建议：按建议修正（只改措辞，出处不动）。CNBC 的 Founders 字段确实只有这 3 人；百科镜像另列 6 位早期成员。事实里写明「CNBC 榜单口径」，才不会在「创始人到底几位」上被追问。",
    },
    "notion:industry:0": {
        "fact": "Notion 是模块化协作工作区，把笔记、项目、wiki、数据库组合在一起",
        "url": "https://www.cnbc.com/id/108295653",
        "note": "建议：采纳原样。正文第 2 段逐字一致。",
    },
    "notion:financial:0": {
        "fact": "2021 年 10 月，Notion 完成 2.75 亿美元融资，由红杉资本与 Coatue 领投，投后估值升至 100 亿美元（2021 年时点，历史数据）",
        "url": "https://siliconangle.com/2021/10/08/productivity-startup-notion-valued-10b-latest-275m-funding-round/",
        "note": "建议：按建议修正（事实不动，只换出处）。原 CNBC 链接正文两次全文核对都没有这段，不能当出处；SiliconANGLE 2021-10-08 报道原文写「valuation has jumped to $10 billion from $2 billion last April thanks to a new $275 million funding round led by Sequoia Capital and Coatue」，金额、领投方、估值、月份全对得上。你上一版备注的判断（2021-10 / 2.75 亿美元 / 100 亿美元）保留，只补出处。",
    },
    "figma:company:0": {
        "fact": "Figma 成立于 2012 年",
        "url": "https://www.figma.com/blog/bill-mcdermott-joins-board/",
        "note": "建议：采纳原样。官方 blog 的 About Figma 段有 Founded in 2012。",
    },
    "figma:company:1": {
        "fact": "Dylan Field 是 Figma 联合创始人兼 CEO，并任董事会主席",
        "url": "https://www.figma.com/blog/bill-mcdermott-joins-board/",
        "note": "建议：采纳原样。董事会列表首行 Dylan Field, co-founder and CEO of Figma (Chair)。",
    },
    "figma:industry:0": {
        "fact": "Figma 已从设计工具演进为覆盖构思、设计、开发到交付的协作平台",
        "url": "https://www.figma.com/blog/bill-mcdermott-joins-board/",
        "note": "建议：采纳原样。事实成立；页面原句比草稿 excerpt 更长且用弯引号，那只是引文截断问题，不影响这条事实。",
    },
    "figma:news:0": {
        "fact": "Adobe 与 Figma 于 2023 年 12 月 18 日宣布双方同意终止合并协议，原因是欧委会与英国 CMA 的监管批准无明确路径",
        "url": "https://news.adobe.com/news/news-details/2023/Adobe-and-Figma-Mutually-Agree-to-Terminate-Merger-Agreement/default.aspx",
        "note": "建议：按建议修正。原 brandligo 是第三方公司目录，不宜当标准答案出处；Adobe 官方声明（2023-12-18）原文是 mutual agreement to terminate，并明确写 no clear path to receive necessary regulatory approvals from the European Commission and the UK Competition and Markets Authority。",
    },
    "figma:financial:0": {
        "fact": "Figma 于 2025 年 7 月 31 日在纽交所开始交易，代码 FIG，IPO 发行价 33 美元/股",
        "url": "https://www.figma.com/blog/ipo-pricing/",
        "note": "建议：按建议修正。官方定价公告原文：36,937,080 股、$33.00 per share，股票 expected to begin trading on the New York Stock Exchange on July 31, 2025、代码 FIG；brandligo 的「August 2025 完成 IPO」指 8 月 1 日交割，不是首日交易。",
    },
    "stripe:industry:0": {
        "fact": "Stripe 是为互联网构建经济基础设施的科技公司，企业用其软件收款并在线管理业务",
        "url": "https://stripe.com/newsroom/information",
        "note": "建议：采纳原样。About Stripe 段逐字一致（页面用 en dash，草稿用 hyphen，只是标点）。",
    },
    "stripe:company:0": {
        "fact": "Stripe 在旧金山和都柏林设有双总部",
        "url": "https://stripe.com/newsroom/information",
        "note": "建议：采纳原样。dual headquarters in San Francisco and Dublin 逐字一致。",
    },
    "stripe:company:1": {
        "fact": "Patrick Collison 是联合创始人兼 CEO",
        "url": "https://stripe.com/newsroom/information",
        "note": "建议：采纳原样。Leadership 段是「标题 + 职务」两行，草稿拼成一行才让 excerpt 不是逐字；事实本身成立。",
    },
    "stripe:company:2": {
        "fact": "John Collison 是联合创始人兼总裁",
        "url": "https://stripe.com/newsroom/information",
        "note": "建议：采纳原样。同上，John Collison / Co-founder and President。",
    },
    "stripe:financial:0": {
        "fact": "2024 年通过 Stripe 处理的支付额超过 1.4 万亿美元（官方披露的历史年度数据）",
        "url": "https://stripe.com/newsroom/information",
        "note": "建议：采纳原样。Fast facts 段是「$1.4T+ / in payments processed by businesses on Stripe in 2024.」；「2024 年」这个限定不能删——首页另有 2025 年的 1.9 万亿，删掉就变成错的当前值。",
    },
    "airbnb:company:0": {
        "fact": "Airbnb 起源于 2007 年，两位房东在旧金山住所接待了 3 位旅客",
        "url": "https://news.airbnb.com/fr/about-us/",
        "note": "建议：采纳原样。官方 About 段写 Airbnb was born in 2007 when two hosts welcomed three guests to their San Francisco home；2008 是同页时间线里的「正式发布」，两个口径不冲突。",
    },
    "airbnb:company:1": {
        "fact": "三位创始人为 Brian Chesky、Nathan Blecharczyk、Joe Gebbia",
        "url": "https://news.airbnb.com/fr/about-us/",
        "note": "建议：采纳原样。三人姓名与顺序都对；页面是三条独立姓名 + 职务，草稿的「Les Fondateurs: A, B, C」是拼接。",
    },
    "airbnb:company:2": {
        "fact": "2009 年 3 月，Airbed & Breakfast 正式更名为 Airbnb",
        "url": "https://news.airbnb.com/fr/about-us/",
        "note": "建议：采纳原样。The Airbnb story 时间线：March 2009 Airbnb officially changes our name from Airbed & Breakfast to Airbnb。",
    },
    "airbnb:financial:0": {
        "fact": "Airbnb 于 2020 年 12 月 9 日发布 IPO 定价公告：发行价 68 美元/股，股票预计 2020 年 12 月 10 日在纳斯达克开始交易，代码 ABNB",
        "url": "https://investors.airbnb.com/press-releases/news-details/2020/Airbnb-Announces-Pricing-of-Initial-Public-Offering/default.aspx",
        "note": "建议：按建议修正（只改措辞，出处不动）。公告发布日是 Dec. 9, 2020，原文是 expected to begin trading（预计开始交易）；写成「10 日已上市」超出了这个 URL 能证明的范围。",
    },
    "airbnb:industry:0": {
        "fact": "Airbnb 是连接房东与旅客的在线住宿预订平台，提供民宿、体验与服务",
        "url": "https://news.airbnb.com/about-us/",
        "note": "建议：按建议修正（事实收敛 + 换出处）。原 wikipedia.com 是镜像/仿冒域名、抓取失败；「按每笔预订收取佣金」在 2026 年费率结构下也站不住。改成官方 About 页能直接支撑的「在线住宿预订平台，提供民宿、体验与服务」，删掉佣金与费率表述。",
    },
    "canva:company:0": {
        "fact": "Canva 于 2013 年正式上线",
        "url": "https://www.newswire.co.kr/newsRead.php?no=973123",
        "note": "建议：按建议修正（只换出处）。Business Wire 西语/法语/中文版直取均为 Page Unavailable；newswire.co.kr 是原稿全文转载，正文有「when we first launched Canva back in 2013」，About 段另有 Launched in 2013。",
    },
    "canva:company:1": {
        "fact": "三位联合创始人为 Melanie Perkins、Cliff Obrecht、Cameron Adams",
        "url": "https://www.newswire.co.kr/newsRead.php?no=973123",
        "note": "建议：按建议修正（只换出处）。转载页导语：the 10-year anniversary of Co-founders Melanie Perkins, Cliff Obrecht and Cameron Adams launching Canva。",
    },
    "canva:company:2": {
        "fact": "Canva 的创业故事起步于澳大利亚珀斯（起源地，不等于当前总部）",
        "url": "https://www.newswire.co.kr/newsRead.php?no=973123",
        "note": "建议：按建议修正（换出处 + 保留「起源地」口吻）。原文 While it all started from humble beginnings around a table in Perth, Australia；该稿只说起源，没说总部城市，别写成「总部在珀斯」。",
    },
    "canva:company:3": {
        "fact": "Melanie Perkins 是联合创始人兼 CEO",
        "url": "https://www.newswire.co.kr/newsRead.php?no=973123",
        "note": "建议：按建议修正（只换出处）。引语署名处原文：said Canva Co-founder and CEO, Melanie Perkins。",
    },
    "canva:industry:0": {
        "fact": "Canva 是自述的一体化视觉通信平台（all-in-one visual communication platform），覆盖演示文稿、文档、视频与网站创作",
        "url": "https://www.newswire.co.kr/newsRead.php?no=973123",
        "note": "建议：按建议修正（换出处 + 用官方表述）。导语 the world's only all-in-one visual communication platform，正文 From presentations to documents, videos and websites，两句合起来支撑该事实。",
    },
}


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_rows() -> list[dict]:
    draft = _read_jsonl(DRAFT)
    review = _read_jsonl(REVIEW)

    claims = [r for r in draft if r.get("kind") == "claim"]
    cases = {r["case"]: r.get("company", r["case"]) for r in draft if r.get("kind") == "case"}
    checks = {r["id"]: r for r in review if r.get("kind") == "claim"}

    if len(claims) != 25 or len(checks) != 25:
        raise ValueError(f"expected 25 claims, got draft={len(claims)} review={len(checks)}")

    rows = []
    for claim in claims:
        cid = claim["id"]
        check = checks.get(cid)
        if check is None:
            raise ValueError(f"missing review row for {cid}")
        if check.get("user_verdict") is not None:
            # Never silently adopt a verdict. If someone filled the source file,
            # the page still starts from a clean, explicit human decision.
            pass
        rows.append(
            {
                "id": cid,
                "case": claim["case"],
                "company": cases.get(claim["case"], claim["case"]),
                "section": claim["section"],
                "candidate_fact": claim["candidate_fact"],
                "source_url": claim["source_url"],
                "source_title": claim.get("source_title", ""),
                "source_excerpt": claim.get("source_excerpt", ""),
                "check_hint": claim.get("check_hint", ""),
                "ai_check": check.get("ai_check"),
                "suggested_action": check.get("suggested_action", ""),
                "suggested_source_url": check.get("suggested_source_url"),
                "suggested_fact": check.get("suggested_fact"),
                "evidence_quote": check.get("evidence_quote", ""),
                "source_accessible": check.get("source_accessible"),
                "excerpt_match": check.get("excerpt_match", ""),
                "note": check.get("note", ""),
            }
        )
    return rows


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>真实 golden 人工复核 · 25 条</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin:0; padding:28px 16px 80px; background:#f6f7f9; color:#1c2027;
         font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
  .wrap { max-width:920px; margin:0 auto; }
  h1 { font-size:24px; margin:0 0 8px; }
  .lede { color:#525b68; margin:0 0 18px; }
  .callout { background:#fff8e6; border:1px solid #f0d9a0; border-radius:10px;
             padding:12px 16px; margin:0 0 20px; font-size:14px; }
  .callout b { color:#8a5b00; }
  .warn { display:none; background:#fdeaea; border:1px solid #efb6b6; border-radius:10px;
          padding:12px 16px; margin:0 0 18px; font-size:14px; color:#8a2020; }
  .warn.show { display:block; }
  .warn b { color:#a52a2a; }
  .bar-outer { height:10px; background:#e3e6eb; border-radius:99px; overflow:hidden; }
  .bar-inner { height:100%; width:0; background:#2f6feb; border-radius:99px; transition:width .2s; }
  .toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:14px 0 22px; }
  button { font:inherit; cursor:pointer; border-radius:8px; border:1px solid #cfd5de;
           background:#fff; padding:7px 13px; color:#1c2027; }
  button:hover { border-color:#8fa6cc; }
  button.primary { background:#2f6feb; border-color:#2f6feb; color:#fff; font-weight:600; }
  button.primary:disabled { background:#b6c4dd; border-color:#b6c4dd; cursor:not-allowed; }
  button.on { background:#e8effd; border-color:#2f6feb; color:#1746a2; }
  .stat { color:#525b68; font-size:14px; }
  .card { background:#fff; border:1px solid #e2e5ea; border-radius:12px;
          padding:18px 20px; margin:0 0 16px; box-shadow:0 1px 2px rgba(20,30,50,.04); }
  .card.done { border-color:#b9d3f6; }
  .card-head { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:12px; }
  .idx { color:#8a94a3; font-variant-numeric:tabular-nums; font-size:13px; }
  .tag { font-size:12px; padding:2px 9px; border-radius:99px; background:#eef1f5; color:#4b5563; }
  .tag.verified { background:#e6f5ea; color:#1c6b34; }
  .tag.needs_fix { background:#fff0dc; color:#96560b; }
  .tag.reject { background:#fdeaea; color:#a52a2a; }
  .fact { font-size:17px; font-weight:600; margin:0 0 12px; line-height:1.5; }
  .kv { display:grid; grid-template-columns:88px 1fr; gap:6px 12px; font-size:14px; margin-bottom:10px; }
  .kv dt { color:#8a94a3; }
  .kv dd { margin:0; word-break:break-word; }
  a { color:#2f6feb; }
  blockquote { margin:0 0 10px; padding:9px 12px; background:#f7f8fa; border-left:3px solid #cfd5de;
               border-radius:0 6px 6px 0; color:#3b434f; font-size:13.5px; white-space:pre-wrap; }
  .note { background:#f4f7fd; border-radius:8px; padding:10px 12px; font-size:13.5px; color:#3d4757; margin-bottom:12px; }
  .edit { display:grid; gap:8px; margin:10px 0 12px; }
  .edit label { font-size:13px; color:#6b7482; display:block; margin-bottom:3px; }
  input[type=text], textarea { width:100%; font:inherit; font-size:14px; padding:7px 10px;
      border:1px solid #d5dae2; border-radius:7px; background:#fff; color:#1c2027; }
  textarea { min-height:52px; resize:vertical; }
  .decisions { display:flex; flex-wrap:wrap; gap:8px; }
  .decisions button { flex:1 1 150px; }
  .decisions button.sel-accept { background:#e6f5ea; border-color:#39a05c; color:#155c2b; font-weight:600; }
  .decisions button.sel-fix { background:#fff0dc; border-color:#d98b1f; color:#8a4f05; font-weight:600; }
  .decisions button.sel-reject { background:#fdeaea; border-color:#d9534f; color:#962626; font-weight:600; }
  .saved { color:#1c6b34; font-size:13px; margin-left:6px; }
  .foot { color:#8a94a3; font-size:13px; margin-top:26px; }
  code { background:#eef1f5; padding:1px 5px; border-radius:4px; font-size:13px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>25 条「标准答案」逐条确认</h1>
  <p class="lede">每条看两样东西：<b>候选事实</b> 和 <b>网页原文</b>。点开原链接核对后，选一个结论。全程 0 次 API 调用、0 Tavily 额度。</p>
  <div class="callout"><b>为什么必须你来点：</b>这些事实是 AI 从网页上找来的。要是还让 AI 自己说「对，可以当标准答案」，就成了自己出题自己批卷，面试一问就穿。所以这里默认<b>一条都没判定</b>，只由你点。<br><b>已预填的部分：</b>下面每条的「修正后的事实 / 出处 URL / 备注」已按逐条复核填好（这些只是建议，不是结论），三个结论按钮仍然留空等你点。</div>

  <div class="warn" id="warn"></div>
  <div class="bar-outer"><div class="bar-inner" id="bar"></div></div>
  <div class="toolbar">
    <span class="stat" id="stat"></span>
    <button id="filter">只看未决</button>
    <button id="filterRisky">只看需处理</button>
    <button id="jump">跳到下一条未决</button>
    <button id="export" class="primary" disabled>导出 jsonl</button>
    <button id="copy">复制内容</button>
    <span class="stat" id="msg"></span>
  </div>

  <main id="cards"></main>

  <p class="foot">
    三个结论的意思：<b>采纳原样</b> = 事实和出处都不动；<b>按建议修正</b> = 采纳，但用下面可编辑的事实/链接替换；<b>驳回</b> = 这条不要，正式 golden 里删掉。<br>
    进度自动存在本浏览器里，刷新不会丢。点原链接只是浏览器免费打开网页，不消耗 Tavily 额度。<br>
    导出后把 <code>golden_live_review_filled.jsonl</code> 放进 <code>evals/</code>，或点「复制内容」直接贴给 AI。<br>
    若预览面板不让下载/复制，直接双击 <code>evals/golden_review.html</code> 用浏览器打开即可（纯本地文件，不需要起服务）。
  </p>
</div>

<script type="application/json" id="seed">__SEED_JSON__</script>
<script type="application/json" id="presets">__PRESETS_JSON__</script>
<script>
(function () {
  "use strict";
  var rows = JSON.parse(document.getElementById("seed").textContent);
  var presets = JSON.parse(document.getElementById("presets").textContent);
  var KEY = "golden_live_review_v2";
  var state = {};
  try { state = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { state = {}; }
  // 只补「修正后的事实 / 出处 / 备注」，不写 decision，结论仍由用户点。
  Object.keys(presets).forEach(function (id) {
    var s = state[id] || {};
    var p = presets[id] || {};
    if (s.fact == null || s.fact === "") s.fact = p.fact || "";
    if (s.url == null || s.url === "") s.url = p.url || "";
    if (s.note == null || s.note === "") s.note = p.note || "";
    state[id] = s;
  });
  var onlyPending = false;
  var onlyRisky = false;
  var risky = rows.filter(function (r) { return r.ai_check !== "verified"; });

  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(state)); }
    catch (e) { /* preview sandbox may block storage; decisions still live in memory */ }
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function decided(r) { return state[r.id] && state[r.id].decision; }
  function count() { return rows.filter(decided).length; }

  function render() {
    var host = document.getElementById("cards");
    host.innerHTML = "";
    rows.forEach(function (r, i) {
      var s = state[r.id] || {};
      if (onlyPending && decided(r)) return;
      if (onlyRisky && r.ai_check === "verified") return;
      var card = document.createElement("section");
      card.className = "card" + (decided(r) ? " done" : "");
      card.id = "card-" + r.id;
      var aiLabel = { verified: "AI：原文支持", needs_fix: "AI：建议修改", reject: "AI：建议删除" }[r.ai_check] || "AI：未标注";
      var suggestUrl = s.url != null ? s.url : (r.suggested_source_url || "");
      var suggestFact = s.fact != null ? s.fact : (r.suggested_fact || "");
      card.innerHTML =
        '<div class="card-head">' +
          '<span class="idx">#' + (i + 1) + ' / ' + rows.length + ' · ' + esc(r.id) + '</span>' +
          '<span class="tag">' + esc(r.company) + '</span>' +
          '<span class="tag">' + esc(r.section) + '</span>' +
          '<span class="tag ' + esc(r.ai_check) + '">' + esc(aiLabel) + '</span>' +
          (decided(r) ? '<span class="saved">已选：' + esc({accept:"采纳原样",fix:"按建议修正",reject:"驳回"}[s.decision]) + '</span>' : '') +
        '</div>' +
        '<p class="fact">' + esc(r.candidate_fact) + '</p>' +
        '<dl class="kv">' +
          '<dt>原出处</dt><dd><a href="' + esc(r.source_url) + '" target="_blank" rel="noopener noreferrer">' + esc(r.source_title || r.source_url) + '</a></dd>' +
          '<dt>链接状态</dt><dd>' + (r.source_accessible ? '可访问' : '打不开') + ' · 引文比对：' + esc(r.excerpt_match) + '</dd>' +
          (r.check_hint ? '<dt>核对提示</dt><dd>' + esc(r.check_hint) + '</dd>' : '') +
        '</dl>' +
        (r.evidence_quote ? '<blockquote>' + esc(r.evidence_quote) + '</blockquote>' : '') +
        (r.note ? '<div class="note"><b>AI 备注：</b>' + esc(r.note) + (r.suggested_action ? '<br><b>建议：</b>' + esc(r.suggested_action) : '') + '</div>' : '') +
        '<div class="edit">' +
          '<div><label>修正后的事实（选「按建议修正」时生效，可直接改）</label><textarea data-f="fact" data-id="' + esc(r.id) + '">' + esc(suggestFact) + '</textarea></div>' +
          '<div><label>修正后的出处 URL（同上）</label><input type="text" data-f="url" data-id="' + esc(r.id) + '" value="' + esc(suggestUrl) + '"></div>' +
          '<div><label>给我/给自己的备注（可空）</label><input type="text" data-f="note" data-id="' + esc(r.id) + '" value="' + esc(s.note || "") + '" placeholder="例如：保留 2007 起源口径"></div>' +
        '</div>' +
        '<div class="decisions">' +
          '<button data-d="accept" data-id="' + esc(r.id) + '" class="' + (s.decision === "accept" ? "sel-accept" : "") + '">采纳原样</button>' +
          '<button data-d="fix" data-id="' + esc(r.id) + '" class="' + (s.decision === "fix" ? "sel-fix" : "") + '">按建议修正</button>' +
          '<button data-d="reject" data-id="' + esc(r.id) + '" class="' + (s.decision === "reject" ? "sel-reject" : "") + '">驳回</button>' +
        '</div>';
      host.appendChild(card);
    });
  }

  function progress() {
    var n = count();
    document.getElementById("bar").style.width = (n / rows.length * 100) + "%";
    document.getElementById("stat").textContent = "已完成 " + n + " / " + rows.length + " 条";
    var warn = document.getElementById("warn");
    var conflicts = risky.filter(function (r) {
      return state[r.id] && state[r.id].decision === "accept";
    });
    var broken = conflicts.filter(function (r) { return !r.source_accessible; });
    if (conflicts.length) {
      warn.classList.add("show");
      warn.innerHTML = "<b>注意：有 " + conflicts.length + " 条选了「采纳原样」，但 AI 核对标的是需修改 / 建议删除" +
        (broken.length ? "（其中 " + broken.length + " 条原始链接打不开）" : "") +
        "。</b> 直接导出会把这些已知问题写进标准答案，测出来的准确率没有意义。点「只看需处理」逐条改，或确认你已自行核实过。";
    } else {
      warn.classList.remove("show");
    }
    var btn = document.getElementById("export");
    btn.disabled = n !== rows.length;
    btn.textContent = n === rows.length ? "导出 jsonl" : "导出 jsonl（还剩 " + (rows.length - n) + " 条）";
  }

  function refresh() { render(); progress(); }

  function exportLines() {
    var asIs = 0, withFix = 0, rejected = 0, conflicts = 0;
    rows.forEach(function (r) {
      var d = state[r.id] && state[r.id].decision;
      if (d === "reject") rejected++;
      else if (d === "fix") withFix++;
      else asIs++;
      if (d === "accept" && r.ai_check !== "verified") conflicts++;
    });
    var accepted = asIs + withFix;
    var meta = {
      kind: "meta", schema_version: 1,
      generated_at: new Date().toISOString().slice(0, 10),
      review_type: "human_confirmed_by_user",
      is_human_verification: true,
      human_reviewed_claims: rows.length,
      accepted_claims: accepted,
      accepted_as_is_claims: asIs,
      accepted_with_fix_claims: withFix,
      rejected_claims: rejected,
      accepted_but_conflicts_with_ai_check: conflicts,
      source: "user decisions collected in evals/golden_review.html (local browser, no API calls)",
      tavily_credits_used: 0, llm_calls_used: 0,
      what_this_is: "用户在本地页面逐条点选的复核结论，含采纳/修正/驳回与自定义备注",
      what_this_is_not: "不是 evals/golden_live.jsonl，也不是准确率指标；正式 golden 与语义 judge 尚未生成",
      must_not_be_used_as_metric: true,
      ai_check_is_not_human_verdict: true
    };
    var lines = [JSON.stringify(meta)];
    rows.forEach(function (r) {
      var s = state[r.id] || {};
      var decision = s.decision || "accept";
      var verdict = decision !== "reject";
      var line = {
        kind: "claim", id: r.id, case: r.case, section: r.section,
        candidate_fact: r.candidate_fact,
        original_source_url: r.source_url,
        ai_check: r.ai_check,
        ai_note: r.note,
        user_verdict: verdict,
        user_decision: decision,
        user_note: s.note || "",
        final_fact: decision === "fix" ? (s.fact != null ? s.fact : r.suggested_fact) : (verdict ? r.candidate_fact : null),
        final_source_url: decision === "fix" ? (s.url != null ? s.url : r.suggested_source_url) : (verdict ? r.source_url : null)
      };
      lines.push(JSON.stringify(line));
    });
    return lines.join("\n") + "\n";
  }

  document.getElementById("cards").addEventListener("click", function (e) {
    var b = e.target.closest("button[data-d]");
    if (!b) return;
    var id = b.getAttribute("data-id");
    state[id] = state[id] || {};
    state[id].decision = b.getAttribute("data-d");
    save();
    var box = document.getElementById("card-" + id);
    ["fact", "url", "note"].forEach(function (f) {
      var el = box.querySelector('[data-f="' + f + '"]');
      if (el) state[id][f] = el.value;
    });
    save();
    refresh();
  });

  document.getElementById("cards").addEventListener("input", function (e) {
    var el = e.target;
    if (!el.getAttribute || !el.getAttribute("data-f")) return;
    var id = el.getAttribute("data-id");
    state[id] = state[id] || {};
    state[id][el.getAttribute("data-f")] = el.value;
    save();
  });

  function setFilter(mode) {
    onlyPending = mode === "pending";
    onlyRisky = mode === "risky";
    var f = document.getElementById("filter");
    var fr = document.getElementById("filterRisky");
    f.classList.toggle("on", onlyPending);
    f.textContent = onlyPending ? "显示全部" : "只看未决";
    fr.classList.toggle("on", onlyRisky);
    fr.textContent = onlyRisky ? "显示全部" : "只看需处理（" + risky.length + "）";
    render();
  }

  document.getElementById("filter").addEventListener("click", function () {
    setFilter(onlyPending ? "all" : "pending");
  });
  document.getElementById("filterRisky").addEventListener("click", function () {
    setFilter(onlyRisky ? "all" : "risky");
  });

  document.getElementById("jump").addEventListener("click", function () {
    var next = rows.filter(function (r) { return !decided(r); })[0];
    if (!next) { document.getElementById("msg").textContent = "全部填完了"; return; }
    if (onlyPending || onlyRisky) setFilter("all");
    var el = document.getElementById("card-" + next.id);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  document.getElementById("export").addEventListener("click", function () {
    if (count() !== rows.length) return;
    var blob = new Blob([exportLines()], { type: "application/x-ndjson;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "golden_live_review_filled.jsonl";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
    document.getElementById("msg").textContent = "已下载，放到 evals/ 后告诉我";
  });

  document.getElementById("copy").addEventListener("click", function () {
    var text = exportLines();
    var self = this;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        document.getElementById("msg").textContent = "已复制，直接贴给 AI 即可";
      }, function () { self.textContent = "复制失败，请用导出"; });
    } else {
      document.getElementById("msg").textContent = "此浏览器不支持复制，请用导出";
    }
  });

  document.getElementById("filterRisky").textContent = "只看需处理（" + risky.length + "）";
  refresh();
})();
</script>
</body>
</html>
"""


def main() -> Path:
    rows = build_rows()
    unknown = set(PRESETS) - {r["id"] for r in rows}
    if unknown:
        raise ValueError(f"PRESETS 里有不存在的 id: {sorted(unknown)}")
    seed = json.dumps(rows, ensure_ascii=False).replace("<", "\\u003c")
    presets = json.dumps(PRESETS, ensure_ascii=False).replace("<", "\\u003c")
    page = HTML.replace("__SEED_JSON__", seed).replace("__PRESETS_JSON__", presets)
    OUTPUT.write_text(page, encoding="utf-8")
    return OUTPUT


if __name__ == "__main__":
    out = main()
    print(f"wrote {out} ({out.stat().st_size} bytes, 25 claims, 0 network, 0 credits)")
