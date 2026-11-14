"""Exercise installed ChatTongyi adapter without a network request."""
import json
from unittest.mock import patch

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.core.llm import create_llm
from src.orchestration.planner import _create_chain
from src.orchestration.planner_schemas import TaskPlan, planner_output_schema

INPUT = {'user_query': '分析茅台表现', 'conversation_context': '', 'correction': '', 'current_date': '2026-11-13'}
PAYLOAD = {'status': 'ready', 'tasks': [
    {'task_id': 'd', 'category': 'market_data', 'question': '获取日线', 'depends_on': []},
    {'task_id': 'a', 'category': 'analytics', 'question': '分析表现', 'depends_on': ['d'],
     'analytics_parameters': {'assumptions': {'window': 20}}}], 'clarification_questions': []}


def test_model_schema_omits_fixed_defaults_but_retains_user_parameters():
    schema = planner_output_schema()
    props = schema['$defs']['AnalyticsAssumptions']['properties']
    assert 'missing_data' not in props
    assert set(props) == {'periods_per_year', 'window'}
    assert 'missing_data' in TaskPlan.model_json_schema()['$defs']['AnalyticsAssumptions']['properties']
    state = TaskPlan.model_validate(PAYLOAD).to_state()
    assert state['tasks'][1]['analytics_parameters']['assumptions'] == {'window': 20, 'missing_data': 'no_fill'}


def invoke_adapter(message, mode, monkeypatch):
    monkeypatch.setenv('PLANNER_OUTPUT_MODE', mode)
    model = create_llm(dashscope_api_key='test-key')
    captured = []
    def generate(self, messages, **kwargs):
        captured.append(kwargs)
        return ChatResult(generations=[ChatGeneration(message=message)])
    with patch('src.orchestration.planner.create_llm', return_value=model), patch.object(type(model), '_generate', generate):
        result = _create_chain().invoke(INPUT)
    return result, captured


def test_installed_tongyi_adapter_passes_schema_as_tool_and_parses_arguments(monkeypatch):
    message = AIMessage(content='', tool_calls=[{'id': 'p1', 'name': 'TaskPlan', 'args': PAYLOAD}])
    parsed, calls = invoke_adapter(message, 'tool_calling', monkeypatch)
    assert parsed == PAYLOAD
    tool = calls[0]['tools'][0]
    assert tool['function']['name'] == 'TaskPlan'
    assert 'missing_data' not in json.dumps(tool)


def test_missing_tool_call_is_retryable_parse_failure(monkeypatch):
    with pytest.raises(OutputParserException):
        invoke_adapter(AIMessage(content='No plan'), 'tool_calling', monkeypatch)


def test_legacy_json_mode_remains_available_for_comparison(monkeypatch):
    parsed, calls = invoke_adapter(AIMessage(content=json.dumps(PAYLOAD)), 'json', monkeypatch)
    assert parsed == PAYLOAD
    assert 'tools' not in calls[0]


def test_structured_output_retries_missing_call_and_still_validates_plan(monkeypatch):
    from src.orchestration.planner import planner
    monkeypatch.setenv('PLANNER_OUTPUT_MODE', 'tool_calling')
    model = create_llm(dashscope_api_key='test-key')
    replies = iter([AIMessage(content='plain text'), AIMessage(content='', tool_calls=[
        {'id': 'p2', 'name': 'TaskPlan', 'args': PAYLOAD}])])
    def generate(self, messages, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=next(replies))])
    with patch('src.orchestration.planner.create_llm', return_value=model), patch.object(type(model), '_generate', generate):
        result = planner({'user_query': '分析茅台表现'})
    assert result['planning_status'] == 'ready'
    assert result['planning_attempts'] == 2
    assert result['plan']['tasks'][1]['analytics_parameters']['assumptions']['missing_data'] == 'no_fill'


def test_planner_contract_supports_portfolio_risk_replay_and_peer_ranking():
    from src.orchestration.planner import _SYSTEM
    strategy = planner_output_schema()['$defs']['StrategyParameters']['properties']
    assert 'historical_scenarios' in strategy
    for rule in ('get_price_history_batch', 'build_return_matrix', 'rank_peers', 'historical_scenarios',
                 '2015_crash', '默认最近2年'):
        assert rule in _SYSTEM
    plan = TaskPlan.model_validate({'status': 'ready', 'clarification_questions': [], 'tasks': [
        {'task_id': 'prices', 'category': 'market_data', 'question': '批量采集600519/000858在2024-11-13至2026-11-13的qfq日线', 'depends_on': []},
        {'task_id': 'matrix', 'category': 'analytics', 'question': '构建收益矩阵', 'depends_on': ['prices']},
        {'task_id': 'risk', 'category': 'investment_strategy', 'question': '评估组合风险', 'depends_on': ['prices', 'matrix'],
         'strategy_parameters': {'historical_scenarios': ['2015_crash'], 'portfolio': {
             'as_of_date': '2026-11-13', 'currency': 'CNY', 'cash_weight': 0.2,
             'positions': [{'symbol': '600519', 'weight': 0.5}, {'symbol': '000858', 'weight': 0.3}]}}}]})
    plan.validate_analytics_dependencies()


def test_prompts_require_name_and_code_together():
    from src.orchestration.planner import _SYSTEM
    from src.specialists.market_data.nodes import _SYSTEM as MARKET
    assert "名称(代码)" in _SYSTEM and "优先只写名称" in _SYSTEM
    assert "名称(代码)" in MARKET and "symbol_mismatch" in MARKET


def test_planner_pins_user_windows_and_uses_closing_price_scenario_dates():
    from src.orchestration.planner import _SYSTEM
    assert "assumptions.window" in _SYSTEM and "近30日" in _SYSTEM
    for day in ("2007-10-16", "2008-11-04", "2015-06-12", "2015-08-26", "2020-01-13", "2020-03-23"):
        assert day in _SYSTEM
    assert "2008-10-28" not in _SYSTEM and "2020-03-19" not in _SYSTEM
