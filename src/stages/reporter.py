# -*- coding: utf-8 -*-
"""
报告生成与结构校验模块

validate_report() 是本项目唯一的报告校验入口。
错误信息中嵌入修复指令（Harness Engineering 核心理念），
让 AI Agent 看到错误后可以自我纠正，形成闭环。

约束常量与 spec/invest_spec.md 保持严格同步：
  修改任何常量前必须先更新 spec 文档。
"""

from __future__ import annotations

# ---- Spec 约束常量（linter 会检查这些常量必须存在）----
REQUIRED_DIMENSIONS = ["fundamental", "market", "news", "analyst"]
VALID_RATINGS = {"buy", "hold", "sell"}
MIN_SUMMARY_LENGTH = 100
MIN_SOURCES = 3
MIN_THESIS_LENGTH = 50


def validate_report(report: dict) -> list[dict]:
    """
    校验投研报告是否符合 spec C1–C7。

    参数:
        report: 待校验的报告字典（LLM 输出或 FinalReport.model_dump()）

    返回:
        错误列表，空列表表示校验通过。
        每个错误包含：
          - type:   错误类型标识符（见 spec/invest_spec.md）
          - detail: 人类可读的错误详情
          - fix:    修复指令（AI Agent 可直接执行）
    """
    errors: list[dict] = []

    # ---- C1：维度完整性 ----
    dims = report.get("dimensions", {})
    if not isinstance(dims, dict):
        dims = {}

    for dim in REQUIRED_DIMENSIONS:
        if dim not in dims:
            errors.append({
                "type": "missing_dimension",
                "detail": f"缺少维度: {dim}",
                "fix": (
                    f"在 dimensions 中添加 '{dim}' 键，"
                    f"包含 'summary'（>={MIN_SUMMARY_LENGTH}字）和 'confidence'（0-1）字段。"
                    f"参考 spec/invest_spec.md 中的报告格式。"
                ),
            })

    # ---- C2 + C3：每个维度的字段校验 ----
    for dim_name, dim_data in dims.items():
        if not isinstance(dim_data, dict):
            errors.append({
                "type": "invalid_dimension_format",
                "detail": f"维度 {dim_name} 格式错误，应为字典",
                "fix": (
                    f"将 dimensions['{dim_name}'] 改为 "
                    f"{{'summary': '...', 'confidence': 0.8}} 格式。"
                ),
            })
            continue

        # C2：摘要最小长度
        summary = dim_data.get("summary", "")
        if len(summary) < MIN_SUMMARY_LENGTH:
            errors.append({
                "type": "summary_too_short",
                "detail": (
                    f"{dim_name}: 摘要长度 {len(summary)} 字符，"
                    f"要求至少 {MIN_SUMMARY_LENGTH}"
                ),
                "fix": (
                    f"扩充 dimensions['{dim_name}']['summary'] 的内容，"
                    f"至少 {MIN_SUMMARY_LENGTH} 个字符。"
                ),
            })

        # C3：置信度范围
        confidence = dim_data.get("confidence")
        if confidence is None:
            errors.append({
                "type": "missing_confidence",
                "detail": f"{dim_name}: 缺少 confidence 字段",
                "fix": (
                    f"为 dimensions['{dim_name}'] 添加 'confidence' 字段，"
                    f"值域 [0.0, 1.0]。"
                ),
            })
        elif not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
            errors.append({
                "type": "confidence_out_of_range",
                "detail": f"{dim_name}: confidence={confidence}，超出 [0, 1] 范围",
                "fix": (
                    f"将 dimensions['{dim_name}']['confidence'] 修正为 "
                    f"0.0 到 1.0 之间的值。"
                ),
            })

    # ---- C4：评级有效值 ----
    rating = report.get("overall_rating")
    if rating is None:
        errors.append({
            "type": "invalid_rating",
            "detail": "缺少 overall_rating 字段",
            "fix": f"添加 overall_rating 字段，值必须是 {sorted(VALID_RATINGS)} 之一。",
        })
    elif rating not in VALID_RATINGS:
        errors.append({
            "type": "invalid_rating",
            "detail": f"overall_rating='{rating}'，不在允许的值集合中",
            "fix": (
                f"将 overall_rating 修改为 {sorted(VALID_RATINGS)} 之一。"
                f"当前值 '{rating}' 无效。"
            ),
        })

    # ---- C5：来源数量 ----
    sources = report.get("sources", [])
    if not isinstance(sources, list) or len(sources) < MIN_SOURCES:
        errors.append({
            "type": "insufficient_sources",
            "detail": (
                f"sources 数量 {len(sources) if isinstance(sources, list) else 0}，"
                f"要求至少 {MIN_SOURCES} 个"
            ),
            "fix": (
                f"在 sources 列表中添加至少 {MIN_SOURCES} 个数据来源。"
                f"来源可以是新闻链接、研报链接或数据平台名称。"
            ),
        })

    # ---- C6：风险因素不能为空 ----
    risk_factors = report.get("risk_factors", [])
    if not isinstance(risk_factors, list) or len(risk_factors) == 0:
        errors.append({
            "type": "empty_risk_factors",
            "detail": "risk_factors 为空或缺失",
            "fix": (
                "在 risk_factors 列表中至少添加1个风险因素。"
                "任何投资都存在风险，空列表说明分析不完整。"
            ),
        })

    # ---- C7：investment_thesis 最小长度 ----
    thesis = report.get("investment_thesis", "")
    if not thesis:
        errors.append({
            "type": "thesis_too_short",
            "detail": "缺少 investment_thesis 字段",
            "fix": (
                f"添加 investment_thesis 字段，内容不少于 {MIN_THESIS_LENGTH} 字符。"
                f"这是深思熟虑路径经过多方案推理后的核心投资逻辑。"
            ),
        })
    elif len(thesis) < MIN_THESIS_LENGTH:
        errors.append({
            "type": "thesis_too_short",
            "detail": (
                f"investment_thesis 长度 {len(thesis)} 字符，"
                f"要求至少 {MIN_THESIS_LENGTH}"
            ),
            "fix": (
                f"扩充 investment_thesis 内容，至少 {MIN_THESIS_LENGTH} 个字符，"
                f"说明选择该投资方案的核心逻辑和依据。"
            ),
        })

    return errors
