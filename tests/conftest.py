"""确保 pytest 能导入项目内包（graph / config / persistence / capabilities）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# psycopg 的异步模式在 Windows 默认 Proactor 循环下会直接拒绝连接；
# 测试进程里必须先把策略切到 Selector，否则 Postgres 相关用例必红。
from persistence.pg_compat import ensure_selector_policy  # noqa: E402

ensure_selector_policy()

# 测试一律不碰真实数据库：本机 .env 可能配了 postgres，但那是给人手动跑服务用的。
# setdefault 而不是直接赋值，方便单独盯某组 PG 用例时用环境变量覆盖。
# 依赖 application.py 里 load_dotenv(override=False) 才生效——否则 .env 会盖回来。
import os  # noqa: E402

os.environ.setdefault("JOB_STORE", "memory")
os.environ.setdefault("CHECKPOINTER", "sqlite")
# .env 现在默认是 live（真实检索 + 真实模型）。测试进程必须钉死在 fixture，
# 否则任何走 get_settings() 的用例都会去联网、要 key、烧额度。
os.environ.setdefault("APP_MODE", "fixture")
os.environ.setdefault("TAVILY_LIVE_ENABLED", "false")
os.environ.setdefault("TAVILY_MAX_CALLS", "0")


def assert_report_shape(report: str) -> None:
    """断言 fixture 报告结构完整，不依赖具体长度或事实条数。

    历史上多个测试写死 `len(report) == 772`：一旦往 fixture 加合成文档，
    报告自然会变长，断言就红了，但其实报告完全正常。结构断言保留"报告
    真的生成了、四栏目齐全、引用可用"的验证意图，又不与数据量耦合。
    """
    assert "# " in report, "缺报告主标题"
    for heading in ("公司概况", "行业概况", "财务概况", "新闻动态"):
        assert f"## {heading}" in report, f"缺栏目：{heading}"
    assert "## References" in report, "缺引用列表"
    assert "[1]" in report, "缺行内引用标记"
