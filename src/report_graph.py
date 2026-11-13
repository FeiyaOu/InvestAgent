"""Report subgraph: preserve the existing Deliberative nodes and routing."""
from typing import Any

from langgraph.graph import END, StateGraph

from src.stages.decision import decision
from src.stages.modeling import modeling
from src.stages.perception import perception
from src.stages.reasoning import reasoning
from src.stages.reporter import report_generation
from src.stages.validator import validator
from src.state import InvestAgentState


def route_after_validator(state: InvestAgentState) -> str:
    """validator 节点后的路由：retry → decision，通过 → END
    这是有向环②的控制函数。
    """
    if state.get("current_phase") == "decision":
        return "decision"
    return END


def create_report_graph() -> Any:
    """Compile without a private checkpointer; inherit persistence from the parent."""
    workflow = StateGraph(InvestAgentState)
    workflow.add_node("perception", perception)
    workflow.add_node("modeling", modeling)
    workflow.add_node("reasoning", reasoning)
    workflow.add_node("decision", decision)
    workflow.add_node("report", report_generation)
    workflow.add_node("validator", validator)
    workflow.set_entry_point("perception")
    workflow.add_edge("perception", "modeling")
    workflow.add_edge("modeling", "reasoning")
    workflow.add_edge("reasoning", "decision")
    workflow.add_edge("decision", "report")
    workflow.add_edge("report", "validator")
    workflow.add_conditional_edges(
        "validator", route_after_validator, {"decision": "decision", END: END},
    )
    return workflow.compile()
