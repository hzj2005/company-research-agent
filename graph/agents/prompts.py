"""R3：栏目 prompt 构建器。

每个栏目有自己的 prompts.py（四件套之一），定义该栏目的专属补充要求。
最终 system prompt = 通用抽取规则（capabilities.structured.BASE_SYSTEM_PROMPT）
                  + 本栏目补充。
这样既满足"每栏目自己的说明书"，又不丢失通用规则（不编造/标出处/中文），
也不破坏 fixture stub（stub 只解析 human 消息里的 <documents>）。
"""

from __future__ import annotations

from capabilities.structured import BASE_SYSTEM_PROMPT


def build_section_prompt(addendum: str) -> str:
    """通用规则 + 栏目专属补充。"""
    return f"{BASE_SYSTEM_PROMPT}\n\n--- 本栏目专属要求 ---\n{addendum.strip()}\n"
