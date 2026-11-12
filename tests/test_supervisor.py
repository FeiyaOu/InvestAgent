"""Supervisor dispatch is deterministic; specialists are mocked."""
from unittest.mock import Mock

from src.supervisor import create_supervisor_graph


def task(ident, category="market_data", deps=None):
    return {"task_id": ident, "category": category, "question": f"查询 {ident}", "depends_on": deps or []}


def plan(*tasks):
    return {"status": "ready", "tasks": list(tasks), "clarification_questions": []}


def market(answer="行情", status="completed"):
    return {"status": status, "result": {"answer": answer, "evidence_ids": [],
            "missing_information": ["缺数据"] if status == "partial" else [], "evidence": []}, "error": None}


def build(market_output=None, report_output=None):
    md = Mock(); md.invoke.return_value = market() if market_output is None else market_output
    report = Mock(); report.invoke.return_value = report_output
    return create_supervisor_graph(market_data_graph=md, report_graph=report), md, report


def test_dispatch_collect_and_isolate_results():
    graph, md, report = build()
    md.invoke.side_effect = [market("A"), market("B")]
    state = graph.invoke({"plan": plan(task("a"), task("b"))})
    assert state["supervisor_status"] == "completed"
    assert state["task_results"]["a"]["result"]["answer"] == "A"
    assert state["task_results"]["b"]["result"]["answer"] == "B"
    report.invoke.assert_not_called()


def test_dependency_order_and_partial_evidence_handoff():
    graph, md, _ = build()
    evidence = {"tool_call_id": "c", "tool_name": "lookup", "content": "quote", "retrieved_at": "now",
                "status": "returned", "data_mode": "real"}
    source = market(status="partial"); source["result"]["evidence"] = [evidence]
    md.invoke.side_effect = [source, market()]
    state = graph.invoke({"plan": plan(task("b", deps=["a"]), task("a"))})
    assert [call.args[0]["task"] for call in md.invoke.call_args_list] == ["查询 a", "查询 b"]
    assert md.invoke.call_args_list[1].args[0]["existing_evidence"] == [{**evidence, "tool_call_id": "a:c", "source_url": None, "as_of_date": None}]
    assert state["supervisor_status"] == "partial"


def test_unsupported_and_blocked_tasks_do_not_call_specialists():
    graph, md, _ = build()
    state = graph.invoke({"plan": plan(task("a", "investment_strategy"), task("b", deps=["a"]), task("s", "investment_strategy"))})
    assert state["task_results"]["a"]["status"] == "unsupported"
    assert state["task_results"]["b"]["status"] == "blocked"
    assert state["task_results"]["s"]["status"] == "unsupported"
    md.invoke.assert_not_called()


def test_exception_does_not_discard_other_success():
    graph, md, _ = build()
    md.invoke.side_effect = [RuntimeError("secret"), market()]
    state = graph.invoke({"plan": plan(task("a"), task("b"))})
    assert state["task_results"]["a"]["status"] == "failed"
    assert "secret" not in str(state["task_results"])
    assert state["task_results"]["b"]["status"] == "completed"


def test_invalid_plan_and_clarification_do_not_execute():
    graph, md, _ = build()
    state = graph.invoke({"plan": plan(task("a", deps=["x"]))})
    assert state["supervisor_status"] == "failed"
    assert state["task_results"] == {}
    state = graph.invoke({"plan": {"status": "needs_clarification", "tasks": [], "clarification_questions": ["哪个公司？"]}})
    assert state["supervisor_status"] == "needs_clarification"
    md.invoke.assert_not_called()


def test_report_adapter_preserves_intermediates_and_checks_report(valid_report):
    import json
    output = {"final_report": json.dumps(valid_report), "current_phase": "completed", "error": None,
              "validation_errors": [], "perception_data": {"raw": "data"}}
    graph, _, report = build(report_output=output)
    state = graph.invoke({"plan": plan(task("r", "report")), "report_parameters": {
        "r": {"research_topic": "新能源", "industry_focus": "光伏", "time_horizon": "未来一年"}}})
    record = state["task_results"]["r"]
    assert record["status"] == "completed"
    assert record["result"]["perception_data"] == {"raw": "data"}
    inputs = report.invoke.call_args.args[0]
    assert inputs["research_topic"] == "新能源"
    assert inputs["retry_count"] == 0


def test_report_return_is_not_automatically_success():
    for output in ({"final_report": "bad json", "current_phase": "completed"},
                   {"final_report": "{}", "current_phase": "completed"},
                   {"error": "report failed"}):
        graph, _, _ = build(report_output=output)
        state = graph.invoke({"plan": plan(task("r", "report"))})
        assert state["task_results"]["r"]["status"] != "completed"


def test_maximum_size_plan_terminates_and_new_run_clears_results():
    graph, md, _ = build()
    state = graph.invoke({"plan": plan(*(task(str(i)) for i in range(12)))})
    assert len(state["task_results"]) == 12
    state = graph.invoke({"plan": plan(task("new")), "task_results": state["task_results"]})
    assert set(state["task_results"]) == {"new"}


def test_malformed_specialist_result_is_failure():
    graph, _, _ = build(market_output={"status": "completed", "result": None})
    state = graph.invoke({"plan": plan(task("a"))})
    assert state["task_results"]["a"]["status"] == "failed"


def test_report_quality_warning_is_partial(valid_report):
    import json
    valid_report["sources"] = []
    graph, _, _ = build(report_output={"final_report": json.dumps(valid_report),
                                      "current_phase": "completed", "validation_errors": []})
    state = graph.invoke({"plan": plan(task("r", "report"))})
    record = state["task_results"]["r"]
    assert record["status"] == "partial"
    assert record["result"]["validation_errors"]


def test_malformed_report_preserves_node_outputs():
    graph, _, _ = build(report_output={"final_report": "bad json", "current_phase": "completed",
                                      "world_model": {"market_state": "test"}})
    state = graph.invoke({"plan": plan(task("r", "report"))})
    assert state["task_results"]["r"]["result"]["world_model"] == {"market_state": "test"}


def test_actual_subgraphs_can_execute_with_nested_config(valid_report):
    import json
    from unittest.mock import patch
    from contextlib import ExitStack
    from langchain_core.messages import AIMessage
    from src.market_data_agent import create_market_data_agent
    from src.report_graph import create_report_graph

    model = Mock()
    model.bind_tools.return_value = model
    model.invoke.return_value = AIMessage(content=json.dumps({"answer": "缺少行情数据", "evidence_ids": [],
                                                            "missing_information": ["无行情"]}))
    with ExitStack() as stack:
        stack.enter_context(patch("src.stages.market_data.create_llm", return_value=model))
        outputs = {"perception": {"perception_data": {}}, "modeling": {"world_model": {}},
                   "reasoning": {"reasoning_plans": []}, "decision": {"selected_plan": {}},
                   "report_generation": {"final_report": json.dumps(valid_report)},
                   "validator": {"current_phase": "completed", "validation_errors": []}}
        for name, output in outputs.items():
            stack.enter_context(patch(f"src.report_graph.{name}", Mock(return_value=output)))
        graph = create_supervisor_graph(market_data_graph=create_market_data_agent(tools=[]),
                                        report_graph=create_report_graph())
        events = list(graph.stream({"plan": plan(task("m"), task("r", "report"), task("r2", "report"))}, subgraphs=True))
    results = [update["supervisor"]["task_results"] for _, update in events if "supervisor" in update]
    assert results[-1]["m"]["status"] == "partial"
    assert results[-1]["r"]["status"] == "completed"
    assert results[-1]["r2"]["status"] == "completed"
    assert any(namespace and "perception" in update for namespace, update in events)


def test_market_failure_preserves_safe_error_code():
    graph, _, _ = build(market_output={"status": "failed", "result": None,
        "error": {"type": "invalid_output", "message": "输出格式或证据引用验证失败。"}})
    result = graph.invoke({"plan": plan(task("a"))})
    assert result["task_results"]["a"]["error"]["type"] == "invalid_output"
