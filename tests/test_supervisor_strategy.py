from unittest.mock import patch, Mock
import pytest
from src.parent_graph import create_parent_graph
from src.planner_schemas import TaskPlan
from tests.test_strategy_agent import answer
from tests.test_strategy_tools import context


def strategy_task():
    _,cfg=context()
    inputs=cfg['configurable']['strategy_input']
    return {'task_id':'s','category':'investment_strategy','question':'检查组合仓位并做跌10%压力测试','depends_on':[],
        'strategy_parameters':{k:v for k,v in inputs.items() if k not in {'task','dataset_refs','analysis_refs','evidence'}}}


def test_plan_parameters_and_real_parent_dispatch_to_strategy_with_stores():
    task=strategy_task()
    payload={'status':'ready','tasks':[task],'clarification_questions':[]}
    assert TaskPlan.model_validate(payload).to_state()['tasks'][0]['strategy_parameters']['portfolio']['as_of_date']=='2026-11-13'
    llm=Mock();llm.bind_tools.return_value=llm;llm.invoke.side_effect=answer
    with patch('src.stages.planner._create_chain') as planner, patch('src.stages.strategy.create_llm',return_value=llm), patch('src.stages.composer._create_chain',side_effect=RuntimeError()):
        planner.return_value.invoke.return_value=payload
        result=create_parent_graph().invoke({'user_query':'检查组合'})
    record=result['task_results']['s']
    assert record['status']=='completed'
    assert record['result']['scenario_results'][0]['portfolio_return']==pytest.approx(-.08)
    assert 'portfolio_return' in result['final_response']
    assert 'strategy_store' not in result and 'messages' not in result


def test_parameters_cannot_be_attached_to_other_category():
    task=strategy_task();task['category']='market_data'
    with pytest.raises(ValueError): TaskPlan.model_validate({'status':'ready','tasks':[task],'clarification_questions':[]})
