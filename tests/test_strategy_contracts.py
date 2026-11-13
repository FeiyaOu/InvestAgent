from datetime import date
import pytest
from pydantic import ValidationError
from src.strategy_state import Portfolio, StrategyParameters, StrategyInput


def portfolio(**kw):
    return {'as_of_date': date(2026, 11, 13), 'currency': 'CNY', 'cash_weight': .2,
            'positions': [{'symbol': '600519', 'weight': .8}], **kw}


def test_portfolio_rejects_wrong_total_duplicates_and_nonfinite():
    for updates in ({'cash_weight': 0.}, {'positions': [{'symbol':'600519','weight':float('nan')}]},
                    {'positions':[{'symbol':'600519','weight':.4},{'symbol':'600519','weight':.4}]},
                    {'positions':[{'symbol':'600519','weight':-.2}]}):
        with pytest.raises(ValidationError): Portfolio.model_validate(portfolio(**updates))
    assert Portfolio.model_validate(portfolio()).cash_weight == .2


def test_optional_portfolio_and_constraints_are_not_inferred():
    p = StrategyInput(task='分析投资机会')
    assert p.portfolio is None and p.risk_constraints.model_dump(exclude_none=True) == {}
    with pytest.raises(ValidationError):
        StrategyParameters.model_validate({'scenario_assumptions':[{'scenario_id':'s','name':'跌10%',
          'price_shocks':{'600519':-.1}}]})  # Origin is mandatory.


def test_optional_null_limits_and_scenarios_do_not_invent_inputs():
    p=StrategyParameters.model_validate({'risk_constraints':None,'scenario_assumptions':None})
    assert p.risk_constraints.model_dump(exclude_none=True)=={}
    assert p.scenario_assumptions==[]


def test_narrative_schema_does_not_require_model_to_select_executed_artifacts():
    from src.strategy_state import strategy_answer_schema, StrategyAnswer
    assert 'artifact_ids' not in strategy_answer_schema()['properties']
    assert 'artifact_ids' in StrategyAnswer.model_json_schema()['properties']
