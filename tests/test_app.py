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
