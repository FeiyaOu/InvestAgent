# -*- coding: utf-8 -*-
"""
LangFuse 追踪集成

提供 LangFuse CallbackHandler 工厂函数。
将 handler 传入 agent.stream() 的 config["callbacks"]，
LangFuse 自动追踪所有 LangChain/LangGraph LLM 调用：
  - 每个节点的 LLM 调用延迟
  - Token 消耗（输入/输出）
  - 每个阶段的 prompt 和 response

使用方式：
    from src.evaluation.langfuse_tracing import get_langfuse_handler

    handler = get_langfuse_handler()
    config = {"configurable": {"thread_id": "abc"}}
    if handler:
        config["callbacks"] = [handler]
    agent.stream(state, config=config)
"""

from __future__ import annotations

import os
from typing import Any


def get_langfuse_handler() -> Any | None:
    """
    创建并返回 LangFuse CallbackHandler。
    若未配置环境变量，返回 None（不影响 Agent 正常运行）。
    """
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")

    if not public_key or not secret_key:
        return None

    try:
        # langfuse v4: from langfuse.langchain import CallbackHandler
        # reads LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST from env
        try:
            from langfuse.langchain import CallbackHandler
        except ImportError:
            from langfuse.callback import CallbackHandler  # type: ignore  # v3

        # v4: keys read from env (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY)
        # v3: pass explicitly; try both
        try:
            handler = CallbackHandler()
        except TypeError:
            handler = CallbackHandler(
                public_key=public_key,
                secret_key=secret_key,
                host=os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
            )
        return handler
    except ImportError:
        print("[LangFuse] langfuse 未安装，跳过追踪。安装命令: pip install langfuse")
        return None
    except Exception as e:
        print(f"[LangFuse] 初始化失败: {e}")
        return None
