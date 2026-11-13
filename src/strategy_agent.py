"""Explicit Strategy/Risk LangGraph subgraph with a bounded ToolNode loop."""
from langgraph.graph import StateGraph, START, END
from src.strategy_state import StrategyState
from src.strategy_tools import evaluate_risk_constraints, stress_test_portfolio
from src.stages.strategy import initialize, make_agent_node, make_tools_node, make_finalize_node

STRATEGY_TOOLS=[evaluate_risk_constraints,stress_test_portfolio]


def create_strategy_agent(*,max_tool_rounds=3,max_tool_calls=12,max_output_retries=1):
    for value,upper in ((max_tool_rounds,5),(max_tool_calls,20),(max_output_retries,2)):
        if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=upper:
            raise ValueError('策略预算超出范围')
    graph=StateGraph(StrategyState)
    graph.add_node('initialize',initialize)
    graph.add_node('agent',make_agent_node(STRATEGY_TOOLS,max_tool_rounds,max_tool_calls))
    graph.add_node('tools',make_tools_node(STRATEGY_TOOLS))
    graph.add_node('finalize',make_finalize_node(max_output_retries))
    graph.add_edge(START,'initialize')
    graph.add_conditional_edges('initialize',lambda s:'agent' if s['status']=='running' else 'end',{'agent':'agent','end':END})
    graph.add_conditional_edges('agent',lambda s:'end' if s['status']!='running' else 'tools' if s['messages'][-1].tool_calls else 'finalize',
        {'end':END,'tools':'tools','finalize':'finalize'})
    graph.add_conditional_edges('tools',lambda s:'end' if s['status']!='running' else 'agent',{'end':END,'agent':'agent'})
    graph.add_conditional_edges('finalize',lambda s:'agent' if s['status']=='running' else 'end',{'agent':'agent','end':END})
    return graph.compile()
