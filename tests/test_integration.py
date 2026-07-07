# -*- coding: utf-8 -*-
"""
集成测试 — 需要真实 DASHSCOPE_API_KEY

通过 @pytest.mark.integration 标记，默认不运行。
运行方式: pytest tests/test_integration.py -m integration -v
"""

from __future__ import annotations

import json
import os

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture()
def api_key() -> str:
    key = os.getenv("DASHSCOPE_API_KEY", "")
    if not key:
        pytest.skip("DASHSCOPE_API_KEY 未设置，跳过集成测试")
    return key


class TestReactivePathEndToEnd:

    def test_reactive_returns_nonempty_response(self, api_key: str) -> None:
        """Reactive 路径应返回非空 final_response（C9）"""
        from src.agent import run_invest_agent

        state = run_invest_agent(user_query="今天上证指数怎么样？")
        assert state.get("processing_mode") in {"reactive", "deliberative"}
        if state.get("processing_mode") == "reactive":
            assert isinstance(state.get("final_response"), str)
            assert len(state["final_response"]) > 0


class TestDeliberativePathEndToEnd:

    def test_deliberative_report_passes_validation(self, api_key: str) -> None:
        """Deliberative 路径生成的报告应通过 C1–C7 校验"""
        from src.agent import run_invest_agent
        from src.stages.reporter import validate_report

        state = run_invest_agent(
            user_query="请深度分析新能源行业的中期投资机会",
            research_topic="新能源行业",
            industry_focus="光伏",
            time_horizon="中期",
        )

        if state.get("processing_mode") != "deliberative":
            pytest.skip("LLM 将本次查询路由到了 reactive 路径，跳过 deliberative 校验")

        assert state.get("final_report"), "final_report 不能为空"

        report = json.loads(state["final_report"])
        errors = validate_report(report)
        critical = [e for e in errors if e["type"] in {
            "missing_dimension", "invalid_rating", "thesis_too_short"
        }]
        assert len(critical) == 0, f"存在关键约束违反: {critical}"

    def test_deliberative_state_has_all_stages(self, api_key: str) -> None:
        """Deliberative 路径应填充全部5个阶段的 state 字段"""
        from src.agent import run_invest_agent

        state = run_invest_agent(
            user_query="请分析光伏行业投资价值",
            research_topic="光伏行业",
            industry_focus="光伏",
            time_horizon="中期",
        )

        if state.get("processing_mode") != "deliberative":
            pytest.skip("路由到了 reactive 路径")

        assert state.get("perception_data") is not None, "perception_data 应存在"
        assert state.get("world_model") is not None, "world_model 应存在"
        assert state.get("reasoning_plans") is not None, "reasoning_plans 应存在"
        assert state.get("selected_plan") is not None, "selected_plan 应存在"
        assert state.get("final_report") is not None, "final_report 应存在"
