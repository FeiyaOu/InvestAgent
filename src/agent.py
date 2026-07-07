# -*- coding: utf-8 -*-
"""
LangGraph StateGraph — 混合型投研 Agent 连线

本模块是整个 Agent 的编排中心。职责：
- 定义所有节点（assess, reactive_agent, tools, extract_response, 5个deliberative阶段, validator）
- 定义路由函数（路由逻辑对应 spec C8/C9）
- 编译 StateGraph，暴露 create_invest_agent() 和 run_invest_agent()

图结构：
  assess
    ├─ reactive → reactive_agent ⟲ tools（有向环①）→ extract_response → END
    └─ deliberative → perception → modeling → reasoning → decision → report
                                                               ↑            ↓
                                                          validator（有向环②）
                                                               ↓
                                                              END
"""

from __future__ import annotations

import json
import os
from typing import Any

from langchain_community.chat_models import ChatTongyi
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from src.stages.decision import decision
from src.stages.modeling import modeling
from src.stages.perception import perception
from src.stages.reasoning import reasoning
from src.stages.reporter import report_generation
from src.stages.validator import validator
from src.state import VALID_PROCESSING_MODES, InvestAgentState
from src.tools import INVEST_TOOLS

# ============================================================
# 路由常量
# ============================================================

_DEFAULT_MODE = "reactive"

# ============================================================
# assess 节点：协调层，判断 processing_mode（对应 C8）
# ============================================================

_ASSESS_SYSTEM = """你是一个智能投研助手的协调层。
你需要判断用户查询的复杂度，决定处理模式：

- reactive（反应式）：适合简单、直接的查询
  例如：查询当天行情、询问某只股票价格、查最新指数点位
- deliberative（深思熟虑）：适合需要深度研究的查询
  例如：行业投资分析、投资机会报告、多维度市场研究

同时解析出研究主题、行业焦点、时间范围。
输出必须是 JSON 格式。"""

_ASSESS_HUMAN = """对话历史（如有，最近2轮）：
{conversation_summary}

当前查询：{user_query}

判断规则：
- 如果当前查询是对已有分析的跟进（追问细节/风险/建议），选 reactive
- 如果是全新研究主题或不同行业，选 deliberative
- 没有对话历史时，按查询本身的复杂度判断

请输出 JSON：
{{
  "processing_mode": "reactive 或 deliberative",
  "query_type": "simple 或 analytical",
  "research_topic": "研究主题（如：新能源行业）",
  "industry_focus": "行业焦点（如：光伏）",
  "time_horizon": "时间范围（短期/中期/长期，默认中期）"
}}"""


def _create_assess_chain() -> Any:
    """创建评估链（提取为函数以支持测试 mock）"""
    llm = ChatTongyi(
        model_name="qwen-turbo",
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"),
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", _ASSESS_SYSTEM),
        ("human", _ASSESS_HUMAN),
    ])
    return prompt | llm | JsonOutputParser()


def assess_query(state: InvestAgentState) -> dict:
    """协调层：判断查询类型，设置 processing_mode（C8 约束的执行者）"""
    print(f"[评估] 分析查询：'{state.get('user_query', '')[:50]}...'")

    try:
        # 构建对话历史摘要（最近2轮，用于跟进检测）
        messages = state.get("messages", [])
        if messages:
            recent = messages[-4:]  # 最近4条消息（约2轮）
            conversation_summary = "\n".join(
                f"{'用户' if isinstance(m, HumanMessage) else 'Agent'}: {getattr(m, 'content', '')[:100]}"
                for m in recent if getattr(m, 'content', '')
            )
        else:
            conversation_summary = "（无历史对话）"

        chain = _create_assess_chain()
        result = chain.invoke({
            "user_query": state.get("user_query", ""),
            "conversation_summary": conversation_summary,
        })

        # C8：强制校验 processing_mode，非法值 fallback 到 reactive
        mode = result.get("processing_mode", _DEFAULT_MODE)
        if mode not in VALID_PROCESSING_MODES:
            print(f"[评估] 无效 processing_mode='{mode}'，fallback 到 '{_DEFAULT_MODE}'")
            mode = _DEFAULT_MODE

        query_type = result.get("query_type", "simple")
        if query_type not in {"simple", "analytical"}:
            query_type = "simple"

        print(f"[评估] 路由到：{mode}")
        return {
            "processing_mode": mode,
            "query_type": query_type,
            "research_topic": result.get("research_topic", state.get("user_query", "")),
            "industry_focus": result.get("industry_focus", ""),
            "time_horizon": result.get("time_horizon", "中期"),
        }

    except Exception as e:
        print(f"[评估] 出错，fallback 到 reactive: {e}")
        return {
            "processing_mode": _DEFAULT_MODE,
            "query_type": "simple",
            "research_topic": state.get("research_topic") or state.get("user_query", ""),
            "industry_focus": state.get("industry_focus", ""),
            "time_horizon": state.get("time_horizon", "中期"),
        }


# ============================================================
# Reactive 路径节点
# ============================================================

def reactive_agent(state: InvestAgentState) -> dict:
    """反应式路径：LLM 决策调用工具，快速回答简单查询"""
    print("[反应] 处理简单查询...")

    llm_with_tools = ChatTongyi(
        model_name="qwen-turbo",
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"),
    ).bind_tools(INVEST_TOOLS)

    messages = state.get("messages", [])
    if not messages:
        # 首次调用，构建初始消息
        messages = [
            SystemMessage(content="你是一个专业的市场数据助手，可以调用工具查询实时市场数据，提供简洁准确的回答。"),
            HumanMessage(content=state.get("user_query", "")),
        ]

    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}   # add_messages reducer 自动追加


def extract_reactive_response(state: InvestAgentState) -> dict:
    """从消息历史中提取最终文本回答（C9：必须是非空字符串）"""
    messages = state.get("messages", [])
    for msg in reversed(messages):
        # 找到最后一条没有 tool_calls 的 AI 消息
        if isinstance(msg, AIMessage) and msg.content:
            if not (hasattr(msg, "tool_calls") and msg.tool_calls):
                print("[反应] 提取回答 ✓")
                return {"final_response": msg.content}
    # C9 fallback：保证 final_response 永远是非空字符串
    return {"final_response": "已收到您的查询，但无法生成具体回答，请稍后重试。"}


# ============================================================
# 路由函数
# ============================================================

def route_after_assess(state: InvestAgentState) -> str:
    """assess 节点后的路由：只有明确的 deliberative 才走深度分析路径，其余全部走 reactive"""
    mode = state.get("processing_mode")
    return "perception" if mode == "deliberative" else "reactive_agent"


def should_continue_tools(state: InvestAgentState) -> str:
    """reactive_agent 节点后的路由：有 tool_calls → tools，否则 → extract_response
    这是有向环①的控制函数。
    """
    messages = state.get("messages", [])
    if not messages:
        return "extract_response"
    last = messages[-1]
    if isinstance(last, AIMessage) and hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return "extract_response"


def route_after_validator(state: InvestAgentState) -> str:
    """validator 节点后的路由：retry → decision，通过 → END
    这是有向环②的控制函数。
    """
    if state.get("current_phase") == "decision":
        return "decision"
    return END


# ============================================================
# 图构建与编译
# ============================================================

def create_invest_agent() -> Any:
    """构建并编译 InvestAgent StateGraph"""
    workflow = StateGraph(InvestAgentState)

    # ---- 注册所有节点 ----
    workflow.add_node("assess", assess_query)
    workflow.add_node("reactive_agent", reactive_agent)
    workflow.add_node("tools", ToolNode(INVEST_TOOLS))          # 内置工具执行节点
    workflow.add_node("extract_response", extract_reactive_response)
    workflow.add_node("perception", perception)
    workflow.add_node("modeling", modeling)
    workflow.add_node("reasoning", reasoning)
    workflow.add_node("decision", decision)
    workflow.add_node("report", report_generation)
    workflow.add_node("validator", validator)

    # ---- 入口 ----
    workflow.set_entry_point("assess")

    # ---- assess → 两条路径分叉（C8 路由）----
    workflow.add_conditional_edges(
        "assess",
        route_after_assess,
        {"reactive_agent": "reactive_agent", "perception": "perception"},
    )

    # ---- 有向环①：Reactive 工具调用循环 ----
    workflow.add_conditional_edges(
        "reactive_agent",
        should_continue_tools,
        {"tools": "tools", "extract_response": "extract_response"},
    )
    workflow.add_edge("tools", "reactive_agent")         # ← 环①回边
    workflow.add_edge("extract_response", END)

    # ---- Deliberative 线性管道 ----
    workflow.add_edge("perception", "modeling")
    workflow.add_edge("modeling", "reasoning")
    workflow.add_edge("reasoning", "decision")
    workflow.add_edge("decision", "report")
    workflow.add_edge("report", "validator")

    # ---- 有向环②：Validator 重试路由 ----
    workflow.add_conditional_edges(
        "validator",
        route_after_validator,
        {"decision": "decision", END: END},
    )

    return workflow.compile(checkpointer=MemorySaver())


# ============================================================
# 公开 API
# ============================================================

def run_invest_agent(
    user_query: str,
    research_topic: str = "",
    industry_focus: str = "",
    time_horizon: str = "中期",
    thread_id: str = "default",
) -> dict:
    """运行 InvestAgent 并返回最终状态"""
    agent = create_invest_agent()

    initial_state: InvestAgentState = {
        "user_query": user_query,
        "research_topic": research_topic or user_query,
        "industry_focus": industry_focus,
        "time_horizon": time_horizon,
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

    print("\n" + "=" * 60)
    print(f"InvestAgent — LangGraph Mermaid 流程图：")
    print(agent.get_graph().draw_mermaid())
    print("=" * 60 + "\n")

    config: dict = {"configurable": {"thread_id": thread_id}}

    # 注入 LangFuse 追踪（如已配置）
    try:
        from src.evaluation.langfuse_tracing import get_langfuse_handler
        handler = get_langfuse_handler()
        if handler:
            config["callbacks"] = [handler]
            print("[LangFuse] 追踪已启用")
    except Exception:
        pass

    return agent.invoke(initial_state, config=config)
