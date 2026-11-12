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
from typing import Literal

from langchain_core.runnables import RunnableConfig

from langchain_core.tools import tool

# 环境变量名（单一真源，UI / 测试 / 工具层共用，避免各处硬编码字符串拼错）
USE_REAL_DATA_ENV = "USE_REAL_DATA"

# 认定为"真"的取值（大小写不敏感）。历史上只认 "true"，
# 导致 .env 写成 True / 1 / yes、或值后面带行尾注释时，工具静默退回 mock 数据。
_TRUTHY = {"true", "1", "yes", "y", "on"}
_FALSY = {"false", "0", "no", "n", "off"}


def parse_bool(raw: str | None, default: bool = True) -> bool:
    """宽松解析布尔环境变量：容忍空白、引号、行尾注释、以及 1/yes/on 等写法。"""
    if raw is None:
        return default
    value = raw.split("#", 1)[0].strip().strip("\"'").lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    return default


def _should_use_real_data() -> bool:
    """读取运行时环境变量。每次工具调用时重新读取，确保 monkeypatch 在测试中生效。"""
    return parse_bool(os.getenv(USE_REAL_DATA_ENV), default=True)


def set_use_real_data(enabled: bool) -> None:
    """显式设置数据模式（供 Streamlit toggle 调用），保证写入的字面量能被 parse_bool 识别。"""
    os.environ[USE_REAL_DATA_ENV] = "true" if enabled else "false"


def data_mode() -> str:
    """返回当前生效的数据模式：'real' 或 'mock'。UI 用它回显真实状态，而不是回显自己的变量。"""
    return "real" if _should_use_real_data() else "mock"


def akshare_available() -> tuple[bool, str]:
    """检查 akshare 是否可导入。返回 (是否可用, 版本号或错误信息)。"""
    try:
        import akshare as ak

        return True, getattr(ak, "__version__", "unknown")
    except Exception as e:  # pragma: no cover - 取决于运行环境
        return False, f"{type(e).__name__}: {e}"


# ============================================================
# 行业板块同义词表
#
# 同花顺行业板块用的是"光伏设备""电池"这类细分名称，
# 用户/LLM 传进来的却常是"新能源""科技"这类主题词，
# 直接 contains 匹配会一个都命中不了 → 真实数据模式下永远返回"未找到"。
# ============================================================

_SECTOR_ALIASES: dict[str, list[str]] = {
    "新能源":   ["光伏设备", "电池", "风电设备", "能源金属", "电网设备", "其他电源设备"],
    "光伏":     ["光伏设备"],
    "锂电":     ["电池", "能源金属"],
    "储能":     ["电池", "其他电源设备", "电网设备"],
    "风电":     ["风电设备"],
    "新能源车": ["汽车整车", "汽车零部件", "电池"],
    "汽车":     ["汽车整车", "汽车零部件", "汽车服务及其他"],
    "科技":     ["半导体", "消费电子", "软件开发", "计算机设备", "光学光电子"],
    "芯片":     ["半导体", "元件", "电子化学品"],
    "半导体":   ["半导体", "元件"],
    "人工智能": ["软件开发", "IT服务", "计算机设备", "半导体"],
    "AI":       ["软件开发", "IT服务", "计算机设备", "半导体"],
    "消费":     ["白酒", "饮料制造", "食品加工制造", "零售", "美容护理", "家居用品"],
    "白酒":     ["白酒"],
    "食品":     ["食品加工制造", "饮料制造"],
    "家电":     ["白色家电", "小家电", "黑色家电", "厨卫电器"],
    "医药":     ["化学制药", "中药", "生物制品", "医疗器械", "医疗服务", "医药商业"],
    "生物医药": ["生物制品", "化学制药", "医疗服务"],
    "军工":     ["军工装备", "军工电子"],
    "金融":     ["银行", "证券", "保险", "多元金融"],
    "券商":     ["证券"],
    "地产":     ["房地产", "建筑装饰", "建筑材料"],
    "房地产":   ["房地产"],
    "周期":     ["煤炭开采加工", "钢铁", "工业金属", "化学原料", "石油加工贸易"],
    "有色":     ["工业金属", "小金属", "贵金属", "金属新材料", "能源金属"],
    "煤炭":     ["煤炭开采加工"],
    "化工":     ["化学原料", "化学制品", "化学纤维", "农化制品"],
    "传媒":     ["文化传媒", "影视院线", "游戏", "互联网电商"],
    "农业":     ["种植业与林业", "养殖业", "农产品加工", "农化制品"],
}


def _match_boards(df: object, sector: str) -> object:
    """在板块汇总表里按 精确名 → 子串 → 同义词 三级匹配，返回匹配到的行。"""
    sector = sector.strip()
    names = df["板块"]

    exact = df[names == sector]
    if not exact.empty:
        return exact

    # 双向子串："光伏" 命中 "光伏设备"；"光伏组件" 也能命中 "光伏设备"
    substr = df[names.apply(lambda n: sector in str(n) or str(n) in sector)]
    if not substr.empty:
        return substr

    for alias, boards in _SECTOR_ALIASES.items():
        if alias in sector or sector in alias:
            aliased = df[names.isin(boards)]
            if not aliased.empty:
                return aliased

    return df.iloc[0:0]  # 空 DataFrame，保留列结构


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

        # 同花顺行业板块实时汇总。真实列名为
        # ['序号','板块','涨跌幅','总成交量','总成交额','净流入','上涨家数','下跌家数','均价','领涨股',...]
        df = ak.stock_board_industry_summary_ths()
        matched = _match_boards(df, sector)
        if matched.empty:
            return (
                f"未找到与 '{sector}' 对应的行业板块。"
                f"可用板块示例：{'、'.join(df['板块'].head(8).tolist())} 等 {len(df)} 个。"
            )

        lines = []
        for _, row in matched.head(4).iterrows():
            lines.append(
                f"- {row['板块']}："
                f"涨跌幅 {row.get('涨跌幅', 'N/A')}%，"
                f"总成交额 {row.get('总成交额', 'N/A')}亿元，"
                f"净流入 {row.get('净流入', 'N/A')}亿元，"
                f"领涨股 {row.get('领涨股', 'N/A')}（{row.get('领涨股-涨跌幅', 'N/A')}%）"
            )
        return f"{sector} 相关行业板块表现（同花顺实时）：\n" + "\n".join(lines)

    except Exception as e:
        return (
            f"{sector} 板块数据暂时无法获取（{type(e).__name__}），"
            f"请基于已有市场信息进行分析。"
        )


# ============================================================
# 指数数据源
#
# 东财的 index_zh_a_hist 在部分网络环境下会直接被断连（RemoteDisconnected），
# 所以每个指数都配一个新浪源作为回退，避免"真实数据模式"整块失效。
# 元素为 (显示名, 东财代码, 新浪代码)
# ============================================================

_INDEXES = [
    ("上证指数", "000001", "sh000001"),
    ("创业板指", "399006", "sz399006"),
    ("沪深300", "000300", "sh000300"),
]


def _index_quote(ak: object, name: str, em_symbol: str, sina_symbol: str) -> str:
    """取单个指数的最新点位和涨跌幅；东财失败自动回退新浪。返回空串表示两个源都失败。"""
    from datetime import date, timedelta

    end = date.today().strftime("%Y%m%d")
    start = (date.today() - timedelta(days=10)).strftime("%Y%m%d")

    # 源1：东财（自带涨跌幅字段）
    try:
        df = ak.index_zh_a_hist(
            symbol=em_symbol, period="daily", start_date=start, end_date=end
        )
        if df is not None and len(df) > 0:
            latest = df.iloc[-1]
            return f"{name} {latest['收盘']}（{latest['涨跌幅']}%）"
    except Exception:
        pass  # fall through 到新浪源

    # 源2：新浪（只有 OHLC，涨跌幅自行算）
    try:
        df = ak.stock_zh_index_daily(symbol=sina_symbol)
        if df is not None and len(df) >= 2:
            last = float(df.iloc[-1]["close"])
            prev = float(df.iloc[-2]["close"])
            pct = round((last - prev) / prev * 100, 2) if prev else 0.0
            return f"{name} {last:.2f}（{'+' if pct >= 0 else ''}{pct}%）"
    except Exception:
        pass

    return ""


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

        results = [_index_quote(ak, name, em, sina) for name, em, sina in _INDEXES]
        ok = [r for r in results if r]
        if not ok:
            return "指数行情数据源均不可用，请基于已有市场信息进行分析。"
        return " | ".join(ok)

    except Exception as e:
        return (
            f"指数行情实时数据暂时无法获取（{type(e).__name__}），"
            f"请基于已有市场信息进行分析。"
        )


def _pmi_zone(value: object) -> str:
    """PMI 荣枯线判断。必须做数值比较——旧实现用字符串比较，'N/A' >= '50' 恒为 True。"""
    try:
        return "扩张" if float(value) >= 50 else "收缩"
    except (TypeError, ValueError):
        return "未知"


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

        # 源1：macro_china_pmi()，列为 ['月份','制造业-指数','制造业-同比增长','非制造业-指数','非制造业-同比增长']
        # 按时间倒序，iloc[0] 才是最新月份（旧实现用 iloc[-1] 会取到 2008 年的数据）
        try:
            df = ak.macro_china_pmi()
            if df is not None and len(df) > 0:
                latest = df.iloc[0]
                period = latest["月份"]
                mfg = latest["制造业-指数"]
                non_mfg = latest["非制造业-指数"]
                return (
                    f"宏观PMI数据（{period}）："
                    f"制造业PMI {mfg}（{_pmi_zone(mfg)}区间）| "
                    f"非制造业PMI {non_mfg}（{_pmi_zone(non_mfg)}区间）"
                )
        except Exception:
            pass  # fall through 到官方 PMI 快讯源

        # 源2：macro_china_pmi_yearly()，列为 ['商品','日期','今值','预测值','前值']
        # 注意：这里没有"制造业"列，旧实现读 latest.get("制造业") 恒为 N/A
        df = ak.macro_china_pmi_yearly()
        if df is None or len(df) == 0:
            return "宏观PMI数据暂时不可用，请基于已有信息进行分析。"
        latest = df.iloc[-1]
        value = latest["今值"]
        return (
            f"{latest['商品']}（{latest['日期']}）："
            f"{value}（{_pmi_zone(value)}区间），"
            f"前值 {latest['前值']}，预测值 {latest['预测值']}"
        )

    except Exception as e:
        return (
            f"宏观数据暂时无法获取（{type(e).__name__}），"
            f"请基于已有信息进行分析。"
        )


def _numbered(items: list[str]) -> str:
    """把标题列表格式化为编号列表"""
    return "\n".join(f"{i}. {t}" for i, t in enumerate(items, 1))


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

        # 源1：东财个股新闻。参数名是 symbol —— 旧实现传 stock=，
        # 在 akshare>=1.12 上直接 TypeError，于是真实模式下新闻永远走 fallback。
        try:
            df = ak.stock_news_em(symbol=keyword)
            titles = [str(t) for t in df["新闻标题"].head(5)] if df is not None and len(df) else []
            if titles:
                return f"'{keyword}' 近期相关新闻（东方财富）：\n" + _numbered(titles)
        except Exception:
            pass  # fall through 到全球财经快讯源

        # 源2：财联社 / 新浪全球财经快讯，按关键词过滤（东财接口不可用时的兜底）
        # 关键词在正文里的情况很常见，所以匹配用"标题+内容"，展示仍用标题
        fallback_latest: list[str] = []
        for fn_name, kwargs, display_col, search_cols in (
            ("stock_info_global_cls", {"symbol": "全部"}, "标题", ["标题", "内容"]),
            ("stock_info_global_sina", {}, "内容", ["内容"]),
        ):
            fn = getattr(ak, fn_name, None)
            if fn is None:
                continue
            try:
                df = fn(**kwargs)
                if df is None or len(df) == 0:
                    continue
                display = df[display_col].astype(str)
                haystack = df[search_cols[0]].astype(str)
                for extra in search_cols[1:]:
                    if extra in df.columns:
                        haystack = haystack + " " + df[extra].astype(str)

                hits = [
                    display.iloc[i][:120]
                    for i in range(len(df))
                    if keyword in haystack.iloc[i]
                ][:5]
                if hits:
                    return f"'{keyword}' 近期相关快讯：\n" + _numbered(hits)

                if not fallback_latest:
                    fallback_latest = [t[:100] for t in display.head(3)]
            except Exception:
                continue

        # 关键词无命中时，退一步给出最新市场快讯供 LLM 参考，好过一句"没找到"
        if fallback_latest:
            return (
                f"未检索到 '{keyword}' 的直接新闻，以下为最新市场快讯：\n"
                + _numbered(fallback_latest)
            )

        return f"未找到与 '{keyword}' 相关的近期新闻。"

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
        from datetime import date, timedelta

        import akshare as ak

        end = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=30)).strftime("%Y%m%d")

        df, cols = None, None
        # 源1：东财（中文列名）
        try:
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=start, end_date=end, adjust="qfq"
            )
            cols = ("收盘", "最高", "最低", "成交量")
        except Exception:
            df = None

        # 源2：新浪（英文列名），东财被断连时兜底
        if df is None or len(df) == 0:
            prefix = "sh" if code.startswith(("6", "9")) else "sz"
            df = ak.stock_zh_a_daily(
                symbol=f"{prefix}{code}", start_date=start, end_date=end, adjust="qfq"
            )
            cols = ("close", "high", "low", "volume")

        if df is None or len(df) == 0:
            return f"{query}（{code}）近期无交易数据，可能为停牌状态。"

        close_col, high_col, low_col, vol_col = cols
        first_close = float(df.iloc[0][close_col])
        last_close = float(df.iloc[-1][close_col])
        pct = round((last_close - first_close) / first_close * 100, 2) if first_close else 0.0
        high = float(df[high_col].max())
        low = float(df[low_col].min())
        avg_vol = float(df[vol_col].mean())

        direction = "+" if pct >= 0 else ""
        return (
            f"{query}（{code}）近30日表现：\n"
            f"涨跌幅 {direction}{pct}%，"
            f"最新收盘 {last_close:.2f}元，"
            f"区间最高 {high:.2f}元，区间最低 {low:.2f}元，"
            f"日均成交量 {avg_vol:.0f}"
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


# Structured acquisition is separate from INVEST_TOOLS to preserve report inputs.
@tool
def get_price_history(query: str, start_date: str, end_date: str, config: RunnableConfig,
                      asset_type: Literal["stock", "index"] = "stock",
                      adjustment: Literal["none", "qfq", "hfq"] = "qfq") -> str:
    """Fetch dated daily A-share prices or benchmark index history into a request dataset.

    Use for historical/quantitative requests, not just the latest price.
    Dates must be YYYY-MM-DD. Stock query accepts a name or six-digit code;
    index query requires a six-digit index code and adjustment='none'.
    Returns metadata/reference and endpoint observations, never the full table.
    DatasetStore is injected by application config, not supplied by the model.
    """
    import json
    from datetime import date, datetime, timezone
    from zoneinfo import ZoneInfo

    import pandas as pd
    from src.datasets import DatasetStore, PriceDataset

    def unavailable(kind, message):
        return json.dumps({"status": "unavailable", "error": {"type": kind, "message": message}}, ensure_ascii=False)

    store = (config.get("configurable") or {}).get("dataset_store")
    if not isinstance(store, DatasetStore):
        return unavailable("missing_store", "请求内数据存储未配置，不能返回有效数据集引用。")
    try:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        if start > end or (end - start).days > 3660 or end > datetime.now(ZoneInfo("Asia/Shanghai")).date():
            return unavailable("invalid_range", "日期须为有效历史区间，单次最长3660天。")
        code = _resolve_stock_code(query) if asset_type == "stock" else query.strip()
        if not code or len(code) != 6 or not code.isdigit():
            return unavailable("invalid_symbol", "仅支持六位 A 股或指数代码，请明确查询对象。")
        if asset_type == "index" and adjustment != "none":
            return unavailable("invalid_adjustment", "指数历史行情请使用 adjustment=none。")
        if asset_type == "stock" and not code.startswith(("0", "3", "6")):
            return unavailable("unsupported_market", "首版仅支持沪深 A 股。")
        real = _should_use_real_data()
        if real:
            import akshare as ak
            provider = "akshare/eastmoney"
            if asset_type == "stock":
                try:
                    df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start.strftime("%Y%m%d"),
                        end_date=end.strftime("%Y%m%d"), adjust="" if adjustment == "none" else adjustment)
                except Exception:
                    df = None
                if df is None or df.empty:
                    prefix = "sh" if code.startswith("6") else "sz"
                    df = ak.stock_zh_a_daily(symbol=prefix + code, start_date=start.strftime("%Y%m%d"),
                        end_date=end.strftime("%Y%m%d"), adjust="" if adjustment == "none" else adjustment)
                    provider = "akshare/sina"
                    if df is not None:
                        df = df.rename(columns={"date": "日期", "close": "收盘", "open": "开盘",
                            "high": "最高", "low": "最低", "volume": "成交量"})
            else:
                df = ak.index_zh_a_hist(symbol=code, period="daily", start_date=start.strftime("%Y%m%d"),
                                       end_date=end.strftime("%Y%m%d"))
        else:
            days = pd.bdate_range(start, end)
            df = pd.DataFrame({"日期": days, "收盘": [100. + i * .1 for i in range(len(days))]})
            provider = "synthetic_demo"
        if df is None or df.empty:
            return unavailable("no_data", "指定区间无可用交易数据。")
        rows = []
        has_volume = asset_type == "stock" and "成交量" in df.columns
        for _, raw in df.iterrows():
            observed = pd.to_datetime(raw["日期"], errors="raise").date()
            if not start <= observed <= end:
                raise ValueError("provider date outside requested range")
            row = {"date": observed, "close": float(raw["收盘"])}
            for column, key in (("开盘", "open"), ("最高", "high"), ("最低", "low")):
                if column in df.columns:
                    row[key] = None if pd.isna(raw[column]) else float(raw[column])
            if has_volume:
                # stock_zh_a_hist documented volume is lots (手), normalize to shares.
                row["volume"] = None if pd.isna(raw["成交量"]) else float(raw["成交量"]) * (1 if provider == "akshare/sina" else 100)
            rows.append(row)
        dataset = PriceDataset(kind="price_history", symbol=code,
            market=("SSE" if code.startswith("6") else "SZSE") if asset_type == "stock" else "CN_INDEX",
            asset_type=asset_type, currency="CNY", frequency="daily", adjustment=adjustment,
            price_unit="CNY/share" if asset_type == "stock" else "points",
            volume_unit="shares" if has_volume else "not_available", provider=provider,
            source_url=("https://finance.sina.com.cn/" if provider == "akshare/sina" else "https://quote.eastmoney.com/") if real else None,
            retrieved_at=datetime.now(timezone.utc), data_mode="real" if real else "mock", rows=rows)
        ref = store.put(dataset)
        return json.dumps({"status": "available", "dataset_ref": ref.model_dump(mode="json"),
            "first_close": rows[0]["close"], "last_close": rows[-1]["close"],
            "limitations": ["模拟工作日序列，不反映交易所节假日或真实行情"] if not real else []}, ensure_ascii=False)
    except Exception as exc:
        return unavailable("history_unavailable", f"历史行情获取或数据验证失败（{type(exc).__name__}）；未注册数据集，请稍后重试。")


@tool
def get_valuation_snapshot(query: str, config: RunnableConfig, as_of_date: str | None = None) -> str:
    """Fetch an A-share valuation snapshot on the latest available date <= as_of_date.

    Date is YYYY-MM-DD, defaults to today's Shanghai date. Uses PE TTM and PB MRQ,
    never substitutes static PE. Dividend yield is explicitly unavailable in this source.
    Registers a dated ValuationDataset and returns its canonical reference and metrics.
    Historical source observations are not guaranteed point-in-time financial records.
    """
    import json
    import math
    from datetime import date, datetime, timezone
    from zoneinfo import ZoneInfo
    import pandas as pd
    from src.datasets import DatasetStore, ValuationDataset

    def unavailable(kind, message):
        return json.dumps({"status": "unavailable", "error": {"type": kind, "message": message}}, ensure_ascii=False)

    store = (config.get("configurable") or {}).get("dataset_store")
    if not isinstance(store, DatasetStore):
        return unavailable("missing_store", "请求内数据存储未配置。")
    try:
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        requested = date.fromisoformat(as_of_date) if as_of_date is not None else today
        if requested > today:
            return unavailable("invalid_date", "不支持未来日期估值。")
        code = _resolve_stock_code(query)
        if not code or len(code) != 6 or not code.startswith(("0", "3", "6")):
            return unavailable("invalid_symbol", "首版仅支持沪深 A 股名称或六位代码。")
        real = _should_use_real_data()
        if real:
            import akshare as ak
            frame = ak.stock_value_em(symbol=code)
            if frame is None or frame.empty:
                return unavailable("no_data", "无可用估值数据。")
            frame = frame.copy()
            frame["数据日期"] = pd.to_datetime(frame["数据日期"], errors="raise").dt.date
            eligible = frame[frame["数据日期"] <= requested]
            if eligible.empty:
                return unavailable("no_data", "指定日期及之前无估值观察值。")
            actual = eligible["数据日期"].max()
            latest = eligible[eligible["数据日期"] == actual]
            if len(latest) != 1:
                return unavailable("ambiguous_data", "同一观察日期有重复估值记录。")
            raw = latest.iloc[0]
        else:
            actual = requested
            raw = {"PE(TTM)": 20., "市净率": 2.}
        values = {}
        for name, column, basis in (("pe_ttm", "PE(TTM)", "PE_TTM"), ("pb", "市净率", "PB_MRQ")):
            source = raw.get(column)
            if source is None or pd.isna(source) or str(source).strip() in {"", "-", "--"}:
                value, reason = None, f"供应商未提供{column}，不以其他口径代替"
            else:
                value, reason = float(source), None
                if not math.isfinite(value):
                    raise ValueError("nonfinite valuation")
            values[name] = {"value": value, "unit": "multiple", "basis": basis, "missing_reason": reason}
        values["dividend_yield"] = {"value": None, "unit": "percent", "basis": None,
            "missing_reason": "该来源不提供有明确口径的个股股息率"}
        if all(values[name]["value"] is None for name in ("pe_ttm", "pb")):
            return unavailable("no_metrics", "无可用 PE TTM 或 PB MRQ，不注册空快照。")
        dataset = ValuationDataset(kind="valuation_snapshot", symbol=code,
            market="SSE" if code.startswith("6") else "SZSE", currency="CNY",
            provider="akshare/eastmoney/stock_value_em" if real else "synthetic_demo",
            source_url=f"https://data.eastmoney.com/gzfx/detail/{code}.html" if real else None,
            retrieved_at=datetime.now(timezone.utc), data_mode="real" if real else "mock",
            as_of_date=actual, available_at=None, report_period=None, metrics=values)
        ref = store.put(dataset)
        limitations = ["股息率缺失，未推断公告日期/报告期，不能用于无前视偏差历史回测。",
                       "非正PE/PB不适用于相对估值排名；不同指标口径不可混用。"]
        if actual != requested:
            limitations.append(f"请求日期{requested}，实际观察日期{actual}；未假定为当天估值。")
        if not real:
            limitations.append("模拟数据，不代表真实估值。")
        return json.dumps({"status": "available", "dataset_ref": ref.model_dump(mode="json"),
            "requested_date": requested.isoformat(), "metrics": dataset.model_dump(mode="json")["metrics"],
            "limitations": limitations}, ensure_ascii=False, allow_nan=False)
    except Exception:
        return unavailable("valuation_unavailable", "估值获取或验证失败，未注册数据集，请稍后重试。")
