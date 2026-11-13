"""Public entrypoint migration: C8 task categories and C9 nonempty response."""
from unittest.mock import Mock, patch
import pytest
from pydantic import ValidationError

from src.agent import create_invest_agent, run_invest_agent
from src.planner_schemas import PlanTask


@pytest.mark.parametrize("category", ["market_data", "analytics", "investment_strategy", "report"])
def test_c8_categories(category):
    assert PlanTask(task_id="t", category=category, question="查询", depends_on=[]).category == category


def test_c8_old_mode_is_not_category():
    with pytest.raises(ValidationError):
        PlanTask(task_id="t", category="reactive", question="查询", depends_on=[])


def test_entrypoint_is_parent_without_checkpoint_or_reactive_nodes():
    graph = create_invest_agent()
    nodes = graph.get_graph().nodes
    assert {"planner", "supervisor", "composer"} <= set(nodes)
    assert not {"assess", "reactive_agent", "tools", "extract_response"} & set(nodes)
    assert graph.checkpointer is None


def test_run_forwards_explicit_context_and_returns_parent_state():
    graph = Mock(); graph.invoke.return_value = {"final_response": "answer", "task_results": {}}
    with patch("src.agent.create_invest_agent", return_value=graph):
        result = run_invest_agent("查询", conversation_context="茅台", config={"tags": ["test"]})
    inputs = graph.invoke.call_args.args[0]
    assert inputs["conversation_context"] == "茅台"
    assert graph.invoke.call_args.kwargs["config"]["tags"] == ["test"]
    assert result["final_response"]
    assert "processing_mode" not in result


def test_c9_invalid_input_returns_readable_response_without_api():
    result = run_invest_agent(" ")
    assert result["composition_status"] == "failed"
    assert result["final_response"].strip()


def test_legacy_thread_id_not_silently_accepted():
    with pytest.raises(TypeError):
        run_invest_agent("查询", thread_id="not-memory")
