import json
from unittest.mock import Mock, patch
import pytest
from src.strategy_agent import create_strategy_agent
from src.strategy_handoff import strategy_result, canonical_request, strategy_inputs
from tests.test_strategy_agent import answer
from tests.test_strategy_tools import context
from tests.test_analytics_agent import setup_data
from src.analytics_tools import analyze_price_performance


def test_forged_child_numbers_are_rebuilt_and_cross_task_scope_is_rejected():
    _,cfg=context()
    cfg['configurable']['strategy_expected_scope']='scope1'
    llm=Mock();llm.bind_tools.return_value=llm;llm.invoke.side_effect=answer
    with patch('src.stages.strategy.create_llm',return_value=llm):
        raw=create_strategy_agent().invoke(cfg['configurable']['strategy_input'],config=cfg)
    raw['result']['scenario_results'][0]['portfolio_return']=999
    status,result,_=strategy_result(raw,cfg['configurable']['strategy_input'],cfg)
    assert status=='completed'
    assert result['scenario_results'][0]['portfolio_return']==pytest.approx(-.08)
    raw['scope_id']='other'
    with pytest.raises(ValueError): strategy_result(raw,cfg['configurable']['strategy_input'],cfg)


def test_canonical_refs_ignore_forged_values_but_reject_missing_data_scope():
    ds,store,ref,cfg=setup_data()
    output=json.loads(analyze_price_performance.invoke({'dataset_id':ref.dataset_id},config=cfg))
    analysis=output['analysis_ref'];analysis['metrics']['period_return']=999
    raw={'task':'研究风险','dataset_refs':[ref.model_dump(mode='json')],'analysis_refs':[analysis]}
    canonical=canonical_request(raw,cfg)
    assert canonical.analysis_refs[0]['metrics']['period_return']==pytest.approx(.05)
    raw['dataset_refs']=[]
    with pytest.raises(ValueError): canonical_request(raw,cfg)
    ds.clear()
    with pytest.raises(KeyError): canonical_request({'task':'x','dataset_refs':[{'dataset_id':ref.dataset_id}]},cfg)


def test_only_direct_dependencies_grant_references_and_report_is_excluded():
    ds,store,ref,cfg=setup_data()
    results={'m':{'category':'market_data','result':{'dataset_refs':[ref.model_dump(mode='json')]}},
             'r':{'category':'report','result':{'secret':'hidden','dataset_refs':[{'dataset_id':'fake'}]}}}
    raw=strategy_inputs({'question':'研究','depends_on':['r']},results,cfg)
    assert raw['dataset_refs']==[]
    raw=strategy_inputs({'question':'研究','depends_on':['m']},results,cfg)
    assert raw['dataset_refs'][0]['dataset_id']==ref.dataset_id


def test_child_cannot_hide_executed_constraint_checks_by_dropping_references():
    _,cfg=context()
    llm=Mock();llm.bind_tools.return_value=llm;llm.invoke.side_effect=answer
    with patch('src.stages.strategy.create_llm',return_value=llm):
        raw=create_strategy_agent().invoke(cfg['configurable']['strategy_input'],config=cfg)
    raw['result']['artifact_refs']=[]
    raw['result']['constraint_checks']=[]
    raw['result']['scenario_results']=[]
    raw['result']['risks']=[]
    _,result,_=strategy_result(raw,cfg['configurable']['strategy_input'],cfg)
    assert result['constraint_checks'][0]['status']=='violated'
    assert result['scenario_results'][0]['portfolio_return']==pytest.approx(-.08)


def test_failed_strategy_keeps_safe_actionable_error_type():
    status,result,error=strategy_result({'status':'failed','error':{'type':'duplicate_tool_call',
        'message':'相同策略产物已计算，禁止重复调用。'}},{}, {})
    assert status=='failed' and result is None
    assert error['type']=='duplicate_tool_call'
