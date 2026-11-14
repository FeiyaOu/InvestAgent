# -*- coding: utf-8 -*-
"""
LangGraph Agent 状态定义

InvestAgentState 仅用于保留原报告子图的内部字段。
父图使用 ParentState，市场数据子图使用 MarketDataState；不能将此对象当作公共返回结构。

注意：
- messages 使用 add_messages reducer（追加语义，非覆盖）
  这是工具调用环路（有向环①）能工作的基础
- retry_count 限制 validator 环路最多重试 MAX_VALIDATOR_RETRIES 次
"""

from __future__ import annotations

from typing import Annotated, List, Literal, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

# 最大重试次数（对应 validator 环路②）
MAX_VALIDATOR_RETRIES = 2


class InvestAgentState(TypedDict):
    """原报告子图局部状态；旧模式与消息字段仅保留内部兼容。"""

    # ---- 用户输入 ----
    user_query: str                     # 原始用户查询
    research_topic: str                 # 解析后的研究主题
    industry_focus: str                 # 行业焦点
    time_horizon: str                   # 时间范围（短期/中期/长期）

    # ---- Reactive 路径 ----
    query_type: Optional[Literal["simple", "analytical"]]
    processing_mode: Optional[Literal["reactive", "deliberative"]]
    # add_messages reducer：追加语义，工具调用环路依赖此字段
    messages: Annotated[List[BaseMessage], add_messages]
    final_response: Optional[str]       # reactive 路径的最终回答（C9 约束）

    # ---- Deliberative 路径（5阶段累积）----
    perception_data: Optional[dict]     # 阶段1写入
    world_model: Optional[dict]         # 阶段2写入，读阶段1
    reasoning_plans: Optional[list]     # 阶段3写入（3个候选方案），读阶段1+2
    selected_plan: Optional[dict]       # 阶段4写入，读阶段1+2+3
    final_report: Optional[str]         # 阶段5写入，读全部

    # ---- 质量控制 ----
    validation_errors: Optional[list]   # validator 节点写入
    retry_count: int                    # 防止环②无限循环，上限 MAX_VALIDATOR_RETRIES

    # ---- 控制流 ----
    current_phase: str
    error: Optional[str]
