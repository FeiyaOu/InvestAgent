"""Independent Analytics LangGraph subgraph; no parent dispatch/UI integration yet."""
from langgraph.graph import END, START, StateGraph

from src.specialists.analytics.nodes import (
    initialize,
    make_agent_node,
    make_finalize_node,
    make_tools_node,
)
from src.specialists.analytics.state import AnalyticsState
from src.specialists.analytics.tools import (
    analyze_price_performance,
    build_return_matrix,
    compare_valuations,
    compare_with_benchmark,
    compute_factors,
    rank_peers,
)

ANALYTICS_TOOLS = [analyze_price_performance, compare_with_benchmark, compute_factors, compare_valuations,
                   build_return_matrix, rank_peers]


def create_analytics_agent(*, max_tool_rounds: int = 3, max_tool_calls: int = 8, max_output_retries: int = 1):
    """Explicit dataset/analysis stores must be provided via RunnableConfig.

    Budget bounds calls, not wall-clock time; no private checkpoint is installed.
    """
    for value, upper in ((max_tool_rounds, 5), (max_tool_calls, 20), (max_output_retries, 2)):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= upper:
            raise ValueError("执行预算超出允许范围")
    graph = StateGraph(AnalyticsState)
    graph.add_node("initialize", initialize)
    graph.add_node("agent", make_agent_node(ANALYTICS_TOOLS, max_tool_rounds, max_tool_calls))
    graph.add_node("tools", make_tools_node(ANALYTICS_TOOLS))
    graph.add_node("finalize", make_finalize_node(max_output_retries))
    graph.add_edge(START, "initialize")
    graph.add_conditional_edges("initialize", lambda s: "agent" if s["status"] == "running" else "end",
                                {"agent": "agent", "end": END})
    graph.add_conditional_edges("agent", lambda s: "end" if s["status"] == "failed" else
                                "tools" if s["messages"][-1].tool_calls else "finalize",
                                {"end": END, "tools": "tools", "finalize": "finalize"})
    graph.add_conditional_edges("tools", lambda s: "end" if s["status"] == "failed" else "agent",
                                {"end": END, "agent": "agent"})
    graph.add_conditional_edges("finalize", lambda s: "agent" if s["status"] == "running" else "end",
                                {"end": END, "agent": "agent"})
    return graph.compile()
