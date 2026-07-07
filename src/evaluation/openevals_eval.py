# -*- coding: utf-8 -*-
"""
LLM-as-judge 评估器

使用 Qwen 作为评判 LLM，以直接 LangChain chain 调用方式实现评估
（避免 openevals 内置 prompts 与 Qwen 的 JSON 输出格式不兼容问题）。

评估维度：
  1. answer_relevance  - 报告是否切题
  2. hallucination     - 报告是否编造超出感知数据的信息（分数越低越好）
  3. thesis_quality    - investment_thesis 是否有实质投资逻辑（对应 spec C7）
"""

from __future__ import annotations

import json
import os
from typing import Any


def _create_judge_chain(prompt_template: str) -> Any | None:
    """创建评判链：ChatTongyi + ChatPromptTemplate + JsonOutputParser"""
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        return None
    try:
        from langchain_community.chat_models import ChatTongyi
        from langchain_core.output_parsers import JsonOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        llm = ChatTongyi(model_name="qwen-turbo", dashscope_api_key=api_key, temperature=0)
        prompt = ChatPromptTemplate.from_messages([("human", prompt_template)])
        return prompt | llm | JsonOutputParser()
    except Exception as e:
        print(f"[Eval] 评判链创建失败: {e}")
        return None


def _run_chain(chain: Any, **kwargs) -> dict:
    """安全调用评判链，返回标准化结果"""
    if chain is None:
        return {"score": None, "reasoning": "评判 LLM 未配置（缺少 DASHSCOPE_API_KEY）"}
    try:
        result = chain.invoke(kwargs)
        return {
            "score": result.get("score"),
            "reasoning": result.get("reasoning", ""),
            "raw": result,
        }
    except Exception as e:
        return {"score": None, "reasoning": f"评估失败: {e}", "raw": {}}


# ============================================================
# 评估1：回答相关性
# ============================================================

_ANSWER_RELEVANCE_PROMPT = """\
你是专业投资研究质量评估员。请评估以下投研报告是否切题地回答了研究查询。

研究查询：{inputs}
投研报告摘要（前500字）：{outputs}

评分标准：
- 1.0：完全切题，直接回答查询
- 0.7：大部分切题，有少量偏离
- 0.4：部分切题，有明显偏离
- 0.0：完全不切题

仅输出 JSON，不要其他内容：{{"score": 0.85, "reasoning": "评审理由"}}
"""


def evaluate_answer_relevance(query: str, report_str: str) -> dict:
    """评估报告是否切题（回答相关性）。"""
    chain = _create_judge_chain(_ANSWER_RELEVANCE_PROMPT)
    return _run_chain(chain, inputs=query, outputs=report_str[:500])


# ============================================================
# 评估2：幻觉检测

_HALLUCINATION_PROMPT = """\
你是一个专业的投资研究事实核查员。请判断以下投研报告中是否包含超出提供的市场感知数据的虚构信息。

市场感知数据（真实数据来源）：
{context}

研究查询：{inputs}
投研报告摘要：{outputs}

评分标准（幻觉程度，分数越低越好）：
- 0.0：报告完全基于感知数据，无虚构
- 0.3：小部分信息超出数据范围但属于合理推断
- 0.7：部分信息明显虚构或与数据矛盾
- 1.0：大量虚构信息，严重脱离数据

请以 JSON 格式输出：{{"score": 0.2, "reasoning": "核查说明..."}}
注：score 越低表示幻觉越少，质量越好。
"""


def evaluate_hallucination(query: str, perception_data: dict, report_str: str) -> dict:
    """评估报告是否编造超出感知数据的信息（分数越低越好）。"""
    chain = _create_judge_chain(_HALLUCINATION_PROMPT)
    context_str = json.dumps(perception_data, ensure_ascii=False)[:800]
    return _run_chain(chain, inputs=query, context=context_str, outputs=report_str[:500])


# ============================================================
# 评估3：investment_thesis 质量（自定义 LLM-as-judge）
# 对应 spec C7：thesis >= 50字，且需有实质投资逻辑
# ============================================================

_THESIS_QUALITY_PROMPT = """\
你是一名专业投资研究质量评审员。请评估以下投资论点（investment_thesis）的质量。

评估维度：
1. 逻辑清晰：论点是否有明确的推理链条
2. 有据可依：论点是否基于具体数据或市场事实，而非空泛表述
3. 决策性：论点是否给出了明确的投资方向（看多/看空/中性）和理由

研究主题：{inputs}
投资论点：{outputs}

请给出 0.0 到 1.0 之间的质量评分，并说明理由。
0.0 = 完全空洞无意义
0.5 = 有基本方向但论据不足
1.0 = 逻辑清晰、有据可依、具备决策价值

输出格式（JSON）：
{{"score": 0.8, "reasoning": "..."}}
"""


def evaluate_thesis_quality(research_topic: str, investment_thesis: str) -> dict:
    """评估 investment_thesis 的实质质量（对应 spec C7 的语义层面）。"""
    chain = _create_judge_chain(_THESIS_QUALITY_PROMPT)
    return _run_chain(chain, inputs=research_topic, outputs=investment_thesis)


# ============================================================
# 统一入口：对 final_state 运行全部评估
# ============================================================

def run_openevals(final_state: dict) -> dict:
    """
    对 InvestAgent 的 final_state 运行全部 OpenEvals 评估。

    Args:
        final_state: agent.invoke() 或 agent.stream() 的最终 state

    Returns:
        dict with keys: answer_relevance, hallucination, thesis_quality
    """
    query = final_state.get("user_query", "")
    research_topic = final_state.get("research_topic", query)
    report_str = final_state.get("final_report", "")
    perception_data = final_state.get("perception_data") or {}
    selected_plan = final_state.get("selected_plan") or {}
    investment_thesis = selected_plan.get("investment_thesis", "")

    if not report_str:
        return {
            "answer_relevance": {"score": None, "reasoning": "无 final_report，跳过评估"},
            "hallucination":    {"score": None, "reasoning": "无 final_report，跳过评估"},
            "thesis_quality":   {"score": None, "reasoning": "无 investment_thesis，跳过评估"},
        }

    print("[OpenEvals] 运行评估（使用 Qwen 作为评判 LLM）...")

    results = {
        "answer_relevance": evaluate_answer_relevance(query, report_str),
        "hallucination":    evaluate_hallucination(query, perception_data, report_str),
        "thesis_quality":   evaluate_thesis_quality(research_topic, investment_thesis),
    }

    for name, r in results.items():
        score = r.get("score")
        score_str = f"{score:.2f}" if isinstance(score, float) else str(score)
        print(f"[OpenEvals] {name}: {score_str}")

    return results
