"""Report subgraph preserves existing stage execution and validator routing."""
from contextlib import ExitStack
from unittest.mock import patch

from src.report_graph import create_report_graph
from src.agent import create_invest_agent


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
            stack.enter_context(patch("src.agent.assess_query", return_value={"processing_mode": "deliberative"}))
        graph = create_invest_agent() if parent else create_report_graph()
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
    config = {"configurable": {"thread_id": "nested"}}
    chunks = list(graph.stream({"retry_count": 0}, config=config, subgraphs=True))
    assert any(namespace and "perception" in update for namespace, update in chunks)
    state = graph.get_state(config).values
    assert state["selected_plan"] == {"selected_plan_id": "A"}
    assert state["current_phase"] == "completed"
    assert "report_workflow" in graph.get_graph().nodes
