# -*- coding: utf-8 -*-
"""
LangGraph Agent 状态定义

InvestAgentState 是本项目所有 LangGraph 节点共享的唯一状态对象。
所有节点读写同一个 state dict，无需手动传参。

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

# 路由约束常量（对应 spec C8）
VALID_PROCESSING_MODES = {"reactive", "deliberative"}

# 最大重试次数（对应 validator 环路②）
MAX_VALIDATOR_RETRIES = 2


class InvestAgentState(TypedDict):
    """混合型投研 Agent 的统一状态。所有节点共享此 TypedDict。"""

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
