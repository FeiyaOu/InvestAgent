"""Exercise installed ChatTongyi adapter without a network request."""
import json
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.exceptions import OutputParserException

from src.llm import create_llm
from src.planner_schemas import TaskPlan, planner_output_schema
from src.stages.planner import _create_chain

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
    with patch('src.stages.planner.create_llm', return_value=model), patch.object(type(model), '_generate', generate):
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
    from src.stages.planner import planner
    monkeypatch.setenv('PLANNER_OUTPUT_MODE', 'tool_calling')
    model = create_llm(dashscope_api_key='test-key')
    replies = iter([AIMessage(content='plain text'), AIMessage(content='', tool_calls=[
        {'id': 'p2', 'name': 'TaskPlan', 'args': PAYLOAD}])])
    def generate(self, messages, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=next(replies))])
    with patch('src.stages.planner.create_llm', return_value=model), patch.object(type(model), '_generate', generate):
        result = planner({'user_query': '分析茅台表现'})
    assert result['planning_status'] == 'ready'
    assert result['planning_attempts'] == 2
    assert result['plan']['tasks'][1]['analytics_parameters']['assumptions']['missing_data'] == 'no_fill'
