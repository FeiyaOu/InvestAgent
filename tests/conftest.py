# -*- coding: utf-8 -*-
"""
共享测试 fixtures

设计原则：
1. 测试环境隔离：确保单元测试不会调用真实 API
2. 报告工厂：快速构建符合/不符合 Spec 的报告字典
3. AKShare 隔离：所有单元测试默认 mock AKShare
"""

from __future__ import annotations

import pytest

from src.stages.reporter import MIN_SOURCES, MIN_SUMMARY_LENGTH, MIN_THESIS_LENGTH


# ---- 环境隔离 ----

@pytest.fixture(autouse=True)
def _isolate_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """确保单元测试不会意外调用真实 LLM API"""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)


# ---- 合规报告工厂 ----

def _build_valid_dimension(dim_name: str) -> dict:
    """构建一个满足 C2 和 C3 的单维度数据"""
    long_summary = f"这是 {dim_name} 维度的详细分析内容。" * 8  # 确保超过100字
    return {
        "summary": long_summary,
        "confidence": 0.8,
    }


def make_valid_report() -> dict:
    """构建一个满足 C1–C7 全部约束的合规报告字典"""
    long_thesis = "经过感知、建模、推理和决策四个阶段的深度分析，" * 3  # 超过50字
    return {
        "research_topic": "新能源行业",
        "industry_focus": "光伏",
        "time_horizon": "中期",
        "report_date": "2026-07-07",
        "dimensions": {
            dim: _build_valid_dimension(dim)
            for dim in ["fundamental", "market", "news", "analyst"]
        },
        "investment_thesis": long_thesis,
        "supporting_evidence": ["证据1", "证据2", "证据3"],
        "overall_rating": "buy",
        "risk_factors": ["政策风险", "市场波动风险"],
        "sources": [
            "https://finance.example.com/1",
            "https://finance.example.com/2",
            "https://finance.example.com/3",
        ],
    }


@pytest.fixture()
def valid_report() -> dict:
    """提供一个通过全部 C1–C7 校验的合规报告"""
    return make_valid_report()
