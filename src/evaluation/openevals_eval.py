# -*- coding: utf-8 -*-
"""
OpenEvals 评估器

使用 OpenEvals 的 LLM-as-judge 模式，以 Qwen 作为评判 LLM，
对 InvestAgent 的输出进行质量评估。

评估维度：
  1. answer_relevance  - 报告是否切题（ANSWER_RELEVANCE_PROMPT）
  2. hallucination     - 报告是否编造超出感知数据的信息（HALLUCINATION_PROMPT）
  3. thesis_quality    - investment_thesis 是否有实质内容（自定义 judge prompt）

使用方式：
    from src.evaluation.openevals_eval import run_openevals

    results = run_openevals(
        query="请分析新能源行业投资机会",
        perception_data={"market_overview": "..."},
        final_report_str='{"dimensions": {...}, ...}',
        investment_thesis="经过综合分析...",
    )
    # results = {"answer_relevance": {...}, "hallucination": {...}, "thesis_quality": {...}}
"""

from __future__ import annotations

import json
import os
from typing import Any


def _get_judge_llm() -> Any | None:
    """创建 Qwen 评判 LLM（需要 DASHSCOPE_API_KEY）"""
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
        print(f"[OpenEvals] 评判 LLM 创建失败: {e}")
        return None


def _safe_evaluate(evaluator: Any, **kwargs) -> dict:
    """安全调用评估器，捕获异常返回 error 结果"""
    try:
        result = evaluator(**kwargs)
        return {
            "score": result.get("score") or result.get("feedback_key"),
            "reasoning": result.get("reasoning", ""),
            "raw": result,
        }
    except Exception as e:
        return {"score": None, "reasoning": f"评估失败: {e}", "raw": {}}


# ============================================================
# 评估1：回答相关性（报告是否切题）
# ============================================================

def evaluate_answer_relevance(query: str, report_str: str) -> dict:
    """
    C 评估：报告内容是否与研究查询相关。

    Args:
        query:      用户的原始研究查询
        report_str: final_report JSON 字符串
    """
    llm = _get_judge_llm()
    if not llm:
        return {"score": None, "reasoning": "评判 LLM 未配置（缺少 DASHSCOPE_API_KEY）"}

    try:
        from openevals.llm import create_llm_as_judge
        from openevals.prompts import ANSWER_RELEVANCE_PROMPT

        evaluator = create_llm_as_judge(
            prompt=ANSWER_RELEVANCE_PROMPT,
            feedback_key="answer_relevance",
            judge=llm,
            continuous=True,
            use_reasoning=True,
        )
        return _safe_evaluate(evaluator, inputs=query, outputs=report_str)

    except ImportError:
        return {"score": None, "reasoning": "openevals 未安装"}
    except Exception as e:
        return {"score": None, "reasoning": f"评估异常: {e}"}


# ============================================================
# 评估2：幻觉检测（报告是否超出感知数据的信息边界）
# ============================================================

def evaluate_hallucination(
    query: str,
    perception_data: dict,
    report_str: str,
) -> dict:
    """
    评估 final_report 是否包含 perception_data 中没有的虚构信息。
    context = perception_data（感知阶段收集的真实数据）
    outputs = final_report（LLM 生成的报告）

    Args:
        query:          用户查询
        perception_data: 感知阶段输出的市场数据
        report_str:     final_report JSON 字符串
    """
    llm = _get_judge_llm()
    if not llm:
        return {"score": None, "reasoning": "评判 LLM 未配置"}

    try:
        from openevals.llm import create_llm_as_judge
        from openevals.prompts import HALLUCINATION_PROMPT

        context = json.dumps(perception_data, ensure_ascii=False, indent=2)

        evaluator = create_llm_as_judge(
            prompt=HALLUCINATION_PROMPT,
            feedback_key="hallucination",
            judge=llm,
            continuous=True,
            use_reasoning=True,
        )
        return _safe_evaluate(
            evaluator,
            inputs=query,
            context=context,
            outputs=report_str,
        )

    except ImportError:
        return {"score": None, "reasoning": "openevals 未安装"}
    except Exception as e:
        return {"score": None, "reasoning": f"评估异常: {e}"}


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
    """
    评估 investment_thesis 的实质质量（对应 spec C7 的语义层面）。

    Args:
        research_topic:     研究主题
        investment_thesis:  决策阶段产出的投资论点
    """
    llm = _get_judge_llm()
    if not llm:
        return {"score": None, "reasoning": "评判 LLM 未配置"}

    try:
        from openevals.llm import create_llm_as_judge

        evaluator = create_llm_as_judge(
            prompt=_THESIS_QUALITY_PROMPT,
            feedback_key="thesis_quality",
            judge=llm,
            continuous=True,
            use_reasoning=True,
        )
        return _safe_evaluate(
            evaluator,
            inputs=research_topic,
            outputs=investment_thesis,
        )

    except ImportError:
        return {"score": None, "reasoning": "openevals 未安装"}
    except Exception as e:
        return {"score": None, "reasoning": f"评估异常: {e}"}


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
