# 真实调研 vs 演示语料：同一家公司的输出对比

> 下面这份是 **2026-11-15 真实跑出来**的报告（Tavily 检索 + qwen-plus 抽取），
> 原样导出、未做任何润色，来源：`evals/live_batch.json`。
>
> 界面上你现在看到的 8 条，是 `APP_MODE=fixture` 下的**预置语料**（来源域名 `example.org`、
> 每条都标「（合成）」），它只为回归测试存在，不代表系统能力。

| | 演示语料（fixture） | 真实调研（live） |
|---|---|---|
| 字数 | 822 | 3971 |
| 引用条数 | 8（全是 example.org 假域名） | 11（真实网页） |
| Company 栏事实 | 2 条 | 8 条 |

---

# Notion Research Report

## Company Overview

- Notion was founded in 2013. [4]
- Notion is a privately held, venture capital-backed company. [4]
- Notion's founders include Ivan Zhao, Simon Last, and Akshay Kothari. [9]
- Notion Labs, Inc. was founded in San Francisco, California. [11]
- Notion's platform is an all-in-one workspace for writing, planning, collaborating, and organizing workflow. [4]
- Notion had 1,200 employees as of the latest data in the PitchBook profile. [4]
- Notion was formerly known as Canopy Technologies. [4]
- Notion's website is www.notion.com. [4]

## Industry Overview

- Notion operates in the collaborative workspace and productivity software industry, competing with companies like Microsoft, Atlassian, Airtable, Slack, ClickUp, monday.com, Asana, Coda, Obsidian, and Roam Research. [1]
- Notion views its competitors broadly — not as single-point solutions but as parts of a fragmented landscape it aims to unify, stating 'Our competitor is the entire industry.' [2]
- Microsoft launched Loop in November 2021 as a direct competitor to Notion, integrated into Microsoft 365. [3]
- Legacy note-taking tools like Evernote have declined (e.g., acquired for a fraction of former valuation by 2022), creating space for Notion’s rise amid shifting user expectations for integration and continuous improvement. [2]
- Enterprise incumbents such as Microsoft and Atlassian pose key competitive risks to Notion due to their existing distribution, embedded workflows, and offensive product launches like Microsoft Loop. [3]

## Financial Overview

- Notion reached a $2 billion valuation in 2020. [8]
- Notion raised $275 million in funding at a $10 billion valuation. [6]

## News

- Notion Labs, Inc. entered into a strategic collaboration with Keio University on February 25, 2026, to support Keio’s vision of becoming a 'Top Global AI-Native University' through integration of Notion AI tools for faculty and staff. [5]
- Notion AI integrated with ZoomInfo via GTM.AI’s Model Context Protocol (MCP) to enable go-to-market teams to query account and buying committee data directly in Notion AI chat. [7]
- Sia Partners acquired Notion Consulting — a US-based organizational change consulting firm founded in 2015 — to expand its Change Management & Organization capabilities in the US East region. [10]

## References

[1] Notion Competitors: Complete List & Market Landscape — https://www.distillintelligence.com/competitors/notion
[2] Notion: From Near Collapse to a $10B All‑In‑One Workspace Unicorn | by Xiayi Sun | Medium — https://medium.com/@sherrysun/notion-from-near-collapse-to-a-10b-all-in-one-workspace-unicorn-6113f7e1dc4c
[3] Report: Notion Business Breakdown & Founding Story | Contrary Research — https://research.contrary.com/report/notion
[4] Notion 2026 Company Profile: Valuation, Funding & Investors | PitchBook — https://pitchbook.com/profiles/company/168506-47
[5] Keio and Notion Launch Strategic Collaboration to Realize a Top Global AI-Native University | Keio University — https://www.keio.ac.jp/en/news/20260227-172922
[6] Notion Reaches $10 Billion Valuation, Boosted By Remote Work — https://www.forbes.com/sites/alexkonrad/2021/10/08/notion-raises-at-10-billion-valuation-boosted-by-remote-work-tiktok
[7] ZoomInfo Launches MCP Integration With Notion Through GTM.AI — https://www.businesswire.com/news/home/20261103978960/en/ZoomInfo-Launches-MCP-Integration-With-Notion-Through-GTM.AI
[8] Buzzy Work App Notion Hits $2 Billion Valuation In New Raise — https://www.forbes.com/sites/davidjeans/2020/04/01/buzzy-work-app-notion-hits-2-billion-valuation
[9] Notion | First Round — https://www.firstround.com/companies/notion
[10] Sia Partners buys organizational change expert Notion Consulting — https://www.consulting.us/news/10182/sia-partners-buys-organizational-change-expert-notion-consulting
[11] Notion (productivity software) - Wikipedia — https://en.wikipedia.org/wiki/Notion_(productivity_software)
