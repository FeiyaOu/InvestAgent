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
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _langfuse_credentials_are_valid(
    public_key: str,
    secret_key: str,
    base_url: str,
) -> bool:
    """预检 LangFuse 凭证，避免运行时每个 span 都重复输出 401。"""
    try:
        from langfuse import Langfuse
        from langfuse.api import UnauthorizedError
    except ImportError:
        return True

    client = None
    try:
        client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=base_url or None,
        )
        client.api.trace.list(limit=1)
        return True
    except UnauthorizedError:
        print(
            "[LangFuse] 认证失败：当前 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY "
            "未被 Langfuse Cloud 接受。请确认 pk/sk 来自同一个项目，或重新生成一对新密钥。"
        )
        return False
    except Exception as e:
        print(f"[LangFuse] 凭证预检跳过：{e}")
        return True
    finally:
        if client is not None:
            try:
                client.shutdown()
            except Exception:
                pass


def get_langfuse_handler() -> Any | None:
    """
    创建并返回 LangFuse CallbackHandler。
    若未配置环境变量，返回 None（不影响 Agent 正常运行）。
    """
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
    base_url = os.getenv("LANGFUSE_BASE_URL", "")
    host = os.getenv("LANGFUSE_HOST", "")

    if not public_key or not secret_key:
        return None

    if public_key.startswith("sk-lf-") and secret_key.startswith("pk-lf-"):
        print("[LangFuse] 检测到 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 写反，已自动纠正。")
        public_key, secret_key = secret_key, public_key

    if not public_key.startswith("pk-lf-") or not secret_key.startswith("sk-lf-"):
        print("[LangFuse] 凭证格式异常：PUBLIC 应以 pk-lf- 开头，SECRET 应以 sk-lf- 开头。")
        return None

    if not _langfuse_credentials_are_valid(public_key, secret_key, base_url):
        return None

    os.environ["LANGFUSE_PUBLIC_KEY"] = public_key
    os.environ["LANGFUSE_SECRET_KEY"] = secret_key
    if base_url and not host:
        os.environ["LANGFUSE_HOST"] = base_url

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
