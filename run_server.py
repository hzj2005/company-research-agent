"""统一启动入口。

    uv run python run_server.py              # 按 .env 启动（默认 live：真实检索 + 真实模型）
    uv run python run_server.py --fixture    # 临时演示模式（本地语料，0 调用，搜别的公司会被拒答）
    uv run python run_server.py --reload     # 开发热重载
    uv run python run_server.py --port 8010  # 换端口

为什么不直接 `uvicorn application:app`：

1. **Windows 事件循环**：psycopg 的异步模式不支持默认的 ProactorEventLoop，
   uvicorn 自己指定 loop factory、改全局策略对它无效，必须显式传 `--loop`。
2. **密钥不进仓库**：模型 key 存在系统用户变量 `SYSTEM_ALIYUN_APIKEY` 里，
   这里在进程内映射成 `DASHSCOPE_API_KEY`，既不写进 .env，也不进 git。

演示模式和真实模式的区别只有环境变量，代码是同一份 —— 所以两种都从这里启动。
"""

from __future__ import annotations

import argparse
import os

from persistence.pg_compat import ensure_selector_policy


def main() -> int:
    parser = argparse.ArgumentParser(description="启动 Company Research API")
    parser.add_argument("--fixture", action="store_true", help="演示模式：本地语料，0 外部调用")
    parser.add_argument("--reload", action="store_true", help="开发热重载")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    print(f"[启动] 事件循环：{ensure_selector_policy()}")

    # 系统变量名 → 项目约定名。不落盘、不打印值。
    if not os.getenv("DASHSCOPE_API_KEY") and os.getenv("SYSTEM_ALIYUN_APIKEY"):
        os.environ["DASHSCOPE_API_KEY"] = os.environ["SYSTEM_ALIYUN_APIKEY"]
        print("[启动] 已从 SYSTEM_ALIYUN_APIKEY 映射 DASHSCOPE_API_KEY（仅本进程）")

    if args.fixture:
        os.environ["APP_MODE"] = "fixture"
        os.environ["TAVILY_LIVE_ENABLED"] = "false"
        print("[启动] 演示模式：任何外部公司都会被拒答，只有内置示例公司有语料")
    else:
        os.environ.setdefault("APP_MODE", "live")

    import uvicorn

    uvicorn.run(
        "application:app",
        host=args.host,
        port=args.port,
        loop="persistence.pg_compat:selector_loop",
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
