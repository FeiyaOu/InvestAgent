"""Deterministic supervisor; no planner, composer, or UI entrypoint changes."""
import json
from copy import deepcopy

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.config import get_stream_writer
from pydantic import ValidationError

from src.analytics_agent import create_analytics_agent
from src.analytics_handoff import analytics_inputs, analytics_result
from src.market_data_agent import create_market_data_agent
from src.market_data_state import MarketDataResult
from src.planner_schemas import TaskPlan
from src.report_graph import create_report_graph
from src.stages.reporter import validate_report
from src.supervisor_state import ReportParameters, SupervisorState
from src.task_contracts import TaskResult, TaskError


def _error(kind, message):
    return {"type": kind, "message": message}


def _initialize(state: SupervisorState) -> dict:
    clean = {"task_results": {}, "last_task_id": None, "supervisor_error": None}
    try:
        plan = TaskPlan.model_validate(state.get("plan"))
        params = {key: ReportParameters.model_validate(value).model_dump()
                  for key, value in state.get("report_parameters", {}).items()}
        report_ids = {task.task_id for task in plan.tasks if task.category == "report"}
        if not set(params) <= report_ids:
            raise ValueError("报告参数必须对应报告任务")
    except (ValidationError, ValueError, TypeError, AttributeError):
        return {**clean, "supervisor_status": "failed",
                "supervisor_error": _error("invalid_plan", "计划或报告参数无效，未执行任务。")}
    return {**clean, "plan": plan.model_dump(), "report_parameters": params,
            "supervisor_status": "needs_clarification" if plan.status == "needs_clarification" else "running"}


def _market_result(raw):
    if not isinstance(raw, dict) or raw.get("status") not in {"completed", "partial", "failed"}:
        raise ValueError("Invalid market-data response")
    if raw["status"] == "failed":
        try:
            error = TaskError.model_validate(raw.get("error")).model_dump()
        except ValidationError:
            error = _error("specialist_failed", "数据查询失败。")
        return "failed", None, error
    result = MarketDataResult.model_validate_json(json.dumps(raw.get("result"))).model_dump(mode="json")
    return raw["status"], result, None


def _report_result(raw):
    if not isinstance(raw, dict):
        raise ValueError("Invalid report response")
    if raw.get("error") or raw.get("current_phase") != "completed" or not raw.get("final_report"):
        return "failed", raw, _error("report_failed", "报告流程未成功完成，请查看节点输出。")
    try:
        report = json.loads(raw["final_report"]) if isinstance(raw["final_report"], str) else raw["final_report"]
    except (ValueError, TypeError):
        return "failed", raw, _error("invalid_report", "报告 JSON 无效，已保留节点输出。")
    if not isinstance(report, dict):
        return "failed", raw, _error("invalid_report", "报告不是 JSON 对象，已保留节点输出。")
    # Single report validation entrypoint; do not duplicate constraint logic.
    errors = validate_report(report)
    output = {**raw, "validation_errors": errors}
    return ("partial" if errors else "completed"), output, None


def _dependency_evidence(task, results):
    """Namespace tool IDs to prevent collisions across independent agents."""
    evidence = []
    for dependency in task["depends_on"]:
        record = results[dependency]
        if record["category"] == "market_data":
            for item in record["result"].get("evidence", []):
                item = deepcopy(item)
                item["tool_call_id"] = f"{dependency}:{item['tool_call_id']}"
                evidence.append(item)
    return evidence


def create_supervisor_graph(*, market_data_graph=None, report_graph=None, analytics_graph=None):
    """Sequential dispatcher for a validated plan (max 12 tasks).

    Partial dependencies may proceed with their available evidence. Failed,
    blocked or unsupported dependencies block dependent tasks. No automatic
    task retry/replanning, private checkpointer, or new LLM call is added.
    """
    market = create_market_data_agent() if market_data_graph is None else market_data_graph
    report = create_report_graph() if report_graph is None else report_graph
    analytics = create_analytics_agent() if analytics_graph is None else analytics_graph

    def dispatch(state: SupervisorState, config: RunnableConfig) -> dict:
        results = dict(state["task_results"])
        pending = [task for task in state["plan"]["tasks"] if task["task_id"] not in results]
        task = next((task for task in pending if all(dep in results for dep in task["depends_on"])), None)
        if task is None:
            return {"supervisor_status": "failed",
                    "supervisor_error": _error("scheduler_stalled", "任务依赖无法推进。")}
        ident, category = task["task_id"], task["category"]
        get_stream_writer()({"event": "task_started", "task_id": ident, "category": category,
                             "question": task["question"], "depends_on": task["depends_on"],
                             "dependency_statuses": {dep: results[dep]["status"] for dep in task["depends_on"]}})
        status, result, error = "failed", None, None
        blocked = [dep for dep in task["depends_on"] if results[dep]["status"] not in {"completed", "partial"}]
        if blocked:
            status, error = "blocked", _error("dependency_failed", f"前置任务不可用：{', '.join(blocked)}")
        elif category == "investment_strategy":
            status, error = "unsupported", _error("capability_unavailable", f"{category} 能力尚未接入。")
        else:
            try:
                if category == "market_data":
                    raw = market.invoke({"task": task["question"],
                                         "existing_evidence": _dependency_evidence(task, results)}, config=config)
                    status, result, error = _market_result(raw)
                elif category == "analytics":
                    inputs = analytics_inputs(task, results, config)
                    raw = analytics.invoke(inputs, config=config)
                    status, result, error = analytics_result(raw, inputs, config)
                else:
                    params = state["report_parameters"].get(ident, {})
                    inputs = {"user_query": task["question"],
                              "research_topic": params.get("research_topic") or task["question"],
                              "industry_focus": params.get("industry_focus") or task["question"],
                              "time_horizon": params.get("time_horizon") or "按任务描述",
                              "processing_mode": "deliberative", "query_type": "analytical",
                              "messages": [], "final_response": None, "perception_data": None,
                              "world_model": None, "reasoning_plans": None, "selected_plan": None,
                              "final_report": None, "validation_errors": None, "retry_count": 0,
                              "current_phase": "perception", "error": None}
                    # Keep task intent intact when dedicated report parameters are absent.
                    raw = report.invoke(inputs, config=config)
                    status, result, error = _report_result(raw)
            except Exception:
                status, result, error = "failed", None, _error("specialist_error", "专家执行或结果格式异常，请重试。")
        results[ident] = TaskResult.model_validate(
            {**task, "status": status, "result": result, "error": error}
        ).model_dump()
        return {"task_results": results, "last_task_id": ident}

    def route(state):
        if state["supervisor_status"] != "running":
            return "end"
        return "finish" if len(state["task_results"]) == len(state["plan"]["tasks"]) else "dispatch"

    def finish(state):
        statuses = [record["status"] for record in state["task_results"].values()]
        status = "completed" if all(s == "completed" for s in statuses) else (
            "partial" if any(s in {"completed", "partial"} for s in statuses) else "failed")
        return {"supervisor_status": status}

    graph = StateGraph(SupervisorState)
    graph.add_node("initialize", _initialize)
    graph.add_node("supervisor", dispatch)
    graph.add_node("finish", finish)
    graph.add_edge(START, "initialize")
    destinations = {"end": END, "dispatch": "supervisor", "finish": "finish"}
    graph.add_conditional_edges("initialize", route, destinations)
    graph.add_conditional_edges("supervisor", route, destinations)
    graph.add_edge("finish", END)
    return graph.compile()
