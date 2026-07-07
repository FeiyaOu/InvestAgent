# -*- coding: utf-8 -*-
"""
Pydantic 数据模型

定义两类模型：
1. 各阶段 LLM 输出模型（PerceptionOutput, ModelingOutput, ReasoningPlan,
   DecisionOutput）—— 用于 Pydantic 分阶段输出验证
2. 最终报告模型（ReportDimension, FinalReport）—— 对应 spec/invest_spec.md
   的报告格式，validate_report() 校验的目标结构

注意：InvestAgentState（LangGraph TypedDict）定义在 src/agent.py 中。
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ============================================================
# 阶段1：感知（Perception）
# 角色：市场数据分析师
# ============================================================

class PerceptionOutput(BaseModel):
    """感知阶段输出 — 市场数据分析师收集的多维度市场信息"""

    market_overview: str = Field(..., description="市场概况和最新动态")
    key_indicators: Dict[str, str] = Field(..., description="关键经济和市场指标，键为指标名，值为指标值+简要说明")
    recent_news: List[str] = Field(..., description="近期重要新闻，至少3条", min_length=1)
    industry_trends: Dict[str, str] = Field(..., description="行业趋势分析，键为细分领域，值为趋势描述")


# ============================================================
# 阶段2：建模（Modeling）
# 角色：宏观经济学家
# ============================================================

class ModelingOutput(BaseModel):
    """建模阶段输出 — 宏观经济学家构建的市场内部世界模型"""

    market_state: str = Field(..., description="当前市场状态评估")
    economic_cycle: str = Field(..., description="经济周期判断（扩张/顶部/收缩/底部）")
    risk_factors: List[str] = Field(..., description="主要风险因素，至少3个", min_length=1)
    opportunity_areas: List[str] = Field(..., description="潜在机会领域，至少3个", min_length=1)
    market_sentiment: str = Field(..., description="市场情绪分析（乐观/中性/悲观）")


# ============================================================
# 阶段3：推理（Reasoning）
# 角色：策略研究员
# ============================================================

class ReasoningPlan(BaseModel):
    """推理阶段生成的单个候选投资分析方案"""

    plan_id: str = Field(..., description="方案ID，如 plan_A / plan_B / plan_C")
    hypothesis: str = Field(..., description="投资假设")
    analysis_approach: str = Field(..., description="分析方法")
    expected_outcome: str = Field(..., description="预期结果")
    confidence_level: float = Field(..., description="置信度，范围 [0.0, 1.0]", ge=0.0, le=1.0)
    pros: List[str] = Field(..., description="方案优势，至少3条", min_length=1)
    cons: List[str] = Field(..., description="方案劣势，至少2条", min_length=1)

    @field_validator("confidence_level")
    @classmethod
    def confidence_must_be_in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence_level 必须在 [0.0, 1.0] 范围内，当前值: {v}")
        return v


class ReasoningOutput(BaseModel):
    """推理阶段整体输出 — 包含3个有明显差异的候选方案"""

    plans: List[ReasoningPlan] = Field(..., description="候选方案列表，应包含3个方案", min_length=1)


# ============================================================
# 阶段4：决策（Decision）
# 角色：投资委员会主席
# ============================================================

class DecisionOutput(BaseModel):
    """决策阶段输出 — 投资委员会主席选定的最优方案"""

    selected_plan_id: str = Field(..., description="选中的方案ID，对应 ReasoningPlan.plan_id")
    investment_thesis: str = Field(..., description="投资论点，不少于50字的核心投资逻辑")
    supporting_evidence: List[str] = Field(..., description="支撑选定方案的证据列表", min_length=1)
    risk_assessment: str = Field(..., description="风险评估")
    recommendation: str = Field(..., description="投资建议")
    timeframe: str = Field(..., description="时间框架（短期/中期/长期）")

    @field_validator("investment_thesis")
    @classmethod
    def thesis_must_be_substantial(cls, v: str) -> str:
        if len(v) < 50:
            raise ValueError(f"investment_thesis 不少于50字符，当前长度: {len(v)}")
        return v


# ============================================================
# 阶段5：报告（Report）
# 角色：资深研究报告撰写专家
# ============================================================

class ReportDimension(BaseModel):
    """报告中单个分析维度的结构（对应 spec C1–C3）"""

    summary: str = Field(..., description="该维度的分析摘要，不少于100字符")
    confidence: float = Field(..., description="分析置信度，范围 [0.0, 1.0]", ge=0.0, le=1.0)

    @field_validator("summary")
    @classmethod
    def summary_must_be_substantial(cls, v: str) -> str:
        if len(v) < 100:
            raise ValueError(f"summary 不少于100字符，当前长度: {len(v)}")
        return v

    @field_validator("confidence")
    @classmethod
    def confidence_must_be_in_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence 必须在 [0.0, 1.0] 范围内，当前值: {v}")
        return v


class FinalReport(BaseModel):
    """最终投研报告结构 — 对应 spec/invest_spec.md 报告格式，满足 C1–C7"""

    research_topic: str = Field(..., description="研究主题")
    industry_focus: str = Field(..., description="行业焦点")
    time_horizon: str = Field(..., description="时间范围")
    report_date: str = Field(
        default_factory=lambda: date.today().isoformat(),
        description="报告生成日期，格式 YYYY-MM-DD",
    )

    # C1–C3：维度完整性、摘要长度、置信度范围
    dimensions: Dict[str, ReportDimension] = Field(
        ...,
        description="四个分析维度：fundamental / market / news / analyst",
    )

    # C7：investment_thesis 是深思熟虑路径的核心产出
    investment_thesis: str = Field(..., description="核心投资论点，不少于50字符")

    supporting_evidence: List[str] = Field(..., description="支撑投资论点的证据列表", min_length=1)

    # C4：评级有效值
    overall_rating: Literal["buy", "hold", "sell"] = Field(..., description="整体评级")

    # C6：风险因素不能为空
    risk_factors: List[str] = Field(..., description="风险因素列表，不能为空", min_length=1)

    # C5：来源数量
    sources: List[str] = Field(..., description="数据来源列表，至少3个", min_length=1)

    @field_validator("investment_thesis")
    @classmethod
    def thesis_must_be_substantial(cls, v: str) -> str:
        if len(v) < 50:
            raise ValueError(f"investment_thesis 不少于50字符，当前长度: {len(v)}")
        return v

    @field_validator("sources")
    @classmethod
    def sources_must_have_minimum(cls, v: List[str]) -> List[str]:
        if len(v) < 3:
            raise ValueError(f"sources 至少3个，当前数量: {len(v)}")
        return v

    @field_validator("risk_factors")
    @classmethod
    def risk_factors_must_not_be_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("risk_factors 不能为空")
        return v
