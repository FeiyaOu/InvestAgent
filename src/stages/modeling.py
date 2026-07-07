# -*- coding: utf-8 -*-
"""
阶段2：建模（Modeling）
角色：宏观经济学家

职责：
- 读取感知阶段收集的市场数据
- 构建市场内部世界模型（经济周期判断、风险识别、机会发现）
- 为推理阶段提供分析基础
"""

from __future__ import annotations

import json
import os
from typing import Any

from langchain_community.chat_models import ChatTongyi
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src.state import InvestAgentState

_SYSTEM = """你是一名资深宏观经济学家。
你的职责是基于市场数据构建系统性的市场内部模型，判断经济周期位置，识别风险和机会。
你擅长从宏观视角理解市场结构性变化，为投资决策提供分析框架。
输出必须是严格的 JSON 格式。"""

_HUMAN = """请基于以下市场感知数据，构建市场内部世界模型：

研究主题：{research_topic}
行业焦点：{industry_focus}
时间范围：{time_horizon}

市场感知数据：
{perception_data}

请输出 JSON，包含以下字段：
{{
  "market_state": "当前市场状态评估（如：震荡上行/区间震荡/下行趋势等）",
  "economic_cycle": "经济周期判断（扩张期/顶部/收缩期/底部）及依据",
  "risk_factors": ["主要风险因素1", "主要风险因素2", "主要风险因素3"],
  "opportunity_areas": ["潜在机会领域1", "潜在机会领域2", "潜在机会领域3"],
  "market_sentiment": "市场情绪分析（乐观/中性/悲观）及成因"
}}"""


def _create_chain() -> Any:
    """创建建模阶段推理链（提取为函数以支持测试 mock）"""
    llm = ChatTongyi(
        model_name="qwen-turbo",
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"),
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM),
        ("human", _HUMAN),
    ])
    return prompt | llm | JsonOutputParser()


def modeling(state: InvestAgentState) -> dict:
    """建模阶段节点函数：宏观经济学家构建市场内部世界模型"""
    print("[建模] 构建市场内部世界模型...")

    if not state.get("perception_data"):
        return {
            "error": "建模阶段缺少感知数据，请先完成感知阶段",
            "current_phase": "perception",
        }

    try:
        chain = _create_chain()
        result = chain.invoke({
            "research_topic": state.get("research_topic", ""),
            "industry_focus": state.get("industry_focus", ""),
            "time_horizon": state.get("time_horizon", "中期"),
            "perception_data": json.dumps(state["perception_data"], ensure_ascii=False, indent=2),
        })

        print("[建模] 完成 ✓")
        return {
            "world_model": result,
            "current_phase": "reasoning",
            "error": None,
        }

    except Exception as e:
        print(f"[建模] 出错: {e}")
        return {
            "error": f"建模阶段出错: {str(e)}",
            "current_phase": "modeling",
        }
