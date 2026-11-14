# 上游来源与归因声明

本项目是 **基于开源仓库二次开发**，不是独立设计。任何 README、简历、commit message 都必须保留这一声明。

| 项 | 值 |
|---|---|
| 上游仓库 | `guy-hartstein/company-research-agent` |
| 来源 URL | https://github.com/guy-hartstein/company-research-agent |
| 落地 commit | `23fe92d48ea05750e6fd7cffdb78799cea5278d8`（2026-10-26） |
| 协议 | Apache-2.0（`LICENSE`，SHA256 `92799ec7ced27736383efb08e9ca150ad527060500a751f38ba3eb874cf913cd`） |
| 落地时间 | 2026-11-14 13:02 |
| 落地方式 | 本地浅克隆快照复制，保留 `.git`；remote 已改名为 `upstream` |

## 保留与改动规则

- `LICENSE` 与所有版权声明**不得删除或改写**。
- `.git` 中保留上游 commit，后续每个改动都能 `git diff 23fe92d` 查到，用于自证「改了哪些文件」。
- 原仓库的 `.env.example` 与本项目阶段 0 的双模式配置模板同名，已另存为 `docs/upstream.env.example`；项目实际使用的是根目录 `.env.example`（fixture/live 双模式）。
- 原版已有功能（四路并行检索、Tavily 相关性筛选、PDF 导出、SSE 进度、多语言 README）**不属于本项目独立设计**。
- 本项目新增层：`graph/`、`capabilities/`、`persistence/`、`evals/`、`tests/`、`config/loader.py`、`docs/`。
- `README.md` 顶部已于 2026-11-14 补上二次开发归因声明与当前真实状态（此前漏了，违反 `AGENT.md` 第 2 条，复查时补掉）；多语言 README（`README.*.md`）仍是上游原文，未改，对外展示以主 README 为准。

## 二次开发范围

见 `docs/PROJECT_PLAN.md` 第 3 节目标架构与 `docs/BASELINE.md` 原版基线。
