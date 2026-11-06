# -*- coding: utf-8 -*-
"""
LLM 工厂测试

- 模型名集中在 src/llm.py，不在各 stage 中散落硬编码
- qwen-turbo 已被 DashScope 限流（429 Throttling.RateQuota），不得再使用
- 限流时快速失败，不让 ChatTongyi 默认的 10 次重试拖住 UI
"""

from __future__ import annotations

from pathlib import Path

from src import llm

_FAKE_KEY = "sk-test"  # conftest 已清除真实 key，ChatTongyi 构造时必须有 key


def test_fast_model_is_not_throttled_qwen_turbo() -> None:
    assert llm.FAST_MODEL != "qwen-turbo"


def test_create_llm_uses_given_model_and_low_retries() -> None:
    model = llm.create_llm(llm.STRONG_MODEL, dashscope_api_key=_FAKE_KEY, temperature=0)
    assert model.model_name == llm.STRONG_MODEL
    assert model.max_retries == llm.LLM_MAX_RETRIES
    assert model.max_retries <= 3


def test_create_llm_defaults_to_fast_model() -> None:
    assert llm.create_llm(dashscope_api_key=_FAKE_KEY).model_name == llm.FAST_MODEL


def test_no_hardcoded_model_names_outside_llm_module() -> None:
    src = Path(__file__).parent.parent / "src"
    offenders = [
        str(p.relative_to(src))
        for p in src.rglob("*.py")
        if p.name != "llm.py" and 'model_name="qwen' in p.read_text(encoding="utf-8")
    ]
    assert offenders == []
