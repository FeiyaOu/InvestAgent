"""Report subgraph preserves existing stage execution and validator routing."""
from contextlib import ExitStack
from unittest.mock import patch

from src.report_graph import create_report_graph
from src.parent_graph import create_parent_graph


def build(retries=0, parent=False):
    events = []
    def stage(name, output):
        def node(state):
            events.append(name)
            return output(state) if callable(output) else output
        return node
    nodes = {
        "perception": {"perception_data": {"market_overview": "data"}},
        "modeling": {"world_model": {"market_state": "model"}},
        "reasoning": {"reasoning_plans": [{"plan_id": "A"}]},
        "decision": {"selected_plan": {"selected_plan_id": "A"}},
        "report_generation": {"final_report": '{"report": "unchanged"}'},
        "validator": lambda s: {"retry_count": s.get("retry_count", 0) + 1,
            "current_phase": "decision" if s.get("retry_count", 0) < retries else "completed"},
    }
    with ExitStack() as stack:
        for name, output in nodes.items():
            stack.enter_context(patch(f"src.report_graph.{name}", stage(name, output)))
        if parent:
            factory = stack.enter_context(patch("src.stages.planner._create_chain"))
            factory.return_value.invoke.return_value = {"status": "ready", "tasks": [
                {"task_id": "r", "category": "report", "question": "生成新能源报告", "depends_on": []}],
                "clarification_questions": []}
        graph = create_parent_graph() if parent else create_report_graph()
    return graph, events


def test_standalone_preserves_stage_order_and_outputs():
    graph, events = build()
    result = graph.invoke({"research_topic": "新能源", "retry_count": 0})
    assert events == ["perception", "modeling", "reasoning", "decision", "report_generation", "validator"]
    assert result["final_report"] == '{"report": "unchanged"}'
    assert result["perception_data"]["market_overview"] == "data"
    assert graph.checkpointer is None


def test_retry_repeats_only_decision_report_validator():
    graph, events = build(retries=2)
    graph.invoke({"retry_count": 0})
    assert events == ["perception", "modeling", "reasoning"] + ["decision", "report_generation", "validator"] * 3


def test_parent_exposes_nested_updates_and_final_state():
    graph, events = build(parent=True)
    from unittest.mock import Mock
    chain = Mock()
    chain.invoke.return_value = {"status": "ready", "tasks": [
        {"task_id": "r", "category": "report", "question": "生成报告", "depends_on": []}],
        "clarification_questions": []}
    with patch("src.stages.planner._create_chain", return_value=chain):
        chunks = list(graph.stream({"user_query": "生成报告"}, subgraphs=True))
    assert any(namespace and "perception" in update for namespace, update in chunks)
    update = next(update["supervisor"] for namespace, update in chunks if not namespace and "supervisor" in update)
    payload = update["task_results"]["r"]["result"]
    assert payload["selected_plan"] == {"selected_plan_id": "A"}
    assert payload["current_phase"] == "completed"
    assert "supervisor" in graph.get_graph().nodes
