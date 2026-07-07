# -*- coding: utf-8 -*-
"""
AKShare 市场数据工具

所有工具通过 @tool 装饰器注册为 LangChain 工具，供 LangGraph ToolNode 使用。

设计原则：
- AKShare 调用全部封装在本模块，stage 模块不直接调用 AKShare
- 每个工具都有 try/except fallback，网络异常不得导致 Agent 崩溃
- USE_REAL_DATA 环境变量控制数据模式（每次调用时重新读取，支持测试覆盖）
"""

from __future__ import annotations

import os

from langchain_core.tools import tool


def _should_use_real_data() -> bool:
    """读取运行时环境变量。每次工具调用时重新读取，确保 monkeypatch 在测试中生效。"""
    return os.getenv("USE_REAL_DATA", "true").lower() == "true"


# ============================================================
# 工具 1：行业板块表现
# ============================================================

@tool
def get_sector_performance(sector: str) -> str:
    """查询指定行业板块的近期市场表现，包括涨跌幅、成交额和主力净流入。

    Args:
        sector: 行业板块名称，如"新能源"、"光伏"、"半导体"、"消费"、"医药"
    """
    if not _should_use_real_data():
        return (
            f"{sector} 板块（模拟数据）："
            f"涨跌幅 +2.31%，成交额 1,243亿元，主力净流入 +32.1亿元，"
            f"领涨个股：隆基绿能 +4.2%，通威股份 +3.8%"
        )

    try:
        import akshare as ak  # 懒导入，避免未安装时模块加载失败

        df = ak.stock_board_industry_summary_ths()
        matched = df[df["板块名称"].str.contains(sector, na=False)]
        if matched.empty:
            return f"未找到与 '{sector}' 相关的板块，请尝试更通用的行业名称（如'新能源'而非'光伏组件'）。"
        row = matched.iloc[0]
        return (
            f"{row.get('板块名称', sector)}："
            f"涨跌幅 {row.get('涨跌幅', 'N/A')}%，"
            f"成交额 {row.get('成交额', 'N/A')}，"
            f"主力净流入 {row.get('主力净流入', 'N/A')}"
        )
    except Exception as e:
        return (
            f"{sector} 板块实时数据暂时无法获取（{type(e).__name__}），"
            f"请基于已有市场信息进行分析。"
        )


# ============================================================
# 工具 2：主要指数行情
# ============================================================

@tool
def get_index_performance() -> str:
    """查询A股主要指数（上证指数、创业板指、沪深300）的最新行情和近期走势。"""
    if not _should_use_real_data():
        return (
            "主要指数行情（模拟数据）："
            "上证指数 3,125.62（+0.32%）| "
            "创业板指 1,923.41（+0.89%）| "
            "沪深300 3,456.78（+0.45%）| "
            "近5日趋势：震荡上行，成交量温和放大"
        )

    try:
        import akshare as ak
        from datetime import date, timedelta

        end = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=7)).strftime("%Y%m%d")

        sh = ak.index_zh_a_hist(symbol="000001", period="daily", start_date=start, end_date=end)
        sz = ak.index_zh_a_hist(symbol="399006", period="daily", start_date=start, end_date=end)

        def _fmt(df: object, name: str) -> str:
            if df is None or len(df) == 0:
                return f"{name} 数据不可用"
            latest = df.iloc[-1]
            close = latest.get("收盘", "N/A")
            pct = latest.get("涨跌幅", "N/A")
            return f"{name} {close}（{pct}%）"

        return " | ".join([_fmt(sh, "上证指数"), _fmt(sz, "创业板指")])

    except Exception as e:
        return (
            f"指数行情实时数据暂时无法获取（{type(e).__name__}），"
            f"请基于已有市场信息进行分析。"
        )


# ============================================================
# 工具 3：宏观经济指标
# ============================================================

@tool
def get_macro_indicators() -> str:
    """获取中国最新宏观经济指标，包括制造业PMI、GDP增速、CPI、PPI等关键数据。"""
    if not _should_use_real_data():
        return (
            "宏观经济指标（模拟数据）："
            "制造业PMI 50.3（扩张区间）| "
            "GDP增速 5.1%（年同比）| "
            "CPI +0.3%（温和通胀）| "
            "PPI -0.8%（工业品价格偏弱）| "
            "LPR 3.45%（维持不变）"
        )

    try:
        import akshare as ak

        pmi_df = ak.macro_china_pmi_yearly()
        if pmi_df is None or len(pmi_df) == 0:
            return "宏观PMI数据暂时不可用，请基于已有信息进行分析。"
        latest = pmi_df.iloc[-1]
        mfg = latest.get("制造业", "N/A")
        non_mfg = latest.get("非制造业", "N/A")
        period = latest.get("月份", "最新")
        return (
            f"宏观PMI数据（{period}）："
            f"制造业PMI {mfg}（{'扩张' if str(mfg) >= '50' else '收缩'}区间）| "
            f"非制造业PMI {non_mfg}"
        )
    except Exception as e:
        return (
            f"宏观数据暂时无法获取（{type(e).__name__}），"
            f"请基于已有信息进行分析。"
        )


# ============================================================
# 工具 4：市场新闻搜索
# ============================================================

@tool
def search_stock_news(keyword: str) -> str:
    """搜索与关键词相关的近期市场新闻和公告。

    Args:
        keyword: 搜索关键词，如"新能源"、"光伏补贴"、"碳中和政策"
    """
    if not _should_use_real_data():
        return (
            f"'{keyword}' 相关新闻（模拟数据）：\n"
            f"1. 国家能源局发布{keyword}产业发展指导意见，明确2025年装机目标\n"
            f"2. 多家头部企业发布{keyword}相关季报，业绩超市场预期\n"
            f"3. 机构研报：{keyword}行业进入景气上行周期，建议超配"
        )

    try:
        import akshare as ak

        # 使用财联社新闻接口搜索相关新闻
        df = ak.stock_news_em(stock=keyword)
        if df is None or len(df) == 0:
            return f"未找到与 '{keyword}' 相关的近期新闻。"

        # 取最新5条
        recent = df.head(5)
        news_list = []
        for i, row in recent.iterrows():
            title = row.get("新闻标题", row.get("title", "无标题"))
            news_list.append(f"{len(news_list) + 1}. {title}")

        return f"'{keyword}' 近期相关新闻：\n" + "\n".join(news_list)

    except Exception as e:
        return (
            f"'{keyword}' 新闻数据暂时无法获取（{type(e).__name__}），"
            f"请基于已有信息进行分析。"
        )


# ============================================================
# 常用股票名称→代码映射（避免依赖 stock_zh_a_spot_em 实时查询）
# ============================================================

_STOCK_NAME_TO_CODE = {
    # 消费
    "贵州茅台": "600519", "茅台": "600519",
    "五粮液": "000858",
    "洋河股份": "002304",
    "海天味业": "603288",
    "伊利股份": "600887",
    "美的集团": "000333",
    "格力电器": "000651",
    "海尔智家": "600690",
    # 新能源 / 科技
    "宁德时代": "300750",
    "比亚迪":   "002594",
    "隆基绿能": "601012",
    "通威股份": "600438",
    "阳光电源": "300274",
    "晶澳科技": "002459",
    "中芯国际": "688981",
    "韦尔股份": "603501",
    "汇川技术": "300124",
    # 金融
    "中国平安": "601318",
    "招商银行": "600036",
    "兴业银行": "601166",
    "中信证券": "600030",
    "东方财富": "300059",
    # 医药
    "恒瑞医药": "600276",
    "药明康德": "603259",
    "迈瑞医疗": "300760",
    # 互联网 / 通信
    "中国移动": "600941",
    "中国联通": "600050",
    "三六零":   "601360",
    # 港股（供参考）
    "腾讯":     "00700",
    "阿里巴巴": "09988",
    "美团":     "03690",
}


def _resolve_stock_code(query: str) -> str | None:
    """从名称或代码中解析出股票代码"""
    query = query.strip()
    # 已是代码格式
    if query.isdigit() and len(query) == 6:
        return query
    # 名称查表
    for name, code in _STOCK_NAME_TO_CODE.items():
        if name in query or query in name:
            return code
    return None


# ============================================================
# 工具 5：个股历史表现（新增）
# ============================================================

@tool
def get_stock_performance(query: str) -> str:
    """查询指定股票最近一个月的价格表现和涨跌情况。

    Args:
        query: 股票名称或代码，如"贵州茅台"、"600519"、"宁德时代"
    """
    if not _should_use_real_data():
        return (
            f"{query}（模拟数据）：近一个月涨跌幅 +8.3%，"
            f"最新收盘价 1,680元，成交量较前月增加12%，"
            f"机构持仓比例上升至45.2%"
        )

    code = _resolve_stock_code(query)
    if not code:
        return f"未能识别股票 '{query}'，请使用股票代码（如600519）或以下常用名称：{list(_STOCK_NAME_TO_CODE.keys())[:5]}"

    try:
        import akshare as ak
        from datetime import date, timedelta

        end = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=30)).strftime("%Y%m%d")

        df = ak.stock_zh_a_hist(
            symbol=code, period="daily",
            start_date=start, end_date=end, adjust="qfq"
        )
        if df is None or len(df) == 0:
            return f"{query}（{code}）近期无交易数据，可能为停牌状态。"

        first_close = df.iloc[0]["收盘"]
        last_close = df.iloc[-1]["收盘"]
        pct = round((last_close - first_close) / first_close * 100, 2)
        high = df["最高"].max()
        low = df["最低"].min()
        avg_vol = df["成交量"].mean()

        direction = "+" if pct >= 0 else ""
        return (
            f"{query}（{code}）近30日表现：\n"
            f"涨跌幅 {direction}{pct}%，"
            f"最新收盘 {last_close:.2f}元，"
            f"区间最高 {high:.2f}元，区间最低 {low:.2f}元，"
            f"日均成交量 {avg_vol:.0f}手"
        )

    except Exception as e:
        return (
            f"{query} 近期数据暂时无法获取（{type(e).__name__}），"
            f"请稍后重试或使用模拟数据模式。"
        )


# ============================================================
# 工具列表（供 agent.py 的 ToolNode 使用）
# ============================================================

INVEST_TOOLS = [
    get_sector_performance,
    get_index_performance,
    get_macro_indicators,
    search_stock_news,
    get_stock_performance,   # 新增：个股表现查询
]
