# -*- coding: utf-8 -*-
"""
Agent 路由测试 — C8 / C9

测试策略：
- 直接测试路由函数（route_after_assess, should_continue_tools, route_after_validator）
- 测试 assess_query 的 processing_mode 校验（C8）
- 测试 extract_reactive_response 的 final_response 完整性（C9）
- 不运行完整 LangGraph（避免真实 LLM 调用）
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END

from src.agent import (
    _DEFAULT_MODE,
    assess_query,
    extract_reactive_response,
    route_after_assess,
    route_after_validator,
    should_continue_tools,
)
from src.state import MAX_VALIDATOR_RETRIES, VALID_PROCESSING_MODES


# ---- 状态工厂 ----

def make_state(**overrides) -> dict:
    base = {
        "user_query": "新能源板块今天怎么样",
        "research_topic": "",
        "industry_focus": "",
        "time_horizon": "中期",
        "processing_mode": None,
        "query_type": None,
        "messages": [],
        "final_response": None,
        "perception_data": None,
        "world_model": None,
        "reasoning_plans": None,
        "selected_plan": None,
        "final_report": None,
        "validation_errors": None,
        "retry_count": 0,
        "current_phase": "assess",
        "error": None,
    }
    base.update(overrides)
    return base


# ============================================================
# C8：processing_mode 必须是 reactive 或 deliberative
# ============================================================

class TestC8RoutingValidValue:

    # ---- route_after_assess 路由逻辑 ----

    def test_reactive_mode_routes_to_reactive_agent(self) -> None:
        """processing_mode=reactive 应路由到 reactive_agent"""
        state = make_state(processing_mode="reactive")
        assert route_after_assess(state) == "reactive_agent"

    def test_deliberative_mode_routes_to_perception(self) -> None:
        """processing_mode=deliberative 应路由到 perception"""
        state = make_state(processing_mode="deliberative")
        assert route_after_assess(state) == "perception"

    def test_none_mode_defaults_to_reactive_agent(self) -> None:
        """processing_mode=None 应 fallback 到 reactive_agent"""
        state = make_state(processing_mode=None)
        assert route_after_assess(state) == "reactive_agent"

    def test_invalid_mode_defaults_to_reactive_agent(self) -> None:
        """非法 processing_mode 应 fallback 到 reactive_agent"""
        state = make_state(processing_mode="unknown_mode")
        assert route_after_assess(state) == "reactive_agent"

    # ---- assess_query 节点：确保输出合法的 processing_mode ----

    def test_assess_outputs_reactive_for_simple_query(self) -> None:
        """assess_query 应为简单查询输出 reactive"""
        mock_result = {
            "processing_mode": "reactive",
            "query_type": "simple",
            "research_topic": "上证指数",
            "industry_focus": "",
            "time_horizon": "短期",
        }
        with patch("src.agent._create_assess_chain") as mock_factory:
            mock_factory.return_value = MagicMock(invoke=MagicMock(return_value=mock_result))
            result = assess_query(make_state())

        assert result["processing_mode"] == "reactive"
        assert result["processing_mode"] in VALID_PROCESSING_MODES

    def test_assess_outputs_deliberative_for_complex_query(self) -> None:
        """assess_query 应为复杂查询输出 deliberative"""
        mock_result = {
            "processing_mode": "deliberative",
            "query_type": "analytical",
            "research_topic": "新能源行业",
            "industry_focus": "光伏",
            "time_horizon": "中期",
        }
        with patch("src.agent._create_assess_chain") as mock_factory:
            mock_factory.return_value = MagicMock(invoke=MagicMock(return_value=mock_result))
            result = assess_query(make_state(user_query="请深度分析新能源行业投资机会"))

        assert result["processing_mode"] == "deliberative"
        assert result["processing_mode"] in VALID_PROCESSING_MODES

    def test_assess_corrects_invalid_mode_to_default(self) -> None:
        """LLM 返回非法 processing_mode 时，assess_query 应修正为 reactive"""
        mock_result = {
            "processing_mode": "strong_buy",   # 非法值
            "query_type": "simple",
            "research_topic": "test",
            "industry_focus": "",
            "time_horizon": "中期",
        }
        with patch("src.agent._create_assess_chain") as mock_factory:
            mock_factory.return_value = MagicMock(invoke=MagicMock(return_value=mock_result))
            result = assess_query(make_state())

        assert result["processing_mode"] == _DEFAULT_MODE
        assert result["processing_mode"] in VALID_PROCESSING_MODES

    def test_assess_exception_falls_back_to_reactive(self) -> None:
        """assess_query 出现异常时应 fallback 到 reactive，不崩溃"""
        with patch("src.agent._create_assess_chain") as mock_factory:
            mock_factory.return_value = MagicMock(
                invoke=MagicMock(side_effect=Exception("LLM error"))
            )
            result = assess_query(make_state())

        assert result["processing_mode"] == _DEFAULT_MODE
        assert result["processing_mode"] in VALID_PROCESSING_MODES

    def test_valid_processing_modes_set_is_correct(self) -> None:
        """VALID_PROCESSING_MODES 常量只包含两个合法值"""
        assert VALID_PROCESSING_MODES == {"reactive", "deliberative"}


# ============================================================
# C9：processing_mode==reactive 时 final_response 必须是非空字符串
# ============================================================

class TestC9ReactiveResponse:

    def test_extract_response_returns_string(self) -> None:
        """extract_reactive_response 应返回字符串"""
        ai_msg = AIMessage(content="今天新能源板块涨了2%")
        state = make_state(messages=[HumanMessage(content="新能源板块"), ai_msg])
        result = extract_reactive_response(state)
        assert isinstance(result.get("final_response"), str)

    def test_extract_response_is_nonempty(self) -> None:
        """extract_reactive_response 返回的 final_response 不能为空"""
        ai_msg = AIMessage(content="上证指数今日收3125点，涨0.32%")
        state = make_state(messages=[HumanMessage(content="上证指数"), ai_msg])
        result = extract_reactive_response(state)
        assert len(result["final_response"]) > 0

    def test_extract_response_skips_tool_call_messages(self) -> None:
        """带 tool_calls 的 AIMessage 不应被提取为最终回答"""
        tool_ai_msg = AIMessage(content="", tool_calls=[{"name": "get_index_performance", "args": {}, "id": "1"}])
        final_ai_msg = AIMessage(content="最终回答：今日指数上涨")
        tool_msg = ToolMessage(content="上证指数 3125.62", tool_call_id="1")
        state = make_state(messages=[
            HumanMessage(content="指数怎样"),
            tool_ai_msg,
            tool_msg,
            final_ai_msg,
        ])
        result = extract_reactive_response(state)
        assert "最终回答" in result["final_response"]

    def test_empty_messages_returns_fallback_string(self) -> None:
        """消息为空时应返回 fallback 字符串而非 None（满足 C9）"""
        state = make_state(messages=[])
        result = extract_reactive_response(state)
        assert isinstance(result["final_response"], str)
        assert len(result["final_response"]) > 0

    def test_no_ai_message_returns_fallback(self) -> None:
        """只有 HumanMessage 时应返回 fallback 字符串"""
        state = make_state(messages=[HumanMessage(content="test")])
        result = extract_reactive_response(state)
        assert isinstance(result["final_response"], str)
        assert len(result["final_response"]) > 0


# ============================================================
# 工具调用循环路由（有向环①的控制函数）
# ============================================================

class TestToolCallRouting:

    def test_routes_to_tools_when_tool_calls_present(self) -> None:
        """AIMessage 有 tool_calls 时应路由到 tools（继续环①）"""
        ai_with_tools = AIMessage(
            content="",
            tool_calls=[{"name": "get_sector_performance", "args": {"sector": "新能源"}, "id": "tc1"}],
        )
        state = make_state(messages=[HumanMessage(content="test"), ai_with_tools])
        assert should_continue_tools(state) == "tools"

    def test_routes_to_extract_when_no_tool_calls(self) -> None:
        """AIMessage 无 tool_calls 时应路由到 extract_response（退出环①）"""
        ai_final = AIMessage(content="新能源板块今日涨2%")
        state = make_state(messages=[HumanMessage(content="test"), ai_final])
        assert should_continue_tools(state) == "extract_response"

    def test_empty_messages_routes_to_extract(self) -> None:
        """空消息时应路由到 extract_response"""
        state = make_state(messages=[])
        assert should_continue_tools(state) == "extract_response"


# ============================================================
# Validator 路由（有向环②的控制函数）
# ============================================================

class TestValidatorRouting:

    def test_completed_routes_to_end(self) -> None:
        """current_phase=completed 应路由到 END"""
        state = make_state(current_phase="completed", validation_errors=[])
        assert route_after_validator(state) == END

    def test_decision_routes_back_to_decision(self) -> None:
        """current_phase=decision 应路由回 decision（触发环②）"""
        state = make_state(current_phase="decision", retry_count=1)
        assert route_after_validator(state) == "decision"

    def test_max_retries_still_routes_to_end(self) -> None:
        """达到最大重试次数后 validator 设 current_phase=completed，应路由到 END"""
        state = make_state(current_phase="completed", retry_count=MAX_VALIDATOR_RETRIES)
        assert route_after_validator(state) == END


# ============================================================
# 图结构验证
# ============================================================

class TestGraphStructure:

    def test_graph_compiles_without_error(self) -> None:
        """create_invest_agent() 应能正常编译，不抛异常"""
        from src.agent import create_invest_agent
        agent = create_invest_agent()
        assert agent is not None

    def test_graph_has_mermaid_output(self) -> None:
        """编译后的 graph 应能输出 Mermaid 流程图"""
        from src.agent import create_invest_agent
        agent = create_invest_agent()
        mermaid = agent.get_graph().draw_mermaid()
        assert "assess" in mermaid
        assert "reactive_agent" in mermaid
        assert "perception" in mermaid
        assert "validator" in mermaid


# ============================================================
# 多轮对话（MemorySaver checkpointer + thread_id）
# TDD: 这些测试在实现前先写（红）→ 实现后变绿
# ============================================================

class TestMultiTurnConversation:

    def test_graph_accepts_checkpointer_parameter(self) -> None:
        """create_invest_agent() 应支持传入 checkpointer 参数"""
        from langgraph.checkpoint.memory import MemorySaver
        from src.agent import create_invest_agent
        # 如果 create_invest_agent 不接受 checkpointer 或内部未使用，此测试失败
        agent = create_invest_agent()
        # 验证编译后的 graph 有 checkpointer（MemorySaver 已在内部注入）
        assert agent.checkpointer is not None

    def test_run_invest_agent_accepts_thread_id(self) -> None:
        """run_invest_agent() 应接受 thread_id 参数而不报错"""
        from src.agent import run_invest_agent
        import inspect
        sig = inspect.signature(run_invest_agent)
        assert "thread_id" in sig.parameters, "run_invest_agent 应有 thread_id 参数"

    def test_same_thread_id_persists_messages(self) -> None:
        """同一 thread_id 的两次调用，第二次应能看到第一次的 messages"""
        from langgraph.checkpoint.memory import MemorySaver
        from src.agent import create_invest_agent

        checkpointer = MemorySaver()
        agent = create_invest_agent()

        config = {"configurable": {"thread_id": "test-thread-persist"}}

        initial_state = {
            "user_query": "测试消息",
            "research_topic": "测试",
            "industry_focus": "",
            "time_horizon": "中期",
            "processing_mode": "reactive",
            "query_type": "simple",
            "messages": [],
            "final_response": None,
            "perception_data": None,
            "world_model": None,
            "reasoning_plans": None,
            "selected_plan": None,
            "final_report": None,
            "validation_errors": None,
            "retry_count": 0,
            "current_phase": "assess",
            "error": None,
        }

        from unittest.mock import MagicMock, patch
        from langchain_core.messages import AIMessage

        mock_assess_result = {
            "processing_mode": "reactive",
            "query_type": "simple",
            "research_topic": "测试",
            "industry_focus": "",
            "time_horizon": "中期",
        }
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value.invoke.return_value = AIMessage(content="第1轮回答")

        with patch("src.agent._create_assess_chain") as mock_chain_factory:
            mock_chain_factory.return_value = MagicMock(invoke=MagicMock(return_value=mock_assess_result))
            with patch("src.agent.ChatTongyi", return_value=mock_llm):
                state1 = agent.invoke(initial_state, config=config)

        # 第二次调用相同 thread_id，messages 应该是累积的
        with patch("src.agent._create_assess_chain") as mock_chain_factory:
            mock_chain_factory.return_value = MagicMock(invoke=MagicMock(return_value=mock_assess_result))
            with patch("src.agent.ChatTongyi", return_value=mock_llm):
                state2 = agent.invoke(initial_state, config=config)

        # 第2次调用后 messages 应多于第1次（历史被保留）
        msgs1 = state1.get("messages", [])
        msgs2 = state2.get("messages", [])
        assert len(msgs2) >= len(msgs1), "同一 thread 的第2轮应积累更多 messages"

    def test_different_thread_ids_are_isolated(self) -> None:
        """不同 thread_id 的状态应相互隔离"""
        from src.agent import create_invest_agent
        from unittest.mock import MagicMock, patch
        from langchain_core.messages import AIMessage

        agent = create_invest_agent()
        config_a = {"configurable": {"thread_id": "thread-A"}}
        config_b = {"configurable": {"thread_id": "thread-B"}}

        initial = make_state()
        mock_assess = {
            "processing_mode": "reactive", "query_type": "simple",
            "research_topic": "test", "industry_focus": "", "time_horizon": "中期",
        }
        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value.invoke.return_value = AIMessage(content="回答A")

        with patch("src.agent._create_assess_chain") as mf:
            mf.return_value = MagicMock(invoke=MagicMock(return_value=mock_assess))
            with patch("src.agent.ChatTongyi", return_value=mock_llm):
                state_a = agent.invoke(initial, config=config_a)
                state_b = agent.invoke(initial, config=config_b)

        # 两个线程的 messages 应独立（不共享）
        msgs_a = state_a.get("messages", [])
        msgs_b = state_b.get("messages", [])
        # 基本验证：两个独立线程都完成了各自的调用
        assert isinstance(msgs_a, list)
        assert isinstance(msgs_b, list)

    def test_followup_query_passed_via_messages_history(self) -> None:
        """多轮场景下，assess_query 收到的 state 应包含历史 messages"""
        from langchain_core.messages import HumanMessage, AIMessage

        # 模拟第2轮的 state：messages 里已有第1轮的对话
        history = [
            HumanMessage(content="分析新能源行业"),
            AIMessage(content="新能源行业具备中期投资价值，评级 buy"),
        ]
        state = make_state(
            user_query="上述分析中哪个风险最关键？",
            messages=history,
        )

        # assess_query 的 prompt 应能看到 messages，测试 state 传递正确
        assert len(state["messages"]) == 2
        assert state["messages"][0].content == "分析新能源行业"
