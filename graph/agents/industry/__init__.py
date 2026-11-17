"""Industry 栏目 Agent 占位包（V2 S5 后处理层方案）。

本目录当前**没有独立实现**——行业栏目的差异化能力（竞品识别、框架归类、
事实对比矩阵）实现在 `capabilities/postprocess.py::industry_postprocess`，
由报告节点在 structured output 之后按 `features.postprocess` 开关调用。

保留此包是为了与 PROJECT_PLAN_V2.md 的目录结构（4 个 Agent 各一包）对齐，
不代表这里存在独立的 graph/state/prompts。若未来走"抽取链下沉"方案，
再把后处理逻辑搬进来并实现完整四件套。
"""
