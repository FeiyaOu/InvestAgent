"""Strategy V1 display over validated task payloads, without reexecution."""
import streamlit as st
from src.strategy_state import StrategyResult


def render_strategy_task(task_id, record):
    st.subheader(f'策略与风险任务 {task_id}')
    st.caption(f"{record['question']} · {record['status']}")
    if record.get('error'): st.error(record['error']['message'])
    if not record.get('result'): return
    try:
        result=StrategyResult.model_validate(record['result'])
    except ValueError:
        st.error('策略结果未通过展示契约校验。');return
    st.markdown(result.summary)
    for title,claims in [('机会',result.opportunities),('风险',result.risks)]:
        if claims: st.markdown(f'**{title}**')
        for claim in claims:
            st.write(claim.text);st.caption('依据：'+', '.join(claim.evidence_ids))
    if result.constraint_checks:
        st.markdown('**用户约束检查**')
        st.dataframe(result.constraint_checks,hide_index=True,width='stretch')
    for scenario in result.scenario_results:
        st.markdown(f"**情景：{scenario['name']}**")
        st.caption(f"来源：{scenario['origin']} · 持仓日期：{scenario['as_of_date']} · {scenario['currency']}；假设，不是预测")
        st.metric('情景组合收益',f"{scenario['portfolio_return']:.2%}")
        st.dataframe(scenario['contributions'],hide_index=True,width='stretch')
    for text in result.missing_information: st.warning(text)
    for request in result.missing_data_requests: st.info('待补数据：'+str(request))
    for text in result.limitations: st.caption('限制：'+text)
    with st.expander(f'策略假设与来源 · {task_id}'):
        st.json({'assumptions':result.assumptions,'dataset_refs':result.dataset_refs,
                 'analysis_ids':[r['analysis_id'] for r in result.analysis_refs],'evidence':result.evidence})
