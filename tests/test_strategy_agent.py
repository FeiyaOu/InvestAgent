import json
from unittest.mock import Mock, patch
import pytest
from langchain_core.messages import AIMessage
from src.strategy_agent import create_strategy_agent
from src.strategy_artifacts import StrategyStore
from tests.test_strategy_tools import context


def answer(messages):
    manifest = json.loads(messages[-1].content.split('\n',1)[1])
    ids = [a['artifact_id'] for a in manifest['artifacts']]
    return AIMessage(content=json.dumps({'summary':'组合风险检查完成', 'artifact_ids':ids,
        'risks':[{'text':'单股仓位超过用户限制','evidence_ids':ids[:1]}]}))


def test_graph_tools_and_final_results_are_canonical_and_reset():
    _, cfg = context()
    llm = Mock(); llm.bind_tools.return_value = llm; llm.invoke.side_effect = answer
    graph = create_strategy_agent()
    with patch('src.stages.strategy.create_llm',return_value=llm):
        result = graph.invoke(cfg['configurable']['strategy_input'],config=cfg)
    assert result['status'] == 'completed'
    assert result['tool_calls_used'] == 2
    assert result['result']['constraint_checks'][0]['status'] == 'violated'
    assert result['result']['scenario_results'][0]['portfolio_return'] == pytest.approx(-.08)
    assert result['result']['risks'][0]['evidence_ids']


def test_no_data_is_partial_without_hallucinated_facts_or_model_call():
    llm = Mock()
    with patch('src.stages.strategy.create_llm',return_value=llm):
        result = create_strategy_agent().invoke({'task':'分析茅台机会'},config={'configurable':{'strategy_store':StrategyStore()}})
    assert result['status'] == 'partial'
    assert result['result']['missing_data_requests']
    llm.invoke.assert_not_called()


def test_invented_artifact_reference_preserves_only_canonical_calculations_after_repair():
    _, cfg = context()
    llm=Mock();llm.bind_tools.return_value=llm
    llm.invoke.return_value=AIMessage(content='{"summary":"test","artifact_ids":["unknown"]}')
    with patch('src.stages.strategy.create_llm',return_value=llm):
        result=create_strategy_agent().invoke(cfg['configurable']['strategy_input'],config=cfg)
    assert result['status']=='partial'
    assert result['result']['constraint_checks'][0]['status']=='violated'
    assert result['output_retries']==1


def test_missing_portfolio_does_not_hide_other_results():
    _,cfg=context(portfolio=None)
    llm=Mock();llm.bind_tools.return_value=llm
    llm.invoke.side_effect=lambda msgs: AIMessage(content='{"summary":"缺少持仓","missing_information":["需要持仓"]}')
    with patch('src.stages.strategy.create_llm',return_value=llm):
        result=create_strategy_agent().invoke(cfg['configurable']['strategy_input'],config=cfg)
    assert result['status']=='partial'
    assert result['result']['constraint_checks'][0]['status']=='unknown'


def test_tool_budget_stops_before_any_execution():
    store,cfg=context()
    result=create_strategy_agent(max_tool_calls=0).invoke(cfg['configurable']['strategy_input'],config=cfg)
    assert result['error']['type']=='tool_budget_exceeded'
    assert result['tool_calls_used']==0


def test_narrative_only_evidence_needs_no_portfolio_or_tools():
    evidence={'tool_call_id':'e1','tool_name':'news','content':'有来源的研究证据',
              'retrieved_at':'2026-11-13','data_mode':'real','status':'returned'}
    llm=Mock();llm.bind_tools.return_value=llm
    llm.invoke.return_value=AIMessage(content=json.dumps({'summary':'基于提供证据的定性分析',
        'risks':[{'text':'证据覆盖有限','evidence_ids':['e1']}]}))
    with patch('src.stages.strategy.create_llm',return_value=llm):
        result=create_strategy_agent().invoke({'task':'解释机会','evidence':[evidence]},
            config={'configurable':{'strategy_store':StrategyStore()}})
    assert result['status']=='completed'
    assert result['tool_calls_used']==0 and result['result']['assumptions']['portfolio'] is None


def test_output_repair_cannot_invoke_more_tools():
    _,cfg=context()
    llm=Mock();llm.bind_tools.return_value=llm
    llm.invoke.side_effect=[AIMessage(content='bad json'),AIMessage(content='',tool_calls=[
        {'name':'evaluate_risk_constraints','args':{},'id':'extra'}])]
    with patch('src.stages.strategy.create_llm',return_value=llm):
        result=create_strategy_agent().invoke(cfg['configurable']['strategy_input'],config=cfg)
    assert result['status']=='partial' and result['error'] is None
    assert 'invalid_output' in str(result['result']['missing_information'])
    assert result['tool_calls_used']==2


def test_new_invocation_resets_artifacts_and_rejects_previous_reference():
    store,cfg=context()
    llm=Mock();llm.bind_tools.return_value=llm;llm.invoke.side_effect=answer
    graph=create_strategy_agent()
    with patch('src.stages.strategy.create_llm',return_value=llm):
        first=graph.invoke(cfg['configurable']['strategy_input'],config=cfg)
    old_id=first['result']['artifact_refs'][0]['artifact_id']
    clean={'task':'仅解释用户持仓','portfolio':cfg['configurable']['strategy_input']['portfolio']}
    llm.invoke.side_effect=None
    llm.invoke.return_value=AIMessage(content=json.dumps({'summary':'旧引用不可复用','artifact_ids':[old_id]}))
    with patch('src.stages.strategy.create_llm',return_value=llm):
        second=graph.invoke({**first,**clean,'risk_constraints':{},'scenario_assumptions':[]},config=cfg)
    assert second['status']=='failed' and second['tool_calls_used']==0
    assert second['strategy_artifacts']==[]


def test_unavailable_dataset_fails_before_model_invocation():
    llm=Mock()
    with patch('src.stages.strategy.create_llm',return_value=llm):
        result=create_strategy_agent().invoke({'task':'风险解释','dataset_refs':[{'dataset_id':'expired'}]},
            config={'configurable':{'strategy_store':StrategyStore()}})
    assert result['status']=='failed'
    llm.invoke.assert_not_called()


def test_failed_market_tool_response_is_not_successful_evidence():
    evidence={'tool_call_id':'bad','tool_name':'get_price_history',
        'content':'{"status":"unavailable"}', 'retrieved_at':'2026-11-13','data_mode':'real','status':'returned'}
    llm=Mock()
    with patch('src.stages.strategy.create_llm',return_value=llm):
        result=create_strategy_agent().invoke({'task':'解释机会','evidence':[evidence]},
            config={'configurable':{'strategy_store':StrategyStore()}})
    assert result['status']=='partial'
    llm.invoke.assert_not_called()


def test_drawdown_tool_results_survive_explanation_model_failure():
    from tests.test_analytics_agent import setup_data
    from src.analytics_tools import analyze_price_performance
    _,_,ref,cfg=setup_data()
    cfg['configurable']['strategy_store']=StrategyStore()
    a=json.loads(analyze_price_performance.invoke({'dataset_id':ref.dataset_id},config=cfg))['analysis_ref']
    llm=Mock();llm.invoke.side_effect=RuntimeError('private provider error')
    llm.bind_tools.return_value=llm
    with patch('src.stages.strategy.create_llm',return_value=llm):
        result=create_strategy_agent().invoke({'task':'检查历史回撤上限5%', 'subjects':['600519'],
            'dataset_refs':[ref.model_dump(mode='json')],'analysis_refs':[a],
            'risk_constraints':{'max_asset_drawdown':.05}},config=cfg)
    assert result['status']=='partial' and result['error'] is None
    assert result['result']['constraint_checks'][0]['status']=='violated'
    assert result['result']['constraint_checks'][0]['observed']==pytest.approx(.1)
    assert 'private provider error' not in str(result)


def test_strategy_validation_failure_emits_safe_field_diagnostics():
    events=list(create_strategy_agent().stream({'task':'检查持仓','portfolio':{'currency':'CNY'}},
        config={'configurable':{'strategy_store':StrategyStore()}},stream_mode='custom'))
    diagnostics=[e for e in events if e.get('event')=='strategy_diagnostic']
    assert diagnostics and diagnostics[0]['error_type']=='invalid_strategy_input'
    assert any(d['field']=='portfolio.as_of_date' for d in diagnostics[0]['diagnostics'])


def test_pure_opportunity_explanation_does_not_bind_inapplicable_tools():
    evidence={'tool_call_id':'e1','tool_name':'lookup','content':'研究证据',
              'retrieved_at':'2026-11-13','data_mode':'real','status':'returned'}
    llm=Mock();llm.bind_tools.return_value=llm
    llm.invoke.return_value=AIMessage(content='{"summary":"基于已有证据解释机会与风险"}')
    with patch('src.stages.strategy.create_llm',return_value=llm):
        result=create_strategy_agent().invoke({'task':'分析未来机会与风险','evidence':[evidence]},
            config={'configurable':{'strategy_store':StrategyStore()}})
    assert result['status']=='completed' and result['tool_calls_used']==0
    llm.bind_tools.assert_not_called()


def test_unexpected_tool_request_is_repaired_without_execution_or_fake_tool_history():
    evidence={'tool_call_id':'e1','tool_name':'lookup','content':'研究证据',
              'retrieved_at':'2026-11-13','data_mode':'real','status':'returned'}
    llm=Mock();llm.bind_tools.return_value=llm
    llm.invoke.side_effect=[AIMessage(content='',tool_calls=[{'name':'forecast_stock','args':{},'id':'bad'}]),
                           AIMessage(content='{"summary":"基于证据的定性解释"}')]
    with patch('src.stages.strategy.create_llm',return_value=llm):
        result=create_strategy_agent().invoke({'task':'分析未来机会','evidence':[evidence]},
            config={'configurable':{'strategy_store':StrategyStore()}})
    assert result['status']=='completed'
    assert result['output_retries']==1 and result['tool_calls_used']==0
    assert not any(getattr(m,'tool_calls',[]) for m in result['messages'])


def test_performance_plus_valuation_handoff_is_narrative_only_without_limits():
    from tests.test_analytics_agent import setup_data
    from tests.test_factors_valuations import valuation
    from src.analytics_tools import analyze_price_performance, compare_valuations
    ds,_,p1,cfg=setup_data()
    p2=ds.put(ds.get(p1.dataset_id).model_copy(update={'symbol':'000858','market':'SZSE'}))
    v1=valuation(ds,'600519');v2=valuation(ds,'000858')
    analyses=[json.loads(analyze_price_performance.invoke({'dataset_id':p.dataset_id},config=cfg))['analysis_ref'] for p in (p1,p2)]
    analyses.append(json.loads(compare_valuations.invoke({'dataset_ids':[v1.dataset_id,v2.dataset_id]},config=cfg))['analysis_ref'])
    cfg['configurable']['strategy_store']=StrategyStore()
    llm=Mock();llm.bind_tools.return_value=llm
    llm.invoke.return_value=AIMessage(content=json.dumps({'summary':'结合已有估值与历史风险解释机会和限制',
        'risks':[{'text':'历史回撤不保证未来风险','evidence_ids':[analyses[0]['analysis_id']]}]}))
    with patch('src.stages.strategy.create_llm',return_value=llm):
        result=create_strategy_agent().invoke({'task':'分析茅台五粮液未来一年机会与风险',
            'dataset_refs':[r.model_dump(mode='json') for r in (p1,p2,v1,v2)],'analysis_refs':analyses},config=cfg)
    assert result['status']=='completed'
    assert result['tool_calls_used']==0 and result['result']['artifact_refs']==[]
    assert len(result['result']['analysis_refs'])==3
    llm.bind_tools.assert_not_called()


def test_analysis_ids_in_artifact_field_get_actionable_repair_manifest():
    from tests.test_analytics_agent import setup_data
    from src.analytics_tools import analyze_price_performance
    _,_,ref,cfg=setup_data()
    cfg['configurable']['strategy_store']=StrategyStore()
    a=json.loads(analyze_price_performance.invoke({'dataset_id':ref.dataset_id},config=cfg))['analysis_ref']
    llm=Mock();llm.bind_tools.return_value=llm
    replies=iter([False,True])
    def respond(messages):
        if not next(replies):
            return AIMessage(content=json.dumps({'summary':'风险解释','artifact_ids':[a['analysis_id']]}))
        repair='\n'.join(m.content for m in messages if m.type=='human')
        assert 'artifact_ids' in repair and 'evidence_ids' in repair
        assert a['analysis_id'] in repair
        assert 'reference_scope' in repair
        return AIMessage(content=json.dumps({'summary':'风险解释','risks':[{
            'text':'历史回撤不是未来保证','evidence_ids':[a['analysis_id']]}]}))
    llm.invoke.side_effect=respond
    with patch('src.stages.strategy.create_llm',return_value=llm):
        result=create_strategy_agent().invoke({'task':'解释投资风险','dataset_refs':[ref.model_dump(mode='json')],
            'analysis_refs':[a]},config=cfg)
    assert result['status']=='completed'
    assert result['output_retries']==1 and result['result']['artifact_refs']==[]
