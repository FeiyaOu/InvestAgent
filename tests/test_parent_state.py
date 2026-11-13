"""Parent/child boundary contracts, without building the parent graph."""
import pytest
from pydantic import ValidationError

from src.parent_state import create_parent_state, validate_task_results
from src.task_contracts import TaskResult


def record(**overrides):
    return {"task_id": "m", "category": "market_data", "question": "查询茅台价格", "depends_on": [],
            "status": "completed", "result": {"answer": "100元"}, "error": None, **overrides}


def test_parent_request_initializes_fresh_outputs_and_preserves_only_inputs():
    one = create_parent_state("查行情", conversation_context="此前讨论茅台")
    one["task_results"]["m"] = record()
    one["plan"] = {"old": True}
    two = create_parent_state("生成报告", conversation_context="此前讨论茅台")
    assert two["task_results"] == {}
    assert two["plan"] is None
    assert two["final_response"] is None
    assert two["conversation_context"] == "此前讨论茅台"
    assert not {"messages", "retry_count", "current_phase", "final_report", "last_task_id"} & two.keys()


def test_parent_input_and_report_parameters_are_validated_and_copied():
    params = {"r": {"industry_focus": "光伏"}}
    state = create_parent_state("生成光伏报告", report_parameters=params)
    params["r"]["industry_focus"] = "changed"
    assert state["report_parameters"]["r"]["industry_focus"] == "光伏"
    for query in (" ", None, 123):
        with pytest.raises(ValidationError):
            create_parent_state(query)
    with pytest.raises(ValidationError):
        create_parent_state("查询", report_parameters={"r": {"unexpected": True}})


@pytest.mark.parametrize("updates", [
    {"status": "completed", "result": None},
    {"status": "partial", "result": None},
    {"status": "failed", "error": None},
    {"status": "unsupported", "result": {}},
    {"status": "running"}, {"category": "reactive"},
    {"error": {"type": "bad", "message": "bad"}},
])
def test_task_result_rejects_inconsistent_terminal_records(updates):
    with pytest.raises(ValidationError):
        TaskResult.model_validate(record(**updates))


def test_failed_report_can_retain_intermediate_outputs():
    result = TaskResult.model_validate(record(category="report", status="failed",
        result={"perception_data": {"data": "kept"}}, error={"type": "report_failed", "message": "失败"}))
    assert result.result["perception_data"]["data"] == "kept"


def test_result_map_validates_keys_without_mutating_input():
    raw = {"m": record()}
    parsed = validate_task_results(raw)
    parsed["m"]["result"]["answer"] = "changed"
    assert raw["m"]["result"]["answer"] == "100元"
    with pytest.raises(ValueError):
        validate_task_results({"wrong": record()})


def test_existing_planner_supervisor_composer_accept_parent_fields():
    from unittest.mock import Mock, patch
    from src.stages.planner import planner
    from src.supervisor import create_supervisor_graph
    from src.stages.composer import composer

    state = create_parent_state("茅台最新价格")
    planned = {"status": "ready", "tasks": [{k: v for k, v in record().items()
                if k in {"task_id", "category", "question", "depends_on"}}], "clarification_questions": []}
    chain = Mock(); chain.invoke.return_value = planned
    with patch("src.stages.planner._create_chain", return_value=chain):
        state.update(planner(state))
    md = Mock(); md.invoke.return_value = {"status": "completed", "error": None, "result": {
        "answer": "100元", "evidence_ids": [], "evidence": [], "missing_information": []}}
    executed = create_supervisor_graph(market_data_graph=md, report_graph=Mock()).invoke({
        "plan": state["plan"], "report_parameters": state["report_parameters"]})
    # Only the documented boundary fields cross from execution into parent state.
    state.update({key: executed[key] for key in ("task_results", "supervisor_status", "supervisor_error")})
    chain.invoke.return_value = {"answer": "茅台价格100元。"}
    with patch("src.stages.composer._create_chain", return_value=chain):
        state.update(composer(state))
    assert state["composition_status"] == "completed"
    assert "100元" in state["final_response"]
    assert "last_task_id" not in state
    assert TaskResult.model_validate(state["task_results"]["m"]).status == "completed"
