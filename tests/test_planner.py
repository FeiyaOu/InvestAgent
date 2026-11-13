"""Planner contract and node tests; no external calls."""
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from src.planner_schemas import TaskPlan
from src.stages.planner import planner


def task(ident="t1", category="market_data", deps=None):
    return {"task_id": ident, "category": category, "question": "查询茅台价格",
            "depends_on": [] if deps is None else deps}


def plan(tasks=None):
    return {"status": "ready", "tasks": [task()] if tasks is None else tasks,
            "clarification_questions": []}


@pytest.mark.parametrize("tasks", [
    [task(), task()], [task(deps=["missing"])], [task(deps=["t1"])],
    [task("a", deps=["b"]), task("b", deps=["a"])],
    [task(category="reactive")], [task(deps=["t2", "t2"]), task("t2")], [],
])
def test_reject_invalid_plans(tasks):
    with pytest.raises(ValidationError):
        TaskPlan.model_validate(plan(tasks))


def test_four_categories_and_forward_dependencies():
    tasks = [task("s", "investment_strategy", ["a"]), task("a", "analytics", ["d"]),
             task("d"), task("r", "report")]
    result = TaskPlan.model_validate(plan(tasks))
    assert len(result.tasks) == 4


@pytest.mark.parametrize("payload", [
    {"status": "needs_clarification", "tasks": [task()], "clarification_questions": ["哪个公司？"]},
    {"status": "needs_clarification", "tasks": [], "clarification_questions": []},
    {"status": "ready", "tasks": [task()], "clarification_questions": ["哪个公司？"]},
])
def test_status_contract(payload):
    with pytest.raises(ValidationError):
        TaskPlan.model_validate(payload)


def invoke(outputs, state=None, **kwargs):
    chain = Mock()
    chain.invoke.side_effect = outputs
    with patch("src.stages.planner._create_chain", return_value=chain):
        result = planner({"user_query": "查股价，比较估值并分析一年投资机会", **(state or {})}, **kwargs)
    return result, chain


def test_plans_mixed_query_without_executing_agents():
    payload = plan([task("d"), task("a", "analytics", ["d"]),
                    task("s", "investment_strategy", ["a"])])
    result, chain = invoke([payload])
    assert result["planning_status"] == "ready"
    assert result["plan"] == payload
    assert chain.invoke.call_count == 1


def test_report_and_lookup_remain_independent():
    payload = plan([task("d"), task("r", "report")])
    result, _ = invoke([payload])
    assert all(not t["depends_on"] for t in result["plan"]["tasks"])


def test_context_and_original_query_reach_model():
    result, chain = invoke([plan()], {"user_query": "它现在多少钱？", "conversation_context": "此前讨论贵州茅台"})
    inputs = chain.invoke.call_args.args[0]
    assert inputs["user_query"] == "它现在多少钱？"
    assert inputs["conversation_context"] == "此前讨论贵州茅台"
    assert result["planning_status"] == "ready"


def test_clarification_does_not_create_executable_tasks():
    result, _ = invoke([{"status": "needs_clarification", "tasks": [],
                         "clarification_questions": ["请问您指哪家公司？"]}])
    assert result["planning_status"] == "needs_clarification"
    assert result["plan"]["tasks"] == []


def test_invalid_plan_retries_with_validation_feedback():
    result, chain = invoke([plan([task(deps=["missing"])]), plan()])
    assert result["planning_status"] == "ready"
    assert result["planning_attempts"] == 2
    assert "missing" in chain.invoke.call_args.args[0]["correction"]


def test_exhausted_validation_returns_failure_without_plan():
    result, chain = invoke([{}, {}])
    assert result["planning_status"] == "failed"
    assert result["plan"] is None
    assert result["planning_error"]["type"] == "invalid_plan"
    assert chain.invoke.call_count == 2


def test_provider_failure_is_caught():
    result, chain = invoke([RuntimeError("secret provider details")])
    assert result["planning_error"]["type"] == "model_error"
    assert "secret" not in str(result)
    assert chain.invoke.call_count == 1


def test_empty_input_does_not_call_llm():
    result, chain = invoke([], {"user_query": " "})
    assert result["planning_error"]["type"] == "invalid_input"
    chain.invoke.assert_not_called()


def test_contract_rejects_whitespace_and_excess_tasks():
    payload = plan(); payload["tasks"][0]["question"] = "  "
    with pytest.raises(ValidationError):
        TaskPlan.model_validate(payload)
    with pytest.raises(ValidationError):
        TaskPlan.model_validate(plan([task(str(i)) for i in range(13)]))


def test_real_chain_parses_mock_model_json_and_repairs_malformed_json(monkeypatch):
    monkeypatch.setenv("PLANNER_OUTPUT_MODE", "json")
    import json
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda

    prompts = []
    replies = iter(["not json", json.dumps(plan())])
    def respond(prompt):
        prompts.append(prompt.to_messages())
        return AIMessage(content=next(replies))
    with patch("src.stages.planner.create_llm", return_value=RunnableLambda(respond)):
        result = planner({"user_query": "茅台现在多少钱？"})
    assert result["planning_status"] == "ready"
    assert len(prompts) == 2
    assert "json模式" in prompts[1][-1].content
    assert "report" in prompts[0][0].content


def test_planner_can_be_registered_as_graph_node():
    from langgraph.graph import START, END, StateGraph
    from src.planner_schemas import PlannerState

    graph = StateGraph(PlannerState)
    graph.add_node("planner", planner)
    graph.add_edge(START, "planner")
    graph.add_edge("planner", END)
    with patch("src.stages.planner._create_chain") as factory:
        factory.return_value.invoke.return_value = plan()
        result = graph.compile().invoke({"user_query": "茅台价格"})
    assert result["planning_status"] == "ready"
    assert result["user_query"] == "茅台价格"


def test_no_retry_when_disabled_and_stale_plan_is_cleared():
    result, chain = invoke([{}], {"plan": plan(), "planning_status": "ready"}, max_retries=0)
    assert result["plan"] is None
    assert chain.invoke.call_count == 1


def test_analytics_plan_without_data_predecessor_is_repaired():
    result, chain = invoke([plan([task("a", "analytics")]),
                          plan([task("d"), task("a", "analytics", ["d"])])])
    assert result["planning_status"] == "ready"
    assert result["planning_attempts"] == 2
    assert "analytics" in chain.invoke.call_args.args[0]["correction"]


def test_analytics_cannot_use_report_as_its_only_data_dependency():
    result, _ = invoke([plan([task("r", "report"), task("a", "analytics", ["r"])])], max_retries=0)
    assert result["planning_status"] == "failed"


def test_structured_analytics_parameters_survive_plan_validation():
    analytical = task("a", "analytics", ["d"])
    analytical["analytics_parameters"] = {"subjects": ["600519"], "time_range": "2025-01-01至2025-12-31",
        "assumptions": {"window": 20, "periods_per_year": 252}}
    result, _ = invoke([plan([task("d"), analytical])])
    params = result["plan"]["tasks"][1]["analytics_parameters"]
    assert params["subjects"] == ["600519"]
    assert params["assumptions"]["window"] == 20


def test_report_task_rejects_analytics_parameters():
    report = task("r", "report")
    report["analytics_parameters"] = {"subjects": ["600519"]}
    result, _ = invoke([plan([report])], max_retries=0)
    assert result["planning_status"] == "failed"


def test_planner_prompt_provides_current_date_and_collection_rules(monkeypatch):
    monkeypatch.setenv("PLANNER_OUTPUT_MODE", "json")
    import json
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda
    prompts = []
    def respond(prompt):
        prompts.append(prompt.to_messages())
        return AIMessage(content=json.dumps(plan()))
    with patch("src.stages.planner.create_llm", return_value=RunnableLambda(respond)):
        result = planner({"user_query": "茅台股价"})
    assert result["planning_status"] == "ready"
    assert "get_price_history" in prompts[0][0].content
    assert "get_valuation_snapshot" in prompts[0][0].content
    assert "当前上海日期" in prompts[0][-1].content


def test_invalid_plan_exposes_field_and_constraint_without_input_value():
    bad = plan()
    bad['tasks'][0]['category'] = 'private-invalid-category'
    result, _ = invoke([bad, bad])
    message = result['planning_error']['message']
    assert 'tasks.0.category' in message
    assert 'private-invalid-category' not in message
    assert '缩小' not in message


def test_mixed_performance_valuation_repair_preserves_separate_dependencies():
    tasks = [task('prices'), task('valuations'), task('performance', 'analytics', ['prices']),
             task('comparison', 'analytics', ['valuations'])]
    tasks[0]['question'] = '获取600519和000858过去一年qfq日线'
    tasks[1]['question'] = '获取600519和000858最新估值快照'
    bad = plan([task('a', 'analytics')])
    result, chain = invoke([bad, plan(tasks)], {'user_query': '比较茅台和五粮液过去一年收益、波动率、回撤及最新PE TTM和PB'})
    assert result['planning_status'] == 'ready'
    assert result['plan']['tasks'][2]['depends_on'] == ['prices']
    assert result['plan']['tasks'][3]['depends_on'] == ['valuations']
    assert 'analytics' in chain.invoke.call_args.args[0]['correction']


def test_optional_null_assumptions_use_defaults():
    analysis = task('a', 'analytics', ['d'])
    analysis['analytics_parameters'] = {'subjects': ['600519'], 'assumptions': None}
    result, _ = invoke([plan([task('d'), analysis])])
    assert result['planning_status'] == 'ready'
    assert result['plan']['tasks'][1]['analytics_parameters']['assumptions'] == {'missing_data': 'no_fill'}


def test_string_assumptions_are_still_rejected():
    analysis = task('a', 'analytics', ['d'])
    analysis['analytics_parameters'] = {'assumptions': 'qfq'}
    with pytest.raises(ValidationError):
        TaskPlan.model_validate(plan([task('d'), analysis]))


def test_planner_emits_failure_and_recovery_events_for_each_attempt():
    bad = plan()
    bad['tasks'][0]['category'] = 'bad'
    events = []
    with patch('src.stages.planner.get_stream_writer', return_value=events.append):
        result, _ = invoke([bad, plan()])
    assert result['planning_status'] == 'ready'
    assert [e['status'] for e in events] == ['started', 'validation_failed', 'started', 'ready']
    assert events[1]['diagnostics'][0]['field'] == 'tasks.0.category'
    assert len({e['run_id'] for e in events}) == 1
    assert events[-1]['attempt'] == 2


def test_exhausted_planning_attempts_keep_both_diagnostics():
    bad = plan()
    bad['tasks'][0]['category'] = 'bad'
    events = []
    with patch('src.stages.planner.get_stream_writer', return_value=events.append):
        result, _ = invoke([bad, bad])
    assert result['planning_status'] == 'failed'
    assert [e['attempt'] for e in events if e['status'] == 'validation_failed'] == [1, 2]
    assert events[-1]['status'] == 'failed'


def test_explicit_report_request_repairs_plan_missing_report_category():
    query='请生成新能源行业未来一年的投研报告，重点关注光伏。'
    wrong=plan([task('d'),task('a','analytics',['d']),task('s','investment_strategy',['a'])])
    result,chain=invoke([wrong,plan([task('r','report')])],{'user_query':query})
    assert result['planning_status']=='ready' and result['planning_attempts']==2
    assert result['plan']['tasks'][0]['category']=='report'
    assert 'report' in chain.invoke.call_args.args[0]['correction']


def test_report_intent_mismatch_never_executes_wrong_ready_plan():
    result,_=invoke([plan(),plan()],{'user_query':'请生成光伏行业投研报告'})
    assert result['planning_status']=='failed' and result['plan'] is None
    assert 'report_intent' in result['planning_error']['message']


def test_explicit_no_report_rejects_report_but_analysis_is_allowed():
    result,_=invoke([plan([task('r','report')]),plan()],{'user_query':'分析光伏风险，不要生成完整报告。'})
    assert result['planning_status']=='ready' and result['planning_attempts']==2


@pytest.mark.parametrize('query,expected',[
    ('请生成新能源行业未来一年的投研报告，重点关注光伏。','requested'),
    ('分析投资机会，不要生成完整报告。','forbidden'),
    ('不用查询价格，请生成光伏行业投研报告。','requested'),
    ('请解释如何生成投研报告。','unspecified'),
    ('比较两家公司估值并分析机会。','unspecified'),
    ('暂不生成报告，先查价格。','forbidden'),
])
def test_explicit_report_intent_handles_negation_and_explanation(query,expected):
    from src.report_intent import explicit_report_intent
    assert explicit_report_intent(query)==expected
