"""LangGraph Studio / Server 入口（S5-B 起指向二次开发的新图）。

原版 `backend/graph.py` 的 `Graph().compile()` 是 12 节点线性 DAG，保留为 upstream
对照；这里导出 `graph/` 下的 7 节点主图（research 内部是 4 路 Send 并行子图）。

**为什么顶层 compile() 不带 checkpointer**（AGENT.md 6.7 的例外）：
`AsyncSqliteSaver.from_conn_string()` 是 async context manager，模块顶层无法 await；
LangGraph Server 会为导出的图注入自己的 saver。CLI / FastAPI 路径则统一走
`persistence.CheckpointSession.compile()`，仍然带真实持久化。

默认 `APP_MODE=fixture`：本模块导入与图编译 0 次外部调用、0 次 Tavily / 模型请求。
要启用 live 需显式三重 opt-in（见 config/settings.yaml 的 retrieval.live）。
"""

from capabilities.retrieval import make_document_tool
from config.loader import get_settings
from graph.builder import build_graph

_settings = get_settings()
graph = build_graph(_settings, make_document_tool(_settings)).compile()
