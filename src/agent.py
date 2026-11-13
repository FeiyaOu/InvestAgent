"""Public entrypoints for the request-local Planner/Supervisor/Composer graph.

Legacy processing_mode, top-level report outputs and automatic thread memory
are no longer part of this API. Report internals remain in report_graph.py.
"""
from langchain_core.runnables import RunnableConfig

from src.parent_graph import create_parent_graph


def create_invest_agent():
    """Return the canonical parent graph, without a private checkpointer."""
    return create_parent_graph()


def run_invest_agent(user_query: str, *, conversation_context: str = "",
                     report_parameters: dict | None = None,
                     config: RunnableConfig | None = None) -> dict:
    """Run a fresh request; callers explicitly supply conversation context.

    Config controls callbacks/tags, not automatic conversation persistence.
    """
    return create_invest_agent().invoke({
        "user_query": user_query, "conversation_context": conversation_context,
        "report_parameters": {} if report_parameters is None else report_parameters,
    }, config=config)
