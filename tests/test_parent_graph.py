"""Full parent graph, using existing nodes and mocked external services."""
from unittest.mock import Mock, patch

from src.parent_graph import create_parent_graph


def task(ident="m", category="market_data", deps=None):
    return {"task_id": ident, "category": category, "question": "查询茅台价格", "depends_on": deps or []}


def plan(*tasks):
    return {"status": "ready", "tasks": list(tasks) or [task()], "clarification_questions": []}


def market():
    graph = Mock()
    graph.invoke.return_value = {"status": "completed", "error": None, "result": {
        "answer": "100元", "evidence_ids": [], "evidence": [], "missing_information": []}}
    return graph


def execute(payload, inputs=None):
    md, report = market(), Mock()
    planning, composing = Mock(), Mock()
    planning.invoke.return_value = payload
    composing.invoke.return_value = {"answer": "查询到价格100元。"}
    graph = create_parent_graph(market_data_graph=md, report_graph=report)
    with patch("src.stages.planner._create_chain", return_value=planning), patch(
            "src.stages.composer._create_chain", return_value=composing):
        result = graph.invoke(inputs or {"user_query": "查茅台价格"})
    return result, md, report, planning, composing


def test_user_input_to_answer_with_strict_child_boundary():
    result, md, report, planning, composing = execute(plan(), {"user_query": "它多少钱？", "conversation_context": "贵州茅台"})
    assert result["planning_status"] == "ready"
    assert result["supervisor_status"] == "completed"
    assert result["composition_status"] == "completed"
    assert "100元" in result["final_response"]
    assert planning.invoke.call_args.args[0]["conversation_context"] == "贵州茅台"
    assert not {"messages", "last_task_id", "retry_count", "current_phase", "final_report"} & result.keys()
    report.invoke.assert_not_called()


def test_clarification_skips_supervisor_and_model_composition():
    result, md, report, _, composing = execute({"status": "needs_clarification", "tasks": [],
                                               "clarification_questions": ["哪家公司？"]})
    assert result["supervisor_status"] is None
    assert result["composition_status"] == "needs_clarification"
    assert "哪家公司" in result["final_response"]
    md.invoke.assert_not_called(); report.invoke.assert_not_called(); composing.invoke.assert_not_called()


def test_invalid_plan_skips_execution_and_returns_readable_failure():
    result, md, _, _, composing = execute({})
    assert result["planning_status"] == "failed"
    assert result["composition_status"] == "failed"
    assert result["final_response"]
    assert result["task_results"] == {}
    md.invoke.assert_not_called(); composing.invoke.assert_not_called()


def test_invalid_user_input_does_not_call_models():
    result, md, _, planning, composing = execute(plan(), {"user_query": " "})
    assert result["planning_error"]["type"] == "invalid_input"
    assert result["final_response"]
    md.invoke.assert_not_called(); planning.invoke.assert_not_called(); composing.invoke.assert_not_called()


def test_mixed_tasks_keep_success_and_strategy_missing_evidence():
    result, _, _, _, _ = execute(plan(task(), task("a", "investment_strategy", ["m"])))
    assert result["supervisor_status"] == "partial"
    assert result["task_results"]["a"]["status"] == "partial"
    assert "缺少" in result["final_response"]


def test_stale_outputs_are_reset_and_graph_has_no_checkpointer():
    result, _, _, _, _ = execute(plan(), {"user_query": "查询", "final_response": "OLD",
        "task_results": {"old": {}}, "plan": plan(task("old")), "composition_error": {"old": True}})
    assert set(result["task_results"]) == {"m"}
    assert "OLD" not in result["final_response"]
    assert result["composition_error"] is None
    assert create_parent_graph().checkpointer is None


def test_report_state_stays_in_task_payload_and_is_not_composed(valid_report):
    import json
    report = Mock()
    report.invoke.return_value = {"current_phase": "completed", "error": None,
        "final_report": json.dumps(valid_report), "perception_data": {"detail": "kept"}}
    planning = Mock(); planning.invoke.return_value = plan(task("r", "report"))
    with patch("src.stages.planner._create_chain", return_value=planning), patch(
            "src.stages.composer._create_chain") as composing:
        result = create_parent_graph(market_data_graph=market(), report_graph=report).invoke({
            "user_query": "生成新能源报告", "report_parameters": {"r": {"industry_focus": "光伏"}}})
    assert result["task_results"]["r"]["result"]["perception_data"] == {"detail": "kept"}
    assert "报告阅读" in result["final_response"]
    composing.assert_not_called()


def test_stream_exposes_task_progress_and_composition():
    md = market()
    planning = Mock(); planning.invoke.return_value = plan()
    composing = Mock(); composing.invoke.return_value = {"answer": "100元"}
    graph = create_parent_graph(market_data_graph=md, report_graph=Mock())
    with patch("src.stages.planner._create_chain", return_value=planning), patch(
            "src.stages.composer._create_chain", return_value=composing):
        events = list(graph.stream({"user_query": "茅台价格"}, subgraphs=True))
    assert any(not namespace and "planner" in update for namespace, update in events)
    assert any(namespace and "supervisor" in update for namespace, update in events)
    assert any(not namespace and "composer" in update for namespace, update in events)


def test_reused_parent_graph_does_not_keep_previous_request():
    planning = Mock(); planning.invoke.side_effect = [plan(task("old")), plan(task("new"))]
    composing = Mock(); composing.invoke.return_value = {"answer": "100元"}
    graph = create_parent_graph(market_data_graph=market(), report_graph=Mock())
    with patch("src.stages.planner._create_chain", return_value=planning), patch(
            "src.stages.composer._create_chain", return_value=composing):
        first = graph.invoke({"user_query": "第一问"})
        second = graph.invoke({"user_query": "第二问"})
    assert set(first["task_results"]) == {"old"}
    assert set(second["task_results"]) == {"new"}


def test_dataset_store_is_per_request_not_state_or_global():
    from src.datasets import DatasetStore
    md = market()
    planning = Mock(); planning.invoke.return_value = plan()
    composing = Mock(); composing.invoke.return_value = {"answer": "100元"}
    graph = create_parent_graph(market_data_graph=md, report_graph=Mock())
    with patch("src.stages.planner._create_chain", return_value=planning), patch(
            "src.stages.composer._create_chain", return_value=composing):
        a = graph.invoke({"user_query": "第一次"})
        b = graph.invoke({"user_query": "第二次"})
    stores = [call.kwargs["config"]["configurable"]["dataset_store"] for call in md.invoke.call_args_list]
    assert all(isinstance(store, DatasetStore) for store in stores)
    assert stores[0] is not stores[1]
    assert "dataset_store" not in a and "dataset_store" not in b


def test_report_intent_repair_dispatches_report_without_executing_rejected_data_plan(valid_report):
    import json
    md, report=market(),Mock()
    report.invoke.return_value={'current_phase':'completed','error':None,'final_report':json.dumps(valid_report)}
    planning=Mock();planning.invoke.side_effect=[plan(task()),plan(task('r','report'))]
    with patch('src.stages.planner._create_chain',return_value=planning):
        result=create_parent_graph(market_data_graph=md,report_graph=report).invoke(
            {'user_query':'请生成新能源行业未来一年的投研报告，重点关注光伏。'})
    assert result['planning_attempts']==2
    assert result['task_results']['r']['status']=='completed'
    md.invoke.assert_not_called()
    report.invoke.assert_called_once()
