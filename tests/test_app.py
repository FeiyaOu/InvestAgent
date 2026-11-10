# -*- coding: utf-8 -*-
"""
Streamlit UI 测试（AppTest 进程内运行，mock 掉 Agent，不调用真实 API）

- 消息历史必须是完整对话：stream chunk 只含增量，dict.update 会把 messages 覆盖成最后一个节点的输出
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from streamlit.testing.v1 import AppTest

_APP = str(Path(__file__).parent.parent / "app" / "streamlit_app.py")


def _fake_agent() -> MagicMock:
    tool_call = AIMessage(content="", tool_calls=[
        {"name": "get_stock_performance", "args": {"query": "茅台"}, "id": "tc1"},
    ])
    tool_result = ToolMessage(content="最新收盘 1471.87元", tool_call_id="tc1")
    answer = AIMessage(content="茅台最新收盘 1471.87 元")
    full_messages = [SystemMessage(content="sys"), HumanMessage(content="茅台最新股价"),
                     tool_call, tool_result, answer]

    agent = MagicMock()
    agent.stream.return_value = iter([
        {"assess": {"processing_mode": "reactive", "research_topic": "茅台"}},
        {"reactive_agent": {"messages": full_messages[:3]}},
        {"tools": {"messages": [tool_result]}},
        {"reactive_agent": {"messages": [answer]}},
        {"extract_response": {"final_response": answer.content}},
    ])
    agent.get_state.return_value.values = {
        "processing_mode": "reactive",
        "messages": full_messages,
        "final_response": answer.content,
    }
    return agent


def test_message_history_keeps_full_conversation() -> None:
    with patch("src.agent.create_invest_agent", return_value=_fake_agent()):
        at = AppTest.from_file(_APP, default_timeout=30)
        at.run()
        at.text_area(key="query_input").input("茅台最新股价")
        next(b for b in at.button if "运行" in b.label).click()
        at.run()

    assert not at.exception
    messages = at.session_state["last_result"]["messages"]
    assert [type(m).__name__ for m in messages] == [
        "SystemMessage", "HumanMessage", "AIMessage", "ToolMessage", "AIMessage",
    ]


def test_workspace_exposes_capability_views_and_backend_notice() -> None:
    at = AppTest.from_file(_APP, default_timeout=30).run()
    assert not at.exception
    assert {tab.label for tab in at.tabs} >= {"回答", "数据与证据", "分析与策略", "节点结果", "执行记录"}
    assert any("尚未接入" in item.value for item in at.info)


def test_node_error_is_not_displayed_as_success() -> None:
    agent = _fake_agent()
    agent.stream.return_value = iter([
        {"perception": {"error": "数据整理失败", "current_phase": "perception"}},
    ])
    agent.get_state.return_value.values = {"error": "数据整理失败"}
    with patch("src.agent.create_invest_agent", return_value=agent):
        at = AppTest.from_file(_APP, default_timeout=30).run()
        at.text_area(key="query_input").input("生成新能源报告")
        next(b for b in at.button if "运行" in b.label).click()
        at.run()
    assert not at.exception
    assert any("数据整理失败" in item.value for item in at.error)


def test_report_and_intermediate_results_have_separate_views(valid_report) -> None:
    import json

    at = AppTest.from_file(_APP, default_timeout=30)
    at.session_state["last_result"] = {
        "processing_mode": "deliberative",
        "perception_data": {"market_overview": "市场证据摘要", "recent_news": ["新闻示例"]},
        "world_model": {"market_state": "震荡", "risk_factors": ["波动风险"]},
        "selected_plan": {"investment_thesis": "决策摘要", "selected_plan_id": "A"},
        "final_report": json.dumps(valid_report),
    }
    at.run()
    assert not at.exception
    assert any("决策摘要" in item.value for item in at.tabs[0].markdown)
    assert any("市场证据摘要" in item.value for item in at.tabs[1].markdown)
    assert len(at.tabs[3].metric) == 0
    assert {h.value for h in at.tabs[3].subheader} == {
        "perception_data", "world_model", "reasoning_plans", "selected_plan",
    }
    assert len(at.tabs[3].json) == 3
    assert not any("最终投研报告" in h.value for h in at.subheader)
    assert not any("运行评估" in b.label for b in at.button)
