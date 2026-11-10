"""Request-local Planner → Supervisor → Composer parent graph."""
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from src.parent_state import ParentState, create_parent_state
from src.planner_schemas import TaskPlan
from src.stages.composer import composer
from src.stages.planner import planner
from src.supervisor import create_supervisor_graph
from src.task_contracts import validate_task_results


def _initialize(state: ParentState) -> dict:
    try:
        return create_parent_state(state.get("user_query"),
            conversation_context=state.get("conversation_context", ""),
            report_parameters=state.get("report_parameters"))
    except ValidationError:
        # Clear every previous execution output even when input validation fails.
        clean = create_parent_state("无效输入")
        return {**clean, "user_query": "", "planning_status": "failed",
                "planning_error": {"type": "invalid_input", "message": "请输入非空问题，并检查上下文和报告参数格式。"}}


def create_parent_graph(*, market_data_graph=None, report_graph=None):
    """Build a stateless parent; callers provide conversation context explicitly.

    invoke({"user_query": ...}) runs the full pipeline. stream(...,
    subgraphs=True) exposes execution progress. No legacy UI switch is made.
    """
    execution = create_supervisor_graph(market_data_graph=market_data_graph, report_graph=report_graph)

    def supervise(state: ParentState, config: RunnableConfig) -> dict:
        try:
            output = execution.invoke({"plan": state["plan"],
                                       "report_parameters": state["report_parameters"]}, config=config)
            results = validate_task_results(output["task_results"])
            planned = {task["task_id"]: task for task in state["plan"]["tasks"]}
            # Validate identities against this plan, not only the result-map keys.
            for ident, result in results.items():
                if ident not in planned or any(result[key] != value for key, value in planned[ident].items()):
                    raise ValueError("任务结果与本轮计划不一致")
            if output["supervisor_status"] in {"completed", "partial"} and set(results) != set(planned):
                raise ValueError("缺少终止任务结果")
            return {"task_results": results, "supervisor_status": output["supervisor_status"],
                    "supervisor_error": output["supervisor_error"]}
        except Exception:
            return {"task_results": {}, "supervisor_status": "failed",
                    "supervisor_error": {"type": "execution_error", "message": "任务执行边界异常，请重试。"}}

    def plan(state: ParentState) -> dict:
        update = planner(state)
        if update["planning_status"] in {"ready", "needs_clarification"}:
            # The existing planner already validates; keep the graph boundary explicit.
            checked = TaskPlan.model_validate(update["plan"])
            return {**update, "plan": checked.model_dump()}
        return update

    graph = StateGraph(ParentState)
    graph.add_node("initialize", _initialize)
    graph.add_node("planner", plan)
    graph.add_node("supervisor", supervise)
    graph.add_node("composer", composer)
    graph.add_edge(START, "initialize")
    graph.add_conditional_edges("initialize", lambda s: "composer" if s["planning_status"] == "failed" else "planner",
                                {"composer": "composer", "planner": "planner"})
    graph.add_conditional_edges("planner", lambda s: "supervisor" if s["planning_status"] == "ready" else "composer",
                                {"supervisor": "supervisor", "composer": "composer"})
    graph.add_edge("supervisor", "composer")
    graph.add_edge("composer", END)
    return graph.compile()
