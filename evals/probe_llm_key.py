"""一次性探针：确认 SYSTEM_ALIYUN_APIKEY 的真实 provider 与可用性。

用途（重建规划前置）：用户决定"用 key 实跑"，但 key 变量名与项目期待的不一致，
且前缀特征不像标准 DashScope。本探针用最小请求（max_tokens=1）测试候选 endpoint，
只报告"哪家能通"，不打印 key，不做任何业务抽取。

**这不是项目代码，是规划前的验证脚本**。运行一次即可，之后删除或保留作诊断工具。
"""

from __future__ import annotations

import os

import httpx

KEY = os.environ.get("SYSTEM_ALIYUN_APIKEY", "")
if not KEY:
    raise SystemExit("SYSTEM_ALIYUN_APIKEY 未设置")

# 候选：DashScope OpenAI 兼容 / OpenRouter / 标准 OpenAI
CANDIDATES = [
    ("dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "qwen-plus"),
    ("openrouter", "https://openrouter.ai/api/v1/chat/completions", "google/gemini-3.8-flash"),
]

for name, url, model in CANDIDATES:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }
    headers = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
    if name == "openrouter":
        headers["HTTP-Referer"] = "http://localhost"
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=20)
        detail = ""
        if r.status_code == 200:
            detail = "OK — 可用"
        else:
            # 只截取错误类型，不回显可能含 key 的完整响应
            detail = f"HTTP {r.status_code} {r.text[:120]}"
        print(f"[{name}] {detail}")
    except Exception as exc:  # noqa: BLE001
        print(f"[{name}] 连接失败: {type(exc).__name__}")
