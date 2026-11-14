# -*- coding: utf-8 -*-
"""
LLM 工厂 — 模型名与重试策略的单一真源

- 所有 ChatTongyi 实例都通过 create_llm() 创建，换模型只改本文件
- qwen-turbo 在当前账号下被 DashScope 限流（429 Throttling.RateQuota），改用 qwen-flash
- ChatTongyi 默认 max_retries=10，遇到 429 会反复退避重试，UI 卡很久才报错；这里调低以快速失败
"""

from __future__ import annotations

import os
from typing import Any

from langchain_community.chat_models import ChatTongyi

FAST_MODEL = "qwen-flash"   # 评估 / 反应式 / 感知 / 建模 / 推理
STRONG_MODEL = "qwen-max"   # 决策 / 报告生成
LLM_MAX_RETRIES = 2


def create_llm(model: str = FAST_MODEL, **kwargs: Any) -> ChatTongyi:
    """创建 ChatTongyi 实例（统一 API key 读取和重试次数）"""
    kwargs.setdefault("dashscope_api_key", os.getenv("DASHSCOPE_API_KEY"))
    kwargs.setdefault("max_retries", LLM_MAX_RETRIES)
    return ChatTongyi(model_name=model, **kwargs)
