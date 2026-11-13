from datetime import date
import json
import pytest
from src.strategy_artifacts import StrategyStore
from src.strategy_state import StrategyInput
from src.strategy_tools import evaluate_risk_constraints, stress_test_portfolio


def context(**updates):
    data = {'task':'检查组合', 'portfolio': {'as_of_date':'2026-11-13','currency':'CNY',
        'cash_weight':.2,'positions':[{'symbol':'600519','weight':.8}]},
        'risk_constraints':{'max_single_asset_weight':.5}, 'scenario_assumptions':[
        {'scenario_id':'down','name':'跌10%','origin':'user','price_shocks':{'600519':-.1}}], **updates}
    request = StrategyInput.model_validate_json(json.dumps(data))
    store = StrategyStore()
    return store, {'configurable': {'strategy_store':store,'strategy_input':request.model_dump(mode='json'), 'strategy_scope':'s'}}


def invoke(tool, config, **args):
    return json.loads(tool.invoke(args, config=config))


def test_constraint_and_stress_values_are_deterministic():
    store, config = context()
    result = invoke(evaluate_risk_constraints, config)
    row = result['artifact']['constraint_checks'][0]
    assert row['status'] == 'violated' and row['observed'] == .8
    stress = invoke(stress_test_portfolio, config, scenario_id='down')['artifact']
    assert stress['scenario_results'][0]['portfolio_return'] == pytest.approx(-.08)
    assert stress['scenario_results'][0]['origin'] == 'user'
    saved = store.get(stress['artifact_id'], 's')
    saved['scenario_results'].clear()
    assert store.get(stress['artifact_id'], 's')['scenario_results']
    with pytest.raises(ValueError): store.get(stress['artifact_id'], 'another-task')


def test_missing_portfolio_and_uncovered_shock_do_not_imply_zero():
    _, cfg = context(portfolio=None)
    assert invoke(stress_test_portfolio, cfg, scenario_id='down')['status'] == 'unavailable'
    _, cfg = context(scenario_assumptions=[{'scenario_id':'down','name':'x','origin':'agent_proposed',
                                          'price_shocks':{'000858':-.2}}])
    assert invoke(stress_test_portfolio, cfg, scenario_id='down')['status'] == 'unavailable'


def test_no_constraints_does_not_create_suitability_thresholds():
    _, cfg = context(risk_constraints={})
    result = invoke(evaluate_risk_constraints, cfg)['artifact']
    assert result['constraint_checks'] == []
    assert result['limitations']
    _, cfg = context(risk_constraints={'max_portfolio_volatility':.15})
    row = invoke(evaluate_risk_constraints, cfg)['artifact']['constraint_checks'][0]
    assert row['status'] == 'unknown' and row['observed'] is None


def test_asset_risk_uses_canonical_history_and_never_future_samples():
    from tests.test_analytics_agent import setup_data
    from src.analytics_tools import analyze_price_performance
    _,_,ref,analytics_cfg=setup_data()
    analysis=json.loads(analyze_price_performance.invoke({'dataset_id':ref.dataset_id},config=analytics_cfg))['analysis_ref']
    _,cfg=context(subjects=['600519'],portfolio=None,risk_constraints={'max_asset_drawdown':.05},analysis_refs=[analysis],dataset_refs=analysis['dataset_refs'])
    row=invoke(evaluate_risk_constraints,cfg)['artifact']['constraint_checks'][0]
    assert row['observed']==pytest.approx(.1) and row['status']=='violated'
    assert row['analysis_id']==analysis['analysis_id']
    req=cfg['configurable']['strategy_input']
    req['portfolio']={'as_of_date':'2024-12-31','currency':'CNY','cash_weight':0.,'positions':[{'symbol':'600519','weight':1.}]}
    row=invoke(evaluate_risk_constraints,cfg)['artifact']['constraint_checks'][0]
    assert row['status']=='unknown'


def test_all_cash_scenario_and_weight_constraint_are_defined():
    _,cfg=context(portfolio={'as_of_date':'2026-11-13','currency':'CNY','cash_weight':1.,'positions':[]},
        scenario_assumptions=[{'scenario_id':'cash','name':'现金静态','origin':'user','price_shocks':{}}])
    check=invoke(evaluate_risk_constraints,cfg)['artifact']['constraint_checks'][0]
    assert check['status']=='satisfied' and check['observed']==0.
    stress=invoke(stress_test_portfolio,cfg,scenario_id='cash')['artifact']['scenario_results'][0]
    assert stress['portfolio_return']==0.
