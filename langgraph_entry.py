"""LangGraph Studio / Server 入口（S5-B 起指向二次开发的新图）。

原版 `backend/graph.py` 的 `Graph().compile()` 是 12 节点线性 DAG，保留为 upstream
对照；这里导出 `graph/` 下的 7 节点主图（research 内部是 4 路 Send 并行子图）。

**为什么顶层 compile() 不带 checkpointer**（AGENT.md 6.7 的例外）：
`AsyncSqliteSaver.from_conn_string()` 是 async context manager，模块顶层无法 await；
LangGraph Server 会为导出的图注入自己的 saver。CLI / FastAPI 路径则统一走
`persistence.CheckpointSession.compile()`，仍然带真实持久化。

**简报后端是模块级单例**：Server 导入一次、随进程存活，所以不走
`briefing_backend_scope()`（scope 会在每次图运行结束时 aclose，单例被提前关闭就废了）。
CLI 与 `/research` 是短生命周期运行，才用 scope 管理并逐个关闭 client。

默认 `APP_MODE=fixture`：本模块导入与图编译 0 次外部调用、0 次 Tavily / 模型请求。
要启用 live 需显式三重 opt-in（见 config/settings.yaml 的 retrieval.live）。
注意：`APP_MODE=live` 且未配置模型 key 时，`make_briefing_backend()` 会在**导入阶段**
抛 `MissingLLMCredentials`；只放行真实检索时请同时设 `FEATURES_STRUCTURED_OUTPUT=false`。
"""

from capabilities.briefing import make_briefing_backend
from capabilities.retrieval import make_document_tool
from config.loader import get_settings
from graph.builder import build_graph

_settings = get_settings()

# importlib.reload() 会复用模块 __dict__，因此 reload 时沿用同一个 backend，
# 不重复创建 httpx.AsyncClient（Studio 与测试都会 reload 这个模块）。
try:
    _briefing_backend
except NameError:
    _briefing_backend = (
        make_briefing_backend(_settings) if _settings.features.structured_output else None
    )

graph = build_graph(
    _settings,
    make_document_tool(_settings),
    briefing_backend=_briefing_backend,
).compile()
