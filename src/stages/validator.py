# -*- coding: utf-8 -*-
"""
校验节点（Validator）
角色：独立合规审查员

职责：
- 独立校验报告是否满足 C1–C7（调用 validate_report()）
- 不知道其他节点的决策过程，只看最终报告
- 校验不通过时触发有向环②：路由回 decision 阶段重新生成
- retry_count 防止无限循环，上限 MAX_VALIDATOR_RETRIES
"""

from __future__ import annotations

import json

from src.stages.reporter import validate_report
from src.state import MAX_VALIDATOR_RETRIES, InvestAgentState


def validator(state: InvestAgentState) -> dict:
    """校验节点函数：独立审查员校验报告是否满足 C1–C7"""
    print("[校验] 独立合规审查员检查报告...")

    retry_count = state.get("retry_count", 0)
    final_report_str = state.get("final_report", "")

    # 解析报告
    if not final_report_str:
        print("[校验] 报告为空，触发重试")
        return {
            "validation_errors": [{"type": "empty_report", "detail": "final_report 为空", "fix": "重新生成报告"}],
            "retry_count": retry_count + 1,
            "current_phase": "validator",
        }

    try:
        report = json.loads(final_report_str) if isinstance(final_report_str, str) else final_report_str
    except json.JSONDecodeError as e:
        return {
            "validation_errors": [{"type": "invalid_json", "detail": str(e), "fix": "确保报告是合法 JSON"}],
            "retry_count": retry_count + 1,
            "current_phase": "validator",
        }

    # 执行 C1–C7 校验
    errors = validate_report(report)

    if not errors:
        print("[校验] 通过 ✓ 报告满足 C1–C7 全部约束")
        return {
            "validation_errors": [],
            "current_phase": "completed",
            "error": None,
        }

    # 区分关键错误（触发重试）和质量警告（接受，仅记录）
    # 关键错误：报告结构缺失或评级非法，不可接受
    CRITICAL_ERROR_TYPES = {"missing_dimension", "invalid_rating", "empty_report", "invalid_json"}
    critical_errors = [e for e in errors if e["type"] in CRITICAL_ERROR_TYPES]
    quality_warnings = [e for e in errors if e["type"] not in CRITICAL_ERROR_TYPES]

    if quality_warnings and not critical_errors:
        # 只有质量警告，无结构性错误 → 接受报告，记录警告
        warn_types = [e["type"] for e in quality_warnings]
        print(f"[校验] 带警告完成 ⚠️ 质量问题（不重试）: {warn_types}")
        return {
            "validation_errors": quality_warnings,
            "current_phase": "completed",
            "error": None,
        }

    # 存在关键错误
    print(f"[校验] 发现 {len(critical_errors)} 个关键问题: {[e['type'] for e in critical_errors]}")

    if retry_count >= MAX_VALIDATOR_RETRIES:
        print(f"[校验] 已达最大重试次数 {MAX_VALIDATOR_RETRIES}，带关键错误完成")
        return {
            "validation_errors": errors,
            "current_phase": "completed",
            "error": f"报告存在关键错误（已重试{retry_count}次）: {[e['type'] for e in critical_errors]}",
        }

    # 触发有向环②：回到 decision 阶段重新生成
    print(f"[校验] 触发重试 #{retry_count + 1}，关键错误: {[e['type'] for e in critical_errors]}")
    return {
        "validation_errors": errors,
        "retry_count": retry_count + 1,
        "current_phase": "decision",
        "error": None,
    }
