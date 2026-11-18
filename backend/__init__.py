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
    # 用真正的解析器判断，不要自己数变量名：dashscope 的 key 可以从
    # DASHSCOPE_API_KEY 或 SYSTEM_ALIYUN_APIKEY 任一个来（config/loader.py:182），
    # 写死变量名会在只有后者的机器上误报「缺 key」。
    from config.loader import MissingLLMCredentials, resolve_llm_credentials

    try:
        resolve_llm_credentials()
    except MissingLLMCredentials:
        logger.warning(
            "live 模式未解析到模型凭据：需要 OPENROUTER_API_KEY / "
            "DASHSCOPE_API_KEY（或 SYSTEM_ALIYUN_APIKEY）/ OPENAI_API_KEY 之一"
            "（只放系统环境变量，不要写进 .env 或提交）",
        )
    except Exception as exc:  # noqa: BLE001 —— 非「缺 key」的异常要说出来，不静默
        logger.warning("解析模型凭据时出错（%s: %s），live 调用可能失败", type(exc).__name__, exc)
    if not os.getenv("TAVILY_API_KEY"):
        logger.warning("TAVILY_API_KEY 未设置：live 真实检索不可用（fixture 模式不需要）")

__all__ = ["Graph"]
