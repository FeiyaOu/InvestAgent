"""Independent Supervisor → Composer execution graph, accepting an existing plan."""
from langgraph.graph import END, START, StateGraph

from src.composer_state import ResponseState
from src.stages.composer import composer
from src.supervisor import create_supervisor_graph


def create_response_graph(*, market_data_graph=None, report_graph=None):
    """No planner, private checkpointer, or Streamlit entrypoint switch yet."""
    graph = StateGraph(ResponseState)
    graph.add_node("execution", create_supervisor_graph(
        market_data_graph=market_data_graph, report_graph=report_graph))
    graph.add_node("composer", composer)
    graph.add_edge(START, "execution")
    graph.add_edge("execution", "composer")
    graph.add_edge("composer", END)
    return graph.compile()
