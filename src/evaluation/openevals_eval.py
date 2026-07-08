# -*- coding: utf-8 -*-
"""
LLM-as-judge 评估器

使用 OpenEvals `create_llm_as_judge` + Qwen 作为评判 LLM。
针对 Qwen 在 structured output 下偶发漏掉 `score` 字段的问题，
增加一个仅解析 `reasoning` 末尾分数句的兼容兜底。

评估维度：
  1. answer_relevance  - 报告是否切题
  2. hallucination     - 报告是否编造超出感知数据的信息（分数越低越好）
  3. thesis_quality    - investment_thesis 是否有实质投资逻辑（对应 spec C7）
"""

from __future__ import annotations

import json
import os
import re
from typing import Any


def _get_qwen_judge() -> Any | None:
    """创建 OpenEvals 使用的 Qwen judge。"""
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        return None

    try:
        from langchain_community.chat_models import ChatTongyi

        return ChatTongyi(
            model_name="qwen-turbo",
            dashscope_api_key=api_key,
            temperature=0,
        )
    except Exception as e:
        print(f"[Eval] Qwen judge 创建失败: {e}")
        return None


def _create_qwen_compatible_schema() -> dict[str, Any]:
    """Qwen 在 structured output 下有时漏掉 score，故仅强制 reasoning。"""
    return {
        "title": "score",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "reasoning": {
                "type": "string",
                "description": (
                    "A human-readable explanation of the score. "
                    "You MUST end the reasoning with a sentence that says: "
                    "Thus, the score should be: SCORE_YOU_ASSIGN."
                ),
            },
            "score": {
                "type": "number",
                "description": "A number between 0.0 and 1.0.",
            },
        },
        "required": ["reasoning"],
    }


def _extract_score(result: dict[str, Any]) -> float | None:
    """优先读取 score 字段，否则从 reasoning 末尾句抽取分数。"""
    score = result.get("score")
    if isinstance(score, (int, float)):
        return float(score)

    reasoning = result.get("reasoning", "")
    if not isinstance(reasoning, str):
        return None

    match = re.search(r"score should be:\s*([01](?:\.\d+)?)", reasoning, re.IGNORECASE)
    if not match:
        return None

    try:
        parsed = float(match.group(1))
    except ValueError:
        return None

    return max(0.0, min(1.0, parsed))


def _create_evaluator(prompt_template: str, feedback_key: str) -> Any | None:
    """创建真正的 OpenEvals evaluator。"""
    judge = _get_qwen_judge()
    if judge is None:
        return None

    try:
        from openevals.llm import create_llm_as_judge

        return create_llm_as_judge(
            prompt=prompt_template,
            feedback_key=feedback_key,
            judge=judge,
            continuous=True,
            use_reasoning=True,
            output_schema=_create_qwen_compatible_schema(),
        )
    except Exception as e:
        print(f"[Eval] OpenEvals evaluator 创建失败: {e}")
        return None


def _run_evaluator(evaluator: Any, **kwargs) -> dict:
    """安全调用 OpenEvals evaluator，返回标准化结果。"""
    if evaluator is None:
        return {"score": None, "reasoning": "评判 LLM 未配置（缺少 DASHSCOPE_API_KEY）", "raw": {}}

    try:
        result = evaluator(**kwargs)
        if not isinstance(result, dict):
            return {
                "score": None,
                "reasoning": f"评估失败: OpenEvals 返回了非 dict 结果 {type(result).__name__}",
                "raw": result,
            }

        return {
            "score": _extract_score(result),
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

请基于以上标准给出 0.0 到 1.0 的分数，并解释理由。
"""


def evaluate_answer_relevance(query: str, report_str: str) -> dict:
    """评估报告是否切题（回答相关性）。"""
    evaluator = _create_evaluator(_ANSWER_RELEVANCE_PROMPT, "answer_relevance")
    return _run_evaluator(evaluator, inputs=query, outputs=report_str[:500])


# ============================================================
# 评估2：幻觉检测
# ============================================================

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

请基于以上标准给出 0.0 到 1.0 的分数，并解释理由。
注：score 越低表示幻觉越少，质量越好。
"""


def evaluate_hallucination(query: str, perception_data: dict, report_str: str) -> dict:
    """评估报告是否编造超出感知数据的信息（分数越低越好）。"""
    evaluator = _create_evaluator(_HALLUCINATION_PROMPT, "hallucination")
    context_str = json.dumps(perception_data, ensure_ascii=False)[:800]
    return _run_evaluator(evaluator, inputs=query, context=context_str, outputs=report_str[:500])


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

请基于以上标准给出 0.0 到 1.0 的分数，并解释理由。
"""


def evaluate_thesis_quality(research_topic: str, investment_thesis: str) -> dict:
    """评估 investment_thesis 的实质质量（对应 spec C7 的语义层面）。"""
    evaluator = _create_evaluator(_THESIS_QUALITY_PROMPT, "thesis_quality")
    return _run_evaluator(evaluator, inputs=research_topic, outputs=investment_thesis)


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
            "hallucination": {"score": None, "reasoning": "无 final_report，跳过评估"},
            "thesis_quality": {"score": None, "reasoning": "无 investment_thesis，跳过评估"},
        }

    print("[OpenEvals] 运行评估（使用 OpenEvals create_llm_as_judge + Qwen）...")

    results = {
        "answer_relevance": evaluate_answer_relevance(query, report_str),
        "hallucination": evaluate_hallucination(query, perception_data, report_str),
        "thesis_quality": evaluate_thesis_quality(research_topic, investment_thesis),
    }

    for name, r in results.items():
        score = r.get("score")
        score_str = f"{score:.2f}" if isinstance(score, float) else str(score)
        print(f"[OpenEvals] {name}: {score_str}")

    return results
