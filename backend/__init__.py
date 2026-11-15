"""Backend package for tavily-company-research."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from .graph import Graph

# Set up logging
logger = logging.getLogger(__name__)

# Load environment variables from .env file
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    logger.info(f"Loading environment variables from {env_path}")
    # override=False：显式环境变量优先。原来是 True，导致测试里设的
    # JOB_STORE=memory 被 .env 的 postgres 盖回去，测试直接写进真实库。
    load_dotenv(dotenv_path=env_path, override=False)
else:
    logger.warning(f".env file not found at {env_path}. Using system environment variables.")

# 上游遗留：原来只要没设 OPENROUTER/OPENAI key 就提示「请从 UI settings 填 key」。
# 12.27 / S13 之后这句话三处都不成立：fixture 模式零 key 可跑；live 的模型凭据是
# 系统环境变量里注入的 DASHSCOPE_API_KEY（run_server.py 负责映射）；UI 早已删掉
# key 输入框和 settings 面板。离线跑一遍刷两条误导性警告，正是「要几个 key 才能用」
# 那次困惑的来源之一，所以改成只在 live 且当前 provider 确实缺凭据时提示。
if os.getenv("APP_MODE", "fixture").lower() == "live":
    provider = (os.getenv("LLM_PROVIDER") or "").lower()
    key_var = {
        "dashscope": "DASHSCOPE_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }.get(provider, "OPENAI_API_KEY")
    if not os.getenv(key_var):
        logger.warning(
            "%s 未设置：live 模式需要它（只放系统环境变量，不要写进 .env 或提交）",
            key_var,
        )
    if not os.getenv("TAVILY_API_KEY"):
        logger.warning("TAVILY_API_KEY 未设置：live 真实检索不可用（fixture 模式不需要）")

__all__ = ["Graph"]
