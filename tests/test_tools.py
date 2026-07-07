# -*- coding: utf-8 -*-
"""
工具函数测试

测试策略：
- 所有单元测试使用 USE_REAL_DATA=false，零网络依赖
- 测试 AKShare 异常时的 fallback 行为（mock AKShare 抛出异常）
- 验证工具已正确注册为 LangChain tool（有 name 和 description）
- 不测试 AKShare 真实 API（属于集成测试范畴）
"""

from __future__ import annotations

import pytest

from src.tools import (
    INVEST_TOOLS,
    get_index_performance,
    get_macro_indicators,
    get_sector_performance,
    search_stock_news,
)


# ---- fixture：强制使用 mock 数据模式 ----

@pytest.fixture(autouse=True)
def mock_data_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有工具测试默认使用 mock 数据，不调用真实 AKShare"""
    monkeypatch.setenv("USE_REAL_DATA", "false")


# ============================================================
# 工具注册验证 — 确保 @tool 装饰器生效
# ============================================================

class TestToolRegistration:

    def test_all_tools_in_invest_tools_list(self) -> None:
        """INVEST_TOOLS 列表应包含全部5个工具"""
        assert len(INVEST_TOOLS) == 5

    def test_each_tool_has_name(self) -> None:
        """每个工具应有 name 属性（LangChain tool 必须项）"""
        for t in INVEST_TOOLS:
            assert hasattr(t, "name"), f"{t} 缺少 name 属性"
            assert t.name, f"{t} 的 name 不能为空"

    def test_each_tool_has_description(self) -> None:
        """每个工具应有 description 属性（LLM 决定是否调用工具的依据）"""
        for t in INVEST_TOOLS:
            assert hasattr(t, "description"), f"{t.name} 缺少 description"
            assert len(t.description) > 10, f"{t.name} 的 description 太短"

    def test_tool_names_are_correct(self) -> None:
        """工具名称应与函数名一致"""
        names = {t.name for t in INVEST_TOOLS}
        assert "get_sector_performance" in names
        assert "get_index_performance" in names
        assert "get_macro_indicators" in names
        assert "search_stock_news" in names
        assert "get_stock_performance" in names


# ============================================================
# get_sector_performance
# ============================================================

class TestGetSectorPerformance:

    def test_returns_string(self) -> None:
        """工具调用应返回字符串"""
        result = get_sector_performance.invoke({"sector": "新能源"})
        assert isinstance(result, str)

    def test_mock_result_contains_sector_name(self) -> None:
        """mock 模式下返回结果应包含行业名称"""
        result = get_sector_performance.invoke({"sector": "光伏"})
        assert "光伏" in result

    def test_mock_result_is_nonempty(self) -> None:
        """mock 模式下不应返回空字符串"""
        result = get_sector_performance.invoke({"sector": "半导体"})
        assert len(result) > 0

    def test_akshare_exception_returns_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AKShare 抛出异常时应返回 fallback 文本而非崩溃"""
        monkeypatch.setenv("USE_REAL_DATA", "true")

        import unittest.mock as mock
        with mock.patch.dict("sys.modules", {"akshare": mock.MagicMock(
            stock_board_industry_summary_ths=mock.MagicMock(side_effect=ConnectionError("网络超时"))
        )}):
            result = get_sector_performance.invoke({"sector": "新能源"})
            assert isinstance(result, str)
            assert len(result) > 0
            # fallback 文本应包含提示而非抛出异常
            assert "无法获取" in result or "新能源" in result


# ============================================================
# get_index_performance
# ============================================================

class TestGetIndexPerformance:

    def test_returns_string(self) -> None:
        """工具调用应返回字符串"""
        result = get_index_performance.invoke({})
        assert isinstance(result, str)

    def test_mock_result_contains_index_name(self) -> None:
        """mock 模式下应包含上证指数"""
        result = get_index_performance.invoke({})
        assert "上证" in result

    def test_mock_result_is_nonempty(self) -> None:
        """mock 模式下不应返回空字符串"""
        result = get_index_performance.invoke({})
        assert len(result) > 0

    def test_akshare_exception_returns_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AKShare 抛出异常时应返回 fallback"""
        monkeypatch.setenv("USE_REAL_DATA", "true")

        import unittest.mock as mock
        with mock.patch.dict("sys.modules", {"akshare": mock.MagicMock(
            index_zh_a_hist=mock.MagicMock(side_effect=RuntimeError("接口不可用"))
        )}):
            result = get_index_performance.invoke({})
            assert isinstance(result, str)
            assert len(result) > 0


# ============================================================
# get_macro_indicators
# ============================================================

class TestGetMacroIndicators:

    def test_returns_string(self) -> None:
        """工具调用应返回字符串"""
        result = get_macro_indicators.invoke({})
        assert isinstance(result, str)

    def test_mock_result_contains_pmi(self) -> None:
        """mock 模式下应包含 PMI 数据"""
        result = get_macro_indicators.invoke({})
        assert "PMI" in result

    def test_mock_result_is_nonempty(self) -> None:
        """mock 模式下不应返回空字符串"""
        result = get_macro_indicators.invoke({})
        assert len(result) > 0

    def test_akshare_exception_returns_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AKShare 抛出异常时应返回 fallback"""
        monkeypatch.setenv("USE_REAL_DATA", "true")

        import unittest.mock as mock
        with mock.patch.dict("sys.modules", {"akshare": mock.MagicMock(
            macro_china_pmi_yearly=mock.MagicMock(side_effect=TimeoutError("请求超时"))
        )}):
            result = get_macro_indicators.invoke({})
            assert isinstance(result, str)
            assert len(result) > 0


# ============================================================
# search_stock_news
# ============================================================

class TestSearchStockNews:

    def test_returns_string(self) -> None:
        """工具调用应返回字符串"""
        result = search_stock_news.invoke({"keyword": "新能源"})
        assert isinstance(result, str)

    def test_mock_result_contains_keyword(self) -> None:
        """mock 模式下返回结果应包含关键词"""
        result = search_stock_news.invoke({"keyword": "碳中和"})
        assert "碳中和" in result

    def test_mock_result_has_multiple_items(self) -> None:
        """mock 模式下应返回多条新闻"""
        result = search_stock_news.invoke({"keyword": "光伏"})
        # 至少有2行内容（标题换行）
        assert result.count("\n") >= 1

    def test_akshare_exception_returns_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AKShare 抛出异常时应返回 fallback"""
        monkeypatch.setenv("USE_REAL_DATA", "true")

        import unittest.mock as mock
        with mock.patch.dict("sys.modules", {"akshare": mock.MagicMock(
            stock_news_em=mock.MagicMock(side_effect=Exception("数据源不可用"))
        )}):
            result = search_stock_news.invoke({"keyword": "新能源"})
            assert isinstance(result, str)
            assert len(result) > 0
