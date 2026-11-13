"""Curated user journeys; dates are resolved when a card is selected."""
from datetime import datetime
from zoneinfo import ZoneInfo


def example_queries(now=None):
    today=(now or datetime.now(ZoneInfo('Asia/Shanghai'))).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
    return [
        {'id':'valuation','title':'查最新估值','hint':'一次查询 · 两只股票',
         'query':'茅台和五粮液最新的PE TTM与PB是多少？'},
        {'id':'performance','title':'看历史表现','hint':'价格采集 + 指标与曲线',
         'query':'分析贵州茅台过去一年的收益、波动率和最大回撤，并展示累计收益和回撤曲线。'},
        {'id':'benchmark','title':'和指数比较','hint':'股票与指数采集 + 基准比较',
         'query':'比较茅台过去一年相对沪深300的表现，计算超额收益和Beta。'},
        {'id':'comparison','title':'比较两家公司','hint':'多类数据 + 多项分析',
         'query':'比较茅台和五粮液最新估值，以及过去一年的收益、波动率和最大回撤。不要生成完整报告。'},
        {'id':'portfolio','title':'检查测试组合','hint':'假设组合 · 约束检查 + 压力测试',
         'query':f'测试假设组合：持仓日期为{today}，人民币：茅台60%、五粮液30%、现金10%，单股上限50%。检查限制，并计算两只股票分别下跌20%和10%时的组合收益，不查询行情。'},
        {'id':'report','title':'生成行业报告','hint':'完整报告流程 · 阅读与下载',
         'query':'请生成新能源行业未来一年的投研报告，重点关注光伏。'},
    ]


BOUNDARY_EXAMPLES = [
    {'id':'short_sample','title':'样本不足','query':'只使用贵州茅台最近5个交易日的数据，计算20日动量和20日波动率，不要扩大数据区间。'},
    {'id':'missing_portfolio','title':'缺少持仓','query':'假设茅台和五粮液均下跌15%，帮我计算组合损失，但我还没有提供持仓权重。'},
    {'id':'experimental_strategy','title':'实验性：机会与风险','query':'比较贵州茅台和五粮液最新PE TTM与PB，结合过去一年表现，分析未来一年的投资机会与风险，不生成报告。'},
]
