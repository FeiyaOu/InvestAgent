"""Market-data agent nodes; no direct provider API access."""
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from langchain_core.runnables import RunnableConfig
from src.datasets import DatasetStore

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import ToolNode
from pydantic import ValidationError

from src.llm import FAST_MODEL, create_llm
from src.market_data_state import MarketDataAnswer, MarketDataResult, MarketDataState, MarketEvidence
from src.tools import data_mode

_SYSTEM = """你是市场数据专家，只收集、核实并整理证据，不做投资建议或因子计算。
按任务选择必要工具，避免重复查询。需要历史价格或后续量化数据时选择 get_price_history，明确日期及复权口径；指数使用 adjustment=none。数据集引用由程序收集，不在最终 JSON 中自行生成 dataset_refs。不把模拟数据、错误提示或过期数据称为实时事实。
工具只能提供现有能力；无法获取时明确说明缺失信息，不编造来源、日期或数值。
最终仅输出 JSON，格式为：
{schema}
证据 ID 使用实际 tool_call_id，已有证据使用调用方提供的 tool_call_id。
引用失败工具时仍须说明数据不可用。没有证据时必须说明缺失信息。
"""


def failure(kind: str, message: str) -> dict:
    return {"status": "failed", "result": None,
            "error": {"type": kind, "message": message}}


def initialize(state: MarketDataState) -> dict:
    task = state.get("task", "")
    if not isinstance(task, str):
        return failure("invalid_task", "查询任务必须为字符串。")
    task = task.strip()
    if not task:
        return failure("invalid_task", "查询任务不能为空。")
    try:
        existing = [MarketEvidence.model_validate(item).model_dump()
                    for item in state.get("existing_evidence", [])]
        ids = [item["tool_call_id"] for item in existing]
        if len(ids) != len(set(ids)):
            raise ValueError("已有证据 ID 重复")
    except (ValidationError, ValueError, TypeError):
        return failure("invalid_task", "已有证据格式无效或 ID 重复。")
    # New invocation starts an independent task; no checkpointer is installed here.
    return {"messages": [SystemMessage(content=_SYSTEM.format(
                schema=json.dumps(MarketDataAnswer.model_json_schema(), ensure_ascii=False))),
            HumanMessage(content=json.dumps({"task": task, "current_date": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
                "subject": state.get("subject", ""),
                "time_range": state.get("time_range", ""),
                "existing_evidence": existing}, ensure_ascii=False))],
            "tool_rounds": 0, "tool_calls_used": 0, "output_retries": 0,
            "existing_evidence": existing, "evidence": [], "dataset_refs": [], "result": None, "error": None, "status": "running"}


def make_agent_node(tools, max_tool_rounds: int, max_tool_calls: int):
    def agent(state: MarketDataState) -> dict:
        try:
            llm = create_llm(FAST_MODEL)
            repairing = state["output_retries"] > 0
            # Repair is a formatting/reference operation, never a new data request.
            response = (llm if repairing else llm.bind_tools(tools)).invoke(state["messages"])
            if not isinstance(response, AIMessage):
                return failure("model_error", "模型未返回 AIMessage。")
            calls = response.tool_calls
            if repairing and calls:
                return failure("invalid_output", "输出修正阶段不得重新调用工具。")
            if calls and (state["tool_rounds"] >= max_tool_rounds or
                          state["tool_calls_used"] + len(calls) > max_tool_calls):
                return failure("tool_budget_exceeded", "达到工具调用预算，任务已停止。")
            return {"messages": [response]}
        except Exception:
            return failure("model_error", "市场数据模型调用失败，请稍后重试。")
    return agent


def make_tools_node(tools):
    executor = ToolNode(tools, handle_tool_errors=True)

    def execute(state: MarketDataState, config: RunnableConfig) -> dict:
        try:
            update = executor.invoke(state, config=config)
            evidence = list(state["evidence"])
            refs = {ref["dataset_id"]: ref for ref in state.get("dataset_refs", [])}
            store = (config.get("configurable") or {}).get("dataset_store")
            for message in update["messages"]:
                if isinstance(message, ToolMessage):
                    content = message.content if isinstance(message.content, str) else json.dumps(message.content, ensure_ascii=False)
                    unavailable = False
                    metadata = None
                    if message.name == "get_price_history" and getattr(message, "status", "") != "error":
                        payload = json.loads(content)
                        unavailable = payload.get("status") != "available"
                        if not unavailable:
                            if not isinstance(store, DatasetStore):
                                raise ValueError("dataset store unavailable")
                            metadata = store.get_ref(payload["dataset_ref"]["dataset_id"]).model_dump(mode="json")
                            refs[metadata["dataset_id"]] = metadata
                    evidence.append({"tool_call_id": message.tool_call_id,
                        "tool_name": message.name or "unknown", "content": content,
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "status": "error" if unavailable or getattr(message, "status", "") == "error" else "returned",
                        "data_mode": metadata["data_mode"] if metadata else data_mode(),
                        "source_url": metadata["source_url"] if metadata else None,
                        "as_of_date": metadata["end_date"] if metadata else None})
            manifest = [{"evidence_id": item["tool_call_id"], "tool_name": item["tool_name"]}
                        for item in evidence + state.get("existing_evidence", [])]
            guidance = HumanMessage(content=(
                "工具已返回。可引用证据清单：" + json.dumps(manifest, ensure_ascii=False) +
                "。最终 evidence_ids 必须逐字复制清单中的 evidence_id，不要自行命名。"
                "已有数据足够时直接输出最终 JSON，不要重复查询相同数据；仅缺少必要数据时调用新工具。"))
            return {"messages": update["messages"] + [guidance], "evidence": evidence,
                    "dataset_refs": list(refs.values()),
                    "tool_rounds": state["tool_rounds"] + 1,
                    "tool_calls_used": state["tool_calls_used"] + len(state["messages"][-1].tool_calls)}
        except Exception:
            return failure("tool_error", "工具执行失败，无法完成本次数据查询。")
    return execute


def make_finalize_node(max_output_retries: int):
    def finalize(state: MarketDataState, config: RunnableConfig) -> dict:
        try:
            content = state["messages"][-1].content
            # Accept a complete Markdown JSON fence, while keeping JSON parsing strict.
            if isinstance(content, str):
                content = content.strip()
                lines = content.splitlines()
                if len(lines) >= 3 and lines[0].lower() in {"```json", "```"} and lines[-1] == "```":
                    content = "\n".join(lines[1:-1])
            answer = MarketDataAnswer.model_validate(json.loads(content))
            evidence = state["evidence"] + state.get("existing_evidence", [])
            ids = {item["tool_call_id"] for item in evidence}
            if not set(answer.evidence_ids) <= ids:
                raise ValueError("evidence_ids 包含未知 ID")
            if not answer.evidence_ids and not answer.missing_information:
                raise ValueError("没有证据时必须说明缺失信息")
            # Retain all raw tool evidence for audit and frontend display.
            store = (config.get("configurable") or {}).get("dataset_store")
            refs = [store.get_ref(ref["dataset_id"]) for ref in state.get("dataset_refs", [])]
            result = MarketDataResult(**answer.model_dump(), evidence=evidence, dataset_refs=refs)
            degraded = any(item.status == "error" or any(marker in item.content for marker in
                ("暂时无法", "无法获取", "调用异常", "模拟", "mock")) or item.data_mode != "real"
                for item in result.evidence)
            return {"result": result.model_dump(mode="json"), "error": None,
                    "status": "partial" if degraded or answer.missing_information else "completed"}
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            if isinstance(exc, ValidationError):
                reason = json.dumps([{"field": ".".join(map(str, e["loc"])), "type": e["type"]}
                                     for e in exc.errors()], ensure_ascii=False)
            elif isinstance(exc, json.JSONDecodeError):
                reason = "不是完整合法的 JSON"
            elif isinstance(exc, ValueError):
                reason = str(exc)
            else:
                reason = "输出字段或类型不正确"
            available = [item.get("tool_call_id") for item in state["evidence"] + state.get("existing_evidence", [])]
            if state["output_retries"] < max_output_retries:
                return {"output_retries": state["output_retries"] + 1,
                        "messages": [HumanMessage(content=f"输出验证失败：{reason}。可用证据 ID：{json.dumps(available, ensure_ascii=False)}。仅修正已有回答，不重新查询或调用工具。请按系统 JSON schema 修正，仅输出完整 JSON；无证据须说明缺失信息。")],
                        "status": "running"}
            return failure("invalid_output", "输出格式或证据引用验证失败。")
    return finalize
