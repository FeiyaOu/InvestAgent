# -*- coding: utf-8 -*-
"""
阶段4：决策（Decision）
角色：投资委员会主席

职责：
- 评估推理阶段生成的3个候选方案
- 综合考虑置信度、风险、与时间框架的匹配度
- 选择最优方案，给出可追溯的 investment_thesis（对应 spec C7）
"""

from __future__ import annotations

import json
import os
from typing import Any

from langchain_community.chat_models import ChatTongyi
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src.state import InvestAgentState

_SYSTEM = """你是一名投资委员会主席。
你的职责是评估多个候选投资方案，综合考虑各方案的假设合理性、风险水平、预期回报与时间框架匹配度，
选择最优方案并形成清晰、可追溯的投资决策。
你的决策必须给出充分的论点依据，不能仅凭直觉。
输出必须是严格的 JSON 格式。"""

_HUMAN = """请评估以下候选方案并作出最终投资决策：

研究主题：{research_topic}
行业焦点：{industry_focus}
时间范围：{time_horizon}

市场世界模型（参考背景）：
{world_model}

候选分析方案：
{reasoning_plans}

请选择最优方案，输出 JSON：
{{
  "selected_plan_id": "plan_A（或B/C）",
  "investment_thesis": "不少于50字的核心投资逻辑，说明为什么选择此方案、关键依据是什么",
  "supporting_evidence": ["支撑证据1", "支撑证据2", "支撑证据3"],
  "risk_assessment": "风险评估：主要风险及应对策略",
  "recommendation": "具体投资建议（如：建议超配、逐步建仓等）",
  "timeframe": "预期时间框架（如：3-6个月）"
}}"""


def _create_chain() -> Any:
    """创建决策阶段推理链（提取为函数以支持测试 mock）"""
    llm = ChatTongyi(
        model_name="qwen-max",   # 决策阶段用更强的模型
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"),
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM),
        ("human", _HUMAN),
    ])
    return prompt | llm | JsonOutputParser()


def decision(state: InvestAgentState) -> dict:
    """决策阶段节点函数：投资委员会主席选择最优方案"""
    print("[决策] 评估候选方案，作出投资决策...")

    if not state.get("reasoning_plans"):
        return {
            "error": "决策阶段缺少候选方案，请先完成推理阶段",
            "current_phase": "reasoning",
        }

    try:
        chain = _create_chain()
        result = chain.invoke({
            "research_topic": state.get("research_topic", ""),
            "industry_focus": state.get("industry_focus", ""),
            "time_horizon": state.get("time_horizon", "中期"),
            "world_model": json.dumps(state.get("world_model", {}), ensure_ascii=False, indent=2),
            "reasoning_plans": json.dumps(state["reasoning_plans"], ensure_ascii=False, indent=2),
        })

        print("[决策] 完成 ✓")
        return {
            "selected_plan": result,
            "current_phase": "report",
            "error": None,
        }

    except Exception as e:
        print(f"[决策] 出错: {e}")
        return {
            "error": f"决策阶段出错: {str(e)}",
            "current_phase": "decision",
        }
