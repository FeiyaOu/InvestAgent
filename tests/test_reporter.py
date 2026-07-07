# -*- coding: utf-8 -*-
"""
报告校验测试 — C1–C7

每个测试类直接对应 spec/invest_spec.md 中的一条约束。
这是 SDD → TDD 的体现：Spec 约束直接转化为测试用例。

测试类命名规则：TestC<编号><约束名称>
"""

from __future__ import annotations

import pytest

from src.stages.reporter import (
    MIN_SOURCES,
    MIN_SUMMARY_LENGTH,
    MIN_THESIS_LENGTH,
    REQUIRED_DIMENSIONS,
    VALID_RATINGS,
    validate_report,
)
from tests.conftest import make_valid_report


# ============================================================
# C1：维度完整性 — 报告必须包含全部4个维度
# ============================================================

class TestC1DimensionCompleteness:

    def test_valid_report_passes(self, valid_report: dict) -> None:
        """合规报告应通过 C1 校验"""
        errors = validate_report(valid_report)
        dim_errors = [e for e in errors if e["type"] == "missing_dimension"]
        assert len(dim_errors) == 0

    def test_missing_one_dimension_fails(self, valid_report: dict) -> None:
        """缺少一个维度应报出1个 missing_dimension 错误"""
        del valid_report["dimensions"]["market"]
        errors = validate_report(valid_report)
        dim_errors = [e for e in errors if e["type"] == "missing_dimension"]
        assert len(dim_errors) == 1
        assert "market" in dim_errors[0]["detail"]

    def test_missing_all_dimensions_fails(self) -> None:
        """dimensions 为空字典应报出4个 missing_dimension 错误"""
        report = make_valid_report()
        report["dimensions"] = {}
        errors = validate_report(report)
        dim_errors = [e for e in errors if e["type"] == "missing_dimension"]
        assert len(dim_errors) == len(REQUIRED_DIMENSIONS)

    def test_no_dimensions_key_fails(self) -> None:
        """缺少 dimensions 键应报出全部4个缺失错误"""
        report = make_valid_report()
        del report["dimensions"]
        errors = validate_report(report)
        dim_errors = [e for e in errors if e["type"] == "missing_dimension"]
        assert len(dim_errors) == len(REQUIRED_DIMENSIONS)

    def test_error_contains_fix_instruction(self, valid_report: dict) -> None:
        """错误信息应包含 fix 字段，供 Agent 自我纠正"""
        del valid_report["dimensions"]["analyst"]
        errors = validate_report(valid_report)
        dim_errors = [e for e in errors if e["type"] == "missing_dimension"]
        assert dim_errors[0].get("fix"), "错误应包含 fix 修复指令"


# ============================================================
# C2：摘要最小长度 — 每个维度 summary >= 100 字符
# ============================================================

class TestC2SummaryLength:

    def test_short_summary_fails(self, valid_report: dict) -> None:
        """过短的摘要应报出 summary_too_short 错误"""
        valid_report["dimensions"]["fundamental"]["summary"] = "太短了"
        errors = validate_report(valid_report)
        short_errors = [e for e in errors if e["type"] == "summary_too_short"]
        assert len(short_errors) == 1
        assert "fundamental" in short_errors[0]["detail"]

    def test_exactly_min_length_passes(self, valid_report: dict) -> None:
        """恰好等于最小长度应通过"""
        valid_report["dimensions"]["fundamental"]["summary"] = "x" * MIN_SUMMARY_LENGTH
        errors = validate_report(valid_report)
        short_errors = [e for e in errors if e["type"] == "summary_too_short"]
        assert len(short_errors) == 0

    def test_all_dimensions_short_summary(self) -> None:
        """4个维度都过短应报4个错误"""
        report = make_valid_report()
        for dim in REQUIRED_DIMENSIONS:
            report["dimensions"][dim]["summary"] = "短"
        errors = validate_report(report)
        short_errors = [e for e in errors if e["type"] == "summary_too_short"]
        assert len(short_errors) == len(REQUIRED_DIMENSIONS)

    def test_empty_summary_fails(self, valid_report: dict) -> None:
        """空摘要应报错"""
        valid_report["dimensions"]["news"]["summary"] = ""
        errors = validate_report(valid_report)
        short_errors = [e for e in errors if e["type"] == "summary_too_short"]
        assert len(short_errors) == 1


# ============================================================
# C3：置信度范围 — confidence 在 [0.0, 1.0]
# ============================================================

class TestC3ConfidenceRange:

    def test_confidence_above_one_fails(self, valid_report: dict) -> None:
        """confidence > 1.0 应报错"""
        valid_report["dimensions"]["market"]["confidence"] = 1.1
        errors = validate_report(valid_report)
        conf_errors = [e for e in errors if e["type"] == "confidence_out_of_range"]
        assert len(conf_errors) == 1

    def test_confidence_below_zero_fails(self, valid_report: dict) -> None:
        """confidence < 0.0 应报错"""
        valid_report["dimensions"]["analyst"]["confidence"] = -0.1
        errors = validate_report(valid_report)
        conf_errors = [e for e in errors if e["type"] == "confidence_out_of_range"]
        assert len(conf_errors) == 1

    def test_confidence_exactly_zero_passes(self, valid_report: dict) -> None:
        """confidence = 0.0 应通过"""
        valid_report["dimensions"]["fundamental"]["confidence"] = 0.0
        errors = validate_report(valid_report)
        conf_errors = [e for e in errors if e["type"] == "confidence_out_of_range"]
        assert len(conf_errors) == 0

    def test_confidence_exactly_one_passes(self, valid_report: dict) -> None:
        """confidence = 1.0 应通过"""
        valid_report["dimensions"]["fundamental"]["confidence"] = 1.0
        errors = validate_report(valid_report)
        conf_errors = [e for e in errors if e["type"] == "confidence_out_of_range"]
        assert len(conf_errors) == 0

    def test_missing_confidence_fails(self, valid_report: dict) -> None:
        """缺少 confidence 字段应报 missing_confidence 错误"""
        del valid_report["dimensions"]["news"]["confidence"]
        errors = validate_report(valid_report)
        missing_errors = [e for e in errors if e["type"] == "missing_confidence"]
        assert len(missing_errors) == 1


# ============================================================
# C4：评级有效值 — overall_rating 只能是 buy/hold/sell
# ============================================================

class TestC4RatingValidValue:

    @pytest.mark.parametrize("rating", ["buy", "hold", "sell"])
    def test_valid_ratings_pass(self, valid_report: dict, rating: str) -> None:
        """buy / hold / sell 均应通过"""
        valid_report["overall_rating"] = rating
        errors = validate_report(valid_report)
        rating_errors = [e for e in errors if e["type"] == "invalid_rating"]
        assert len(rating_errors) == 0

    @pytest.mark.parametrize("bad_rating", ["strong_buy", "neutral", "outperform", "", "BUY"])
    def test_invalid_rating_fails(self, valid_report: dict, bad_rating: str) -> None:
        """非法评级应报 invalid_rating 错误"""
        valid_report["overall_rating"] = bad_rating
        errors = validate_report(valid_report)
        rating_errors = [e for e in errors if e["type"] == "invalid_rating"]
        assert len(rating_errors) == 1

    def test_missing_rating_fails(self, valid_report: dict) -> None:
        """缺少 overall_rating 字段应报错"""
        del valid_report["overall_rating"]
        errors = validate_report(valid_report)
        rating_errors = [e for e in errors if e["type"] == "invalid_rating"]
        assert len(rating_errors) == 1


# ============================================================
# C5：来源数量 — sources >= 3 个
# ============================================================

class TestC5SourceCount:

    def test_exactly_three_sources_passes(self, valid_report: dict) -> None:
        """恰好3个来源应通过"""
        valid_report["sources"] = ["s1", "s2", "s3"]
        errors = validate_report(valid_report)
        source_errors = [e for e in errors if e["type"] == "insufficient_sources"]
        assert len(source_errors) == 0

    def test_two_sources_fails(self, valid_report: dict) -> None:
        """2个来源应报 insufficient_sources 错误"""
        valid_report["sources"] = ["s1", "s2"]
        errors = validate_report(valid_report)
        source_errors = [e for e in errors if e["type"] == "insufficient_sources"]
        assert len(source_errors) == 1

    def test_empty_sources_fails(self, valid_report: dict) -> None:
        """空来源列表应报错"""
        valid_report["sources"] = []
        errors = validate_report(valid_report)
        source_errors = [e for e in errors if e["type"] == "insufficient_sources"]
        assert len(source_errors) == 1

    def test_missing_sources_key_fails(self, valid_report: dict) -> None:
        """缺少 sources 键应报错"""
        del valid_report["sources"]
        errors = validate_report(valid_report)
        source_errors = [e for e in errors if e["type"] == "insufficient_sources"]
        assert len(source_errors) == 1

    def test_more_than_min_passes(self, valid_report: dict) -> None:
        """超过最小数量应通过"""
        valid_report["sources"] = ["s1", "s2", "s3", "s4", "s5"]
        errors = validate_report(valid_report)
        source_errors = [e for e in errors if e["type"] == "insufficient_sources"]
        assert len(source_errors) == 0


# ============================================================
# C6：风险因素 — risk_factors 不能为空
# ============================================================

class TestC6RiskFactors:

    def test_nonempty_risk_factors_passes(self, valid_report: dict) -> None:
        """非空 risk_factors 应通过"""
        valid_report["risk_factors"] = ["政策风险", "市场风险"]
        errors = validate_report(valid_report)
        risk_errors = [e for e in errors if e["type"] == "empty_risk_factors"]
        assert len(risk_errors) == 0

    def test_empty_risk_factors_fails(self, valid_report: dict) -> None:
        """空列表应报 empty_risk_factors 错误"""
        valid_report["risk_factors"] = []
        errors = validate_report(valid_report)
        risk_errors = [e for e in errors if e["type"] == "empty_risk_factors"]
        assert len(risk_errors) == 1

    def test_missing_risk_factors_key_fails(self, valid_report: dict) -> None:
        """缺少 risk_factors 键应报错"""
        del valid_report["risk_factors"]
        errors = validate_report(valid_report)
        risk_errors = [e for e in errors if e["type"] == "empty_risk_factors"]
        assert len(risk_errors) == 1


# ============================================================
# C7：investment_thesis — 不少于50字符（深思熟虑核心产出）
# ============================================================

class TestC7InvestmentThesis:

    def test_sufficient_thesis_passes(self, valid_report: dict) -> None:
        """长度 >= 50 字符的 thesis 应通过"""
        errors = validate_report(valid_report)
        thesis_errors = [e for e in errors if e["type"] == "thesis_too_short"]
        assert len(thesis_errors) == 0

    def test_short_thesis_fails(self, valid_report: dict) -> None:
        """过短的 thesis 应报 thesis_too_short 错误"""
        valid_report["investment_thesis"] = "短论点"
        errors = validate_report(valid_report)
        thesis_errors = [e for e in errors if e["type"] == "thesis_too_short"]
        assert len(thesis_errors) == 1

    def test_exactly_min_length_passes(self, valid_report: dict) -> None:
        """恰好等于最小长度应通过"""
        valid_report["investment_thesis"] = "x" * MIN_THESIS_LENGTH
        errors = validate_report(valid_report)
        thesis_errors = [e for e in errors if e["type"] == "thesis_too_short"]
        assert len(thesis_errors) == 0

    def test_missing_thesis_fails(self, valid_report: dict) -> None:
        """缺少 investment_thesis 键应报错"""
        del valid_report["investment_thesis"]
        errors = validate_report(valid_report)
        thesis_errors = [e for e in errors if e["type"] == "thesis_too_short"]
        assert len(thesis_errors) == 1

    def test_empty_thesis_fails(self, valid_report: dict) -> None:
        """空字符串 thesis 应报错"""
        valid_report["investment_thesis"] = ""
        errors = validate_report(valid_report)
        thesis_errors = [e for e in errors if e["type"] == "thesis_too_short"]
        assert len(thesis_errors) == 1
