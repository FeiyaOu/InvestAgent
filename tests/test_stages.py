# -*- coding: utf-8 -*-
"""
Stage 函数单元测试

测试策略：
- 不调用真实 LLM（mock _create_chain()）
- 重点测试：prerequisite 检查、state 字段更新、错误处理
- validator 节点测试 C1–C7 校验触发和重试逻辑
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.stages.decision import decision
from src.stages.modeling import modeling
from src.stages.perception import perception
from src.stages.reasoning import reasoning
from src.stages.reporter import report_generation
from src.stages.validator import validator
from tests.conftest import make_valid_report


# ---- 测试用初始状态工厂 ----

def make_base_state(**overrides) -> dict:
    base = {
        "user_query": "请分析新能源行业投资机会",
        "research_topic": "新能源行业",
        "industry_focus": "光伏",
        "time_horizon": "中期",
        "processing_mode": "deliberative",
        "messages": [],
        "perception_data": None,
        "world_model": None,
        "reasoning_plans": None,
        "selected_plan": None,
        "final_report": None,
        "validation_errors": None,
        "retry_count": 0,
        "current_phase": "perception",
        "error": None,
        "final_response": None,
        "query_type": None,
    }
    base.update(overrides)
    return base


def make_mock_chain(return_value: dict) -> MagicMock:
    """创建一个 mock chain，invoke() 返回指定值"""
    mock_chain = MagicMock()
    mock_chain.invoke.return_value = return_value
    return mock_chain


# ============================================================
# 感知阶段（Perception）
# ============================================================

class TestPerception:

    def test_missing_api_key_triggers_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """没有 API key 时感知阶段应返回 error 字段"""
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.setenv("USE_REAL_DATA", "false")

        with patch("src.stages.perception._create_chain") as mock_factory:
            mock_factory.return_value = MagicMock(
                invoke=MagicMock(side_effect=Exception("API key missing"))
            )
            state = make_base_state()
            result = perception(state)

        assert "error" in result
        assert result["current_phase"] == "perception"

    def test_success_updates_perception_data(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """成功时应更新 perception_data 并设置 current_phase=modeling"""
        monkeypatch.setenv("USE_REAL_DATA", "false")
        mock_output = {
            "market_overview": "市场整体" * 20,
            "key_indicators": {"PMI": "50.3"},
            "recent_news": ["新闻1", "新闻2", "新闻3"],
            "industry_trends": {"光伏": "上行", "风电": "平稳", "储能": "高增"},
        }
        with patch("src.stages.perception._create_chain") as mock_factory:
            mock_factory.return_value = make_mock_chain(mock_output)
            state = make_base_state()
            result = perception(state)

        assert result["perception_data"] == mock_output
        assert result["current_phase"] == "modeling"
        assert result.get("error") is None

    def test_returns_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """节点函数必须返回 dict"""
        monkeypatch.setenv("USE_REAL_DATA", "false")
        with patch("src.stages.perception._create_chain") as mock_factory:
            mock_factory.return_value = make_mock_chain({})
            result = perception(make_base_state())
        assert isinstance(result, dict)


# ============================================================
# 建模阶段（Modeling）
# ============================================================

class TestModeling:

    def test_missing_perception_data_returns_error(self) -> None:
        """缺少 perception_data 时应路由回 perception"""
        state = make_base_state(perception_data=None)
        result = modeling(state)
        assert "error" in result
        assert result["current_phase"] == "perception"

    def test_success_updates_world_model(self) -> None:
        """成功时应更新 world_model 并设置 current_phase=reasoning"""
        mock_output = {
            "market_state": "震荡上行",
            "economic_cycle": "扩张期",
            "risk_factors": ["风险1", "风险2", "风险3"],
            "opportunity_areas": ["机会1", "机会2", "机会3"],
            "market_sentiment": "中性偏乐观",
        }
        with patch("src.stages.modeling._create_chain") as mock_factory:
            mock_factory.return_value = make_mock_chain(mock_output)
            state = make_base_state(perception_data={"market_overview": "test"})
            result = modeling(state)

        assert result["world_model"] == mock_output
        assert result["current_phase"] == "reasoning"
        assert result.get("error") is None

    def test_llm_exception_returns_error(self) -> None:
        """LLM 异常时应返回 error 并保持在 modeling 阶段"""
        with patch("src.stages.modeling._create_chain") as mock_factory:
            mock_factory.return_value = MagicMock(
                invoke=MagicMock(side_effect=RuntimeError("LLM error"))
            )
            state = make_base_state(perception_data={"x": "y"})
            result = modeling(state)

        assert "error" in result
        assert result["current_phase"] == "modeling"


# ============================================================
# 推理阶段（Reasoning）
# ============================================================

class TestReasoning:

    def test_missing_world_model_returns_error(self) -> None:
        """缺少 world_model 时应路由回 modeling"""
        state = make_base_state(world_model=None)
        result = reasoning(state)
        assert "error" in result
        assert result["current_phase"] == "modeling"

    def test_success_updates_reasoning_plans_as_list(self) -> None:
        """成功时 reasoning_plans 应是 list"""
        mock_plans = [
            {"plan_id": "plan_A", "hypothesis": "假设A", "confidence_level": 0.8, "pros": [], "cons": []},
            {"plan_id": "plan_B", "hypothesis": "假设B", "confidence_level": 0.6, "pros": [], "cons": []},
            {"plan_id": "plan_C", "hypothesis": "假设C", "confidence_level": 0.7, "pros": [], "cons": []},
        ]
        with patch("src.stages.reasoning._create_chain") as mock_factory:
            mock_factory.return_value = make_mock_chain(mock_plans)
            state = make_base_state(world_model={"market_state": "test"})
            result = reasoning(state)

        assert isinstance(result["reasoning_plans"], list)
        assert result["current_phase"] == "decision"

    def test_llm_exception_returns_error(self) -> None:
        """LLM 异常时应返回 error"""
        with patch("src.stages.reasoning._create_chain") as mock_factory:
            mock_factory.return_value = MagicMock(
                invoke=MagicMock(side_effect=Exception("LLM error"))
            )
            result = reasoning(make_base_state(world_model={"x": "y"}))

        assert "error" in result
        assert result["current_phase"] == "reasoning"


# ============================================================
# 决策阶段（Decision）
# ============================================================

class TestDecision:

    def test_missing_reasoning_plans_returns_error(self) -> None:
        """缺少 reasoning_plans 时应路由回 reasoning"""
        state = make_base_state(reasoning_plans=None)
        result = decision(state)
        assert "error" in result
        assert result["current_phase"] == "reasoning"

    def test_success_updates_selected_plan(self) -> None:
        """成功时应更新 selected_plan 并设置 current_phase=report"""
        mock_output = {
            "selected_plan_id": "plan_A",
            "investment_thesis": "经过综合评估，新能源光伏行业在政策支持和需求增长双重驱动下，具备中期投资价值",
            "supporting_evidence": ["政策支持", "需求增长", "成本下降"],
            "risk_assessment": "政策风险可控",
            "recommendation": "建议超配",
            "timeframe": "6个月",
        }
        with patch("src.stages.decision._create_chain") as mock_factory:
            mock_factory.return_value = make_mock_chain(mock_output)
            state = make_base_state(
                world_model={"market_state": "test"},
                reasoning_plans=[{"plan_id": "plan_A"}],
            )
            result = decision(state)

        assert result["selected_plan"] == mock_output
        assert result["current_phase"] == "report"

    def test_llm_exception_returns_error(self) -> None:
        """LLM 异常时应返回 error"""
        with patch("src.stages.decision._create_chain") as mock_factory:
            mock_factory.return_value = MagicMock(
                invoke=MagicMock(side_effect=Exception("LLM error"))
            )
            result = decision(make_base_state(reasoning_plans=[{"plan_id": "A"}]))

        assert "error" in result
        assert result["current_phase"] == "decision"


# ============================================================
# 报告生成阶段（Report Generation）
# ============================================================

class TestReportGeneration:

    def test_missing_selected_plan_returns_error(self) -> None:
        """缺少 selected_plan 时应路由回 decision"""
        state = make_base_state(selected_plan=None)
        result = report_generation(state)
        assert "error" in result
        assert result["current_phase"] == "decision"

    def test_success_returns_json_string(self) -> None:
        """成功时 final_report 应是合法 JSON 字符串"""
        mock_report = make_valid_report()
        with patch("src.stages.reporter._create_report_chain") as mock_factory:
            mock_factory.return_value = make_mock_chain(mock_report)
            state = make_base_state(
                selected_plan={"investment_thesis": "test thesis for report generation"}
            )
            result = report_generation(state)

        assert "final_report" in result
        assert isinstance(result["final_report"], str)
        parsed = json.loads(result["final_report"])
        assert "dimensions" in parsed
        assert result["current_phase"] == "validator"

    def test_llm_exception_returns_error(self) -> None:
        """LLM 异常时应返回 error"""
        with patch("src.stages.reporter._create_report_chain") as mock_factory:
            mock_factory.return_value = MagicMock(
                invoke=MagicMock(side_effect=Exception("LLM error"))
            )
            result = report_generation(make_base_state(selected_plan={"thesis": "x"}))

        assert "error" in result
        assert result["current_phase"] == "report"


# ============================================================
# 校验节点（Validator）
# ============================================================

class TestValidator:

    def test_valid_report_passes(self) -> None:
        """合规报告应通过校验，current_phase=completed"""
        valid = make_valid_report()
        state = make_base_state(
            final_report=json.dumps(valid, ensure_ascii=False),
            retry_count=0,
        )
        result = validator(state)
        assert result["validation_errors"] == []
        assert result["current_phase"] == "completed"

    def test_invalid_report_triggers_retry(self) -> None:
        """不合规报告应触发重试，路由回 decision"""
        bad_report = {"research_topic": "test", "overall_rating": "bad_value"}
        state = make_base_state(
            final_report=json.dumps(bad_report),
            retry_count=0,
        )
        result = validator(state)
        assert len(result["validation_errors"]) > 0
        assert result["retry_count"] == 1
        assert result["current_phase"] == "decision"

    def test_max_retries_forces_completion(self) -> None:
        """达到最大重试次数后应强制完成，不再循环"""
        from src.state import MAX_VALIDATOR_RETRIES
        bad_report = {"research_topic": "test"}
        state = make_base_state(
            final_report=json.dumps(bad_report),
            retry_count=MAX_VALIDATOR_RETRIES,
        )
        result = validator(state)
        assert result["current_phase"] == "completed"   # 不再是 decision

    def test_empty_report_triggers_retry(self) -> None:
        """空报告应触发重试"""
        state = make_base_state(final_report="", retry_count=0)
        result = validator(state)
        assert result["retry_count"] == 1

    def test_invalid_json_triggers_retry(self) -> None:
        """非法 JSON 应触发重试"""
        state = make_base_state(final_report="not json at all {{", retry_count=0)
        result = validator(state)
        assert result["retry_count"] == 1
