"""Independent Market Data subgraph factory; report workflow remains unchanged."""
from langgraph.graph import END, START, StateGraph

from src.market_data_state import MarketDataState
from src.stages.market_data import (
    initialize, make_agent_node, make_finalize_node, make_tools_node,
)
from src.tools import INVEST_TOOLS, get_price_history


def create_market_data_agent(*, tools=None, max_tool_rounds: int = 3,
                             max_tool_calls: int = 8, max_output_retries: int = 1):
    """Build a local task graph. Stream updates via graph.stream(...).

    No private checkpointer: the future parent controls persistence.
    Budgets bound calls, not elapsed time of synchronous provider requests.
    """
    if max_tool_rounds < 0 or max_tool_calls < 0 or max_output_retries < 0:
        raise ValueError("执行预算不得为负数")
    tools = list([*INVEST_TOOLS, get_price_history] if tools is None else tools)
    graph = StateGraph(MarketDataState)
    graph.add_node("initialize", initialize)
    graph.add_node("agent", make_agent_node(tools, max_tool_rounds, max_tool_calls))
    graph.add_node("tools", make_tools_node(tools))
    graph.add_node("finalize", make_finalize_node(max_output_retries))
    graph.add_edge(START, "initialize")
    graph.add_conditional_edges("initialize", lambda s: "end" if s["status"] == "failed" else "agent",
                                {"end": END, "agent": "agent"})
    graph.add_conditional_edges("agent", lambda s: "end" if s["status"] == "failed" else
                                "tools" if s["messages"][-1].tool_calls else "finalize",
                                {"end": END, "tools": "tools", "finalize": "finalize"})
    graph.add_conditional_edges("tools", lambda s: "end" if s["status"] == "failed" else "agent",
                                {"end": END, "agent": "agent"})
    graph.add_conditional_edges("finalize", lambda s: "agent" if s["status"] == "running" else "end",
                                {"agent": "agent", "end": END})
    return graph.compile()
