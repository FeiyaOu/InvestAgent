# -*- coding: utf-8 -*-
"""
阶段3：推理（Reasoning）
角色：策略研究员

职责：
- 读取世界模型，生成3个有明显差异的投资分析方案
- 每个方案有独立的投资假设、分析路径、置信度和优缺点
- 方案间应代表不同的投资思路，为决策阶段提供有效选择
"""

from __future__ import annotations

import json
import os
from typing import Any

from langchain_community.chat_models import ChatTongyi
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src.state import InvestAgentState

_SYSTEM = """你是一名资深策略研究员。
你的职责是基于市场世界模型，生成多个有明显差异的投资分析方案供决策层评估。
每个方案应有独立的投资假设和分析逻辑，代表不同的市场视角或投资策略。
你的分析应客观、有理有据，不偏向任何单一结论。
输出必须是严格的 JSON 格式。"""

_HUMAN = """请基于以下市场世界模型，生成3个有明显差异的投资分析方案：

研究主题：{research_topic}
行业焦点：{industry_focus}
时间范围：{time_horizon}

市场世界模型：
{world_model}

请生成3个差异化方案，输出 JSON 数组，每个方案包含：
[
  {{
    "plan_id": "plan_A",
    "hypothesis": "投资假设（该方案的核心判断）",
    "analysis_approach": "分析方法（如：基本面驱动/技术面驱动/政策催化等）",
    "expected_outcome": "预期结果（如：6个月内涨幅20%，理由...）",
    "confidence_level": 0.75,
    "pros": ["优势1", "优势2", "优势3"],
    "cons": ["劣势1", "劣势2"]
  }},
  ...（共3个方案，plan_A/plan_B/plan_C）
]"""


def _create_chain() -> Any:
    """创建推理阶段推理链（提取为函数以支持测试 mock）"""
    llm = ChatTongyi(
        model_name="qwen-turbo",
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"),
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM),
        ("human", _HUMAN),
    ])
    return prompt | llm | JsonOutputParser()


def reasoning(state: InvestAgentState) -> dict:
    """推理阶段节点函数：策略研究员生成3个候选投资方案"""
    print("[推理] 生成候选投资方案...")

    if not state.get("world_model"):
        return {
            "error": "推理阶段缺少世界模型，请先完成建模阶段",
            "current_phase": "modeling",
        }

    try:
        chain = _create_chain()
        result = chain.invoke({
            "research_topic": state.get("research_topic", ""),
            "industry_focus": state.get("industry_focus", ""),
            "time_horizon": state.get("time_horizon", "中期"),
            "world_model": json.dumps(state["world_model"], ensure_ascii=False, indent=2),
        })

        # result 可能是 list（直接的JSON数组）或 dict（包含plans键）
        plans = result if isinstance(result, list) else result.get("plans", result)

        print(f"[推理] 完成 ✓ 生成了 {len(plans) if isinstance(plans, list) else 1} 个方案")
        return {
            "reasoning_plans": plans,
            "current_phase": "decision",
            "error": None,
        }

    except Exception as e:
        print(f"[推理] 出错: {e}")
        return {
            "error": f"推理阶段出错: {str(e)}",
            "current_phase": "reasoning",
        }
