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
