"""Strategy/Risk display over validated task payloads and event-delivered series, without reexecution."""
import plotly.graph_objects as go
import streamlit as st

from app.analytics_dashboard import format_metric
from src.specialists.strategy.state import StrategyResult

_RISK_LABELS = {'annualized_volatility':'组合年化波动率','max_drawdown':'回放最大回撤',
    'historical_var_95':'历史VaR 95%','historical_cvar_95':'历史CVaR 95%',
    'historical_var_99':'历史VaR 99%','historical_cvar_99':'历史CVaR 99%',
    'parametric_var_95':'参数VaR 95%','parametric_cvar_95':'参数CVaR 95%',
    'parametric_var_99':'参数VaR 99%','parametric_cvar_99':'参数CVaR 99%'}
_SERIES_TITLES = {'portfolio_nav':'当前权重恒定回放净值（非真实业绩）','portfolio_value':'情景期间组合价值（买入持有）'}


def build_strategy_figures(series):
    """series: {artifact_id: {key: [{date, value}]}} from the strategy_artifacts event."""
    figures = []
    for ident, groups in series.items():
        for key, points in groups.items():
            if not points:
                continue
            figure = go.Figure(go.Scatter(x=[p['date'] for p in points], y=[p['value'] for p in points], mode='lines'))
            figure.update_layout(title=_SERIES_TITLES.get(key, key), template='plotly_white', height=320,
                                 margin=dict(l=20, r=20, t=50, b=20), hovermode='x unified')
            figures.append((f'{ident}_{key}', figure))
    return figures


def _render_risk(row):
    st.markdown('**组合风险（1日持有期）**')
    st.caption(f"{row['start_date']} → {row['end_date']} · {row['observations']}个收益观察值 · "
               f"收益矩阵 {row['return_matrix_analysis_id']}")
    entries = [(name, value) for name, value in row['metrics'].items() if name in _RISK_LABELS]
    for start in range(0, len(entries), 4):
        batch = entries[start:start + 4]
        for column, (name, value) in zip(st.columns(len(batch)), batch):
            column.metric(_RISK_LABELS[name], format_metric(value, 'fraction'))
    for name, reason in row.get('reasons', {}).items():
        st.caption(f"{_RISK_LABELS.get(name, name)}：{reason}")


def _render_scenario(scenario):
    replay = scenario['origin'] == 'historical_replay'
    st.markdown(f"**{'历史情景重演' if replay else '情景'}：{scenario['name']}**")
    window = f"{scenario['start_date']} → {scenario['end_date']} · " if replay else ''
    st.caption(f"{window}来源：{scenario['origin']} · 持仓日期：{scenario['as_of_date']} · {scenario['currency']}；"
               + ('历史走势回放，不代表未来' if replay else '假设，不是预测'))
    value = scenario.get('portfolio_return')
    if value is None:
        st.warning(f"有持仓未覆盖情景区间（覆盖权重 {format_metric(scenario.get('coverage_weight'), 'fraction')}），未计算组合收益。")
    else:
        columns = st.columns(2 if replay else 1)
        columns[0].metric('情景组合收益', format_metric(value, 'fraction'))
        if replay:
            columns[1].metric('情景期间最大回撤', format_metric(scenario.get('max_drawdown'), 'fraction'))
    if scenario.get('contributions'):
        st.dataframe(scenario['contributions'], hide_index=True, width='stretch')
    for benchmark in scenario.get('benchmarks', []):
        st.caption(f"对照指数 {benchmark['symbol']} 同期收益：{format_metric(benchmark['period_return'], 'fraction')}")


def render_strategy_task(task_id, record, series=None, render_id='final'):
    st.subheader(f'策略与风险任务 {task_id}')
    st.caption(f"{record['question']} · {record['status']}")
    if record.get('error'):
        st.error(record['error']['message'])
    if not record.get('result'):
        return
    try:
        result = StrategyResult.model_validate(record['result'])
    except ValueError:
        st.error('策略结果未通过展示契约校验。')
        return
    st.markdown(result.summary)
    for title, claims in [('机会', result.opportunities), ('风险', result.risks)]:
        if claims:
            st.markdown(f'**{title}**')
        for claim in claims:
            st.write(claim.text)
            st.caption('依据：' + ', '.join(claim.evidence_ids))
    for row in result.risk_results:
        _render_risk(row)
    if result.constraint_checks:
        st.markdown('**用户约束检查**')
        st.dataframe(result.constraint_checks, hide_index=True, width='stretch')
    for scenario in result.scenario_results:
        _render_scenario(scenario)
    for kind, figure in build_strategy_figures(series or {}):
        st.plotly_chart(figure, width='stretch', key=f'strategy_{render_id}_{task_id}_{kind}')
    for text in result.missing_information:
        st.warning(text)
    for request in result.missing_data_requests:
        st.info('待补数据：' + str(request))
    for text in result.limitations:
        st.caption('限制：' + text)
    with st.expander(f'策略假设与来源 · {task_id}'):
        st.json({'assumptions':result.assumptions, 'dataset_refs':result.dataset_refs,
                 'analysis_ids':[r['analysis_id'] for r in result.analysis_refs], 'evidence':result.evidence})
