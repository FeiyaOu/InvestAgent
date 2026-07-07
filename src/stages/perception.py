# -*- coding: utf-8 -*-
"""
阶段1：感知（Perception）
角色：市场数据分析师

职责：
- 调用 AKShare 工具收集真实市场数据（行业板块、指数、宏观、新闻）
- 用 LLM 将原始数据综合整理为结构化的 PerceptionOutput
- 只负责数据收集，不做主观投资判断
"""

from __future__ import annotations

import os
from typing import Any

from langchain_community.chat_models import ChatTongyi
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src.state import InvestAgentState
from src.tools import (
    get_index_performance,
    get_macro_indicators,
    get_sector_performance,
    search_stock_news,
)

# ---- 角色 Persona（Hat System）----
_SYSTEM = """你是一名专业的市场数据分析师。
你的职责是系统性地收集和整理指定研究主题的多维度市场信息。
你只负责数据收集和客观整理，不进行主观投资判断，不给出买卖建议。
输出必须是严格的 JSON 格式。"""

_HUMAN = """请收集以下研究主题的市场信息并整理为结构化报告：

研究主题：{research_topic}
行业焦点：{industry_focus}
时间范围：{time_horizon}

以下是已采集的原始市场数据，请基于此进行整理分析：

【行业板块表现】
{sector_data}

【主要指数行情】
{index_data}

【宏观经济指标】
{macro_data}

【近期市场新闻】
{news_data}

请输出 JSON，包含以下字段：
{{
  "market_overview": "不少于100字的市场概况和最新动态",
  "key_indicators": {{"指标名": "指标值和简要说明"}},
  "recent_news": ["新闻1", "新闻2", "新闻3"],
  "industry_trends": {{"细分领域1": "趋势描述", "细分领域2": "趋势描述", "细分领域3": "趋势描述"}}
}}"""


def _create_chain() -> Any:
    """创建感知阶段推理链（提取为函数以支持测试 mock）"""
    llm = ChatTongyi(
        model_name="qwen-turbo",
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"),
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM),
        ("human", _HUMAN),
    ])
    return prompt | llm | JsonOutputParser()


def perception(state: InvestAgentState) -> dict:
    """感知阶段节点函数：调用工具收集数据，LLM 综合整理"""
    print(f"[感知] 收集 '{state.get('research_topic', '')} / {state.get('industry_focus', '')}' 数据...")

    try:
        # Step 1：调用工具获取真实（或 mock）市场数据
        sector_data = get_sector_performance.invoke(
            {"sector": state.get("industry_focus", state.get("research_topic", "新能源"))}
        )
        index_data = get_index_performance.invoke({})
        macro_data = get_macro_indicators.invoke({})
        news_data = search_stock_news.invoke({"keyword": state.get("research_topic", "")})

        # Step 2：LLM 综合整理为 PerceptionOutput 结构
        chain = _create_chain()
        result = chain.invoke({
            "research_topic": state.get("research_topic", ""),
            "industry_focus": state.get("industry_focus", ""),
            "time_horizon": state.get("time_horizon", "中期"),
            "sector_data": sector_data,
            "index_data": index_data,
            "macro_data": macro_data,
            "news_data": news_data,
        })

        print("[感知] 完成 ✓")
        return {
            "perception_data": result,
            "current_phase": "modeling",
            "error": None,
        }

    except Exception as e:
        print(f"[感知] 出错: {e}")
        return {
            "error": f"感知阶段出错: {str(e)}",
            "current_phase": "perception",
        }
