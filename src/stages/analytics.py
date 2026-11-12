"""Analytics nodes: scoped computation, no market API or cross-agent dispatch."""
import json
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.prebuilt import ToolNode
from pydantic import ValidationError

from src.analytics_artifacts import AnalysisStore
from src.analytics_state import AnalyticsInput, AnalyticsAnswer, AnalyticsResult, AnalyticsState, MissingDataRequest
from src.datasets import DatasetStore
from src.llm import FAST_MODEL, create_llm

METHODOLOGY_PATH = Path(__file__).resolve().parents[2] / "research_skills" / "analytics-methodology" / "SKILL.md"


def load_analytics_methodology() -> str:
    """Load the fixed repository skill; no cwd dependency, cache or model path input."""
    text = METHODOLOGY_PATH.read_text(encoding="utf-8").strip()
    if text.startswith("---\n"):
        _, separator, text = text[4:].partition("\n---\n")
        if not separator:
            raise ValueError("方法文件 frontmatter 未闭合")
    if not text.strip():
        raise ValueError("方法文件正文为空")
    return text.strip()


_SYSTEM = """你是定量分析专家。只对任务提供的数据集做可复现计算，不抓取数据、不调其他Agent、不做买卖推荐。
dataset_refs仅是元数据引用，不显示metrics不代表底层数据缺失。估值比较用compare_valuations读取数据；字段名pe_ttm/pb，PE_TTM/PB_MRQ是口径。
只调用适用的分析工具，不重复计算同一结果；只能用输入清单的dataset_id，禁止猜测ID。
依照任务选择表现、基准比较、价格因子或估值比较，不为完成而盲目调用全部工具。
输入assumptions明确指定的年化和窗口参数必须遵守，实际参数与限制由工具产物记录。
数据不足时返回missing_information和结构化missing_data_requests，由父级决定后续采集。
数值结论必须引用实际analysis_id；不可捏造指标或把模型自行计算作为工具结果。
模拟数据、缺失指标、样本不足、收益/估值口径及工具限制须明确，不将技术因子当作预测保证。
已有分析产物足够时可以复用。输出严格JSON，按以下schema，不要回填数值、图表或引用元数据：
{schema}
"""


def failure(kind, message):
    return {"status": "failed", "result": None, "error": {"type": kind, "message": message}}


def _stores(config):
    runtime = config.get("configurable") or {}
    ds, analyses = runtime.get("dataset_store"), runtime.get("analysis_store")
    if not isinstance(ds, DatasetStore) or not isinstance(analyses, AnalysisStore):
        raise ValueError("missing runtime stores")
    return ds, analyses


def _canonical_analysis(store, ident, allowed):
    ref = store.get_ref(ident)
    if not {item["dataset_id"] for item in ref["dataset_refs"]} <= allowed:
        raise ValueError("分析产物使用了任务范围外的数据集")
    return ref


def _check_reuse_assumptions(ref, assumptions):
    applicable = {"analyze_price_performance": ("periods_per_year",),
                  "compare_with_benchmark": ("periods_per_year",),
                  "compute_factors": ("periods_per_year", "window"), "compare_valuations": ()}
    for key in applicable.get(ref["tool_name"], ()):
        if assumptions.get(key) is not None and ref["assumptions"].get(key) != assumptions[key]:
            raise ValueError("已有产物参数与本次指定假设不符")


def initialize(state: AnalyticsState, config: RunnableConfig) -> dict:
    reset = {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)], "tool_rounds": 0,
             "tool_calls_used": 0, "output_retries": 0, "analysis_artifacts": [],
             "tool_errors": [], "result": None, "status": "running", "error": None}
    try:
        request = AnalyticsInput.model_validate({key: state[key] for key in AnalyticsInput.model_fields if key in state})
    except ValidationError:
        return {**reset, **failure("invalid_input", "分析任务或输入参数格式无效。")}
    if not request.dataset_refs and not request.existing_analysis_refs:
        missing = MissingDataRequest(kind="unspecified", subjects=request.subjects,
            time_range=request.time_range, reason="任务尚未提供数据集，请由父级补充历史价格或估值数据。")
        result = AnalyticsResult(summary="缺少分析数据，尚未执行计算。", findings=[], analysis_refs=[],
            chart_refs=[], dataset_refs=[], assumptions=request.assumptions.model_dump(), limitations=[],
            missing_information=[missing.reason], missing_data_requests=[missing])
        return {**reset, **request.model_dump(), "status": "partial", "result": result.model_dump(mode="json")}
    try:
        datasets, analyses = _stores(config)
    except ValueError:
        return {**reset, **failure("missing_store", "请求内数据或分析产物存储未配置。")}
    try:
        ids = [item["dataset_id"] for item in request.dataset_refs]
        if not all(isinstance(ident, str) and ident for ident in ids) or len(ids) != len(set(ids)):
            raise ValueError("重复或无效数据ID")
        refs = [datasets.get_ref(ident).model_dump(mode="json") for ident in ids]
        for ident in ids:
            datasets.get(ident)  # Verify the referenced dataset actually resolves.
        existing_ids = [item["analysis_id"] for item in request.existing_analysis_refs]
        if len(existing_ids) != len(set(existing_ids)):
            raise ValueError("重复分析ID")
        existing = [_canonical_analysis(analyses, ident, set(ids)) for ident in existing_ids]
        for ref in existing:
            _check_reuse_assumptions(ref, request.assumptions.model_dump())
    except (ValueError, KeyError, TypeError):
        return {**reset, **failure("invalid_reference", "数据集或分析引用无效、已过期或超出任务范围。")}
    try:
        methodology = load_analytics_methodology()
    except (OSError, ValueError, UnicodeError):
        return {**reset, **failure("methodology_unavailable", "分析方法文件缺失或无效，任务未调用模型。")}
    inputs = {**request.model_dump(), "dataset_refs": refs, "existing_analysis_refs": existing}
    messages = [*reset["messages"], SystemMessage(content=_SYSTEM.format(
        schema=json.dumps(AnalyticsAnswer.model_json_schema(), ensure_ascii=False))),
        SystemMessage(content="【分析方法：analytics-methodology】\n" + methodology),
        HumanMessage(content=json.dumps(inputs, ensure_ascii=False))]
    return {**reset, **inputs, "analysis_artifacts": existing, "messages": messages}


def make_agent_node(tools, max_tool_rounds, max_tool_calls):
    def agent(state: AnalyticsState):
        try:
            llm = create_llm(FAST_MODEL)
            repairing = state["output_retries"] > 0
            response = (llm if repairing else llm.bind_tools(tools)).invoke(state["messages"])
            if not isinstance(response, AIMessage):
                return failure("model_error", "分析模型未返回有效消息。")
            calls = response.tool_calls
            # A metadata-only reference cannot establish that the underlying metrics are missing.
            # Probe a valuation-only comparison once before accepting a no-tool refusal.
            refs = state["dataset_refs"]
            if (not calls and not repairing and state["tool_rounds"] == 0
                    and not state["analysis_artifacts"] and 2 <= len(refs) <= 20
                    and all(ref["kind"] == "valuation_snapshot" for ref in refs)
                    and any(word in state["task"].lower() for word in ("估值", "valuation", "pe", "pb"))
                    and any(tool.name == "compare_valuations" for tool in tools)):
                from uuid import uuid4
                response = AIMessage(content="", tool_calls=[{"name": "compare_valuations",
                    "args": {"dataset_ids": [ref["dataset_id"] for ref in refs]},
                    "id": "valuation_probe_" + uuid4().hex}])
                calls = response.tool_calls
            if repairing and calls:
                return failure("invalid_output", "修正阶段不得重新执行计算工具。")
            if calls and (state["tool_rounds"] >= max_tool_rounds or
                          state["tool_calls_used"] + len(calls) > max_tool_calls):
                return failure("tool_budget_exceeded", "分析工具调用达到预算上限。")
            allowed = {ref["dataset_id"] for ref in state["dataset_refs"]}
            for call in calls:
                args = call["args"]
                requested = [args[key] for key in ("dataset_id", "benchmark_dataset_id") if key in args]
                requested.extend(args.get("dataset_ids", []))
                if not set(requested) <= allowed:
                    return failure("dataset_scope_error", "工具请求的数据集超出本任务授权范围。")
                # Only caller-specified assumptions override model-chosen/default parameters.
                for key in ("periods_per_year", "window"):
                    specified = state["assumptions"].get(key)
                    supports = key == "window" and call["name"] == "compute_factors" or (
                        key == "periods_per_year" and call["name"] != "compare_valuations")
                    if specified is not None and supports:
                        args[key] = specified
            return {"messages": [response]}
        except Exception:
            return failure("model_error", "分析模型调用失败，请稍后重试。")
    return agent


def make_tools_node(tools):
    executor = ToolNode(tools, handle_tool_errors=True)
    def execute(state: AnalyticsState, config: RunnableConfig):
        try:
            _, analyses = _stores(config)
            update = executor.invoke(state, config=config)
            refs = {item["analysis_id"]: item for item in state["analysis_artifacts"]}
            errors = list(state["tool_errors"])
            allowed = {ref["dataset_id"] for ref in state["dataset_refs"]}
            for msg in update["messages"]:
                if not isinstance(msg, ToolMessage):
                    continue
                if getattr(msg, "status", "") == "error":
                    errors.append({"tool_call_id": msg.tool_call_id, "type": "tool_error",
                                   "message": "分析工具调用参数错误或执行异常。"})
                    continue
                payload = json.loads(msg.content)
                if payload.get("status") != "available":
                    errors.append({"tool_call_id": msg.tool_call_id, **payload["error"]})
                else:
                    ident = payload["analysis_ref"]["analysis_id"]
                    refs[ident] = _canonical_analysis(analyses, ident, allowed)
            guidance = HumanMessage(content="计算结果清单：引用analysis_id，不重复计算；缺失数据须明确说明。\n" +
                json.dumps({"analysis_refs": list(refs.values()), "tool_errors": errors}, ensure_ascii=False))
            return {"messages": update["messages"] + [guidance], "analysis_artifacts": list(refs.values()),
                    "tool_errors": errors, "tool_rounds": state["tool_rounds"] + 1,
                    "tool_calls_used": state["tool_calls_used"] + len(state["messages"][-1].tool_calls)}
        except Exception:
            return failure("tool_error", "分析工具结果无法验证，任务已停止。")
    return execute


def make_finalize_node(max_output_retries):
    def finalize(state: AnalyticsState, config: RunnableConfig):
        try:
            text = state["messages"][-1].content.strip()
            lines = text.splitlines()
            if len(lines) >= 3 and lines[0].lower() in {"```", "```json"} and lines[-1] == "```":
                text = "\n".join(lines[1:-1])
            answer = AnalyticsAnswer.model_validate(json.loads(text))
            ids = answer.analysis_ids
            available = {ref["analysis_id"] for ref in state["analysis_artifacts"]}
            if len(ids) != len(set(ids)) or not set(ids) <= available:
                raise ValueError("analysis_ids 含重复或未知引用")
            if not ids and not (answer.missing_information or answer.missing_data_requests):
                raise ValueError("无分析产物时必须说明缺失信息，不得声称计算完成")
            _, store = _stores(config)
            allowed = {ref["dataset_id"] for ref in state["dataset_refs"]}
            refs = [_canonical_analysis(store, ident, allowed) for ident in ids]
            missing = list(answer.missing_information) + [e["message"] for e in state["tool_errors"]]
            undefined = any(value is None for ref in refs for value in ref["metrics"].values())
            if undefined:
                missing.append("部分指标不可定义或缺少可比数据，详见计算产物限制。")
            limits = list(dict.fromkeys(limit for ref in refs for limit in ref["limitations"]))
            result = AnalyticsResult(summary=answer.summary,
                findings=[{key: ref[key] for key in ("analysis_id", "tool_name", "metrics", "metric_units", "table")}
                          for ref in refs], analysis_refs=refs,
                chart_refs=[chart for ref in refs for chart in ref["chart_refs"]], dataset_refs=state["dataset_refs"],
                assumptions={"requested": state["assumptions"],
                             "effective": {ref["analysis_id"]: ref["assumptions"] for ref in refs}},
                limitations=limits, missing_information=list(dict.fromkeys(missing)),
                missing_data_requests=answer.missing_data_requests)
            mock = any(ref["data_mode"] == "mock" for ref in state["dataset_refs"])
            return {"result": result.model_dump(mode="json"), "error": None,
                    "status": "partial" if mock or missing or answer.missing_data_requests or not refs else "completed"}
        except (ValueError, TypeError, KeyError, AttributeError):
            if state["output_retries"] < max_output_retries:
                return {"output_retries": state["output_retries"] + 1, "messages": [HumanMessage(content=
                    "输出校验失败，请只修正最终JSON，不调用工具。可用analysis_id：" +
                    json.dumps([ref["analysis_id"] for ref in state["analysis_artifacts"]], ensure_ascii=False) +
                    "。无计算结果时须填写missing_information或missing_data_requests。")], "status": "running"}
            return failure("invalid_output", "分析输出格式或引用校验失败。")
    return finalize
