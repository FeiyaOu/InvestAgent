"""Independent subgraph tests: no real LLM or market API."""
import json
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from src.market_data_agent import create_market_data_agent


@tool
def lookup(symbol: str) -> str:
    """Fetch a test quote."""
    return f"{symbol}: 100 CNY"


def run(responses, tools=None, **kwargs):
    llm = Mock()
    llm.bind_tools.return_value = llm
    llm.invoke.side_effect = responses
    with patch("src.stages.market_data.create_llm", return_value=llm):
        graph = create_market_data_agent(tools=[lookup] if tools is None else tools, **kwargs)
        result = graph.invoke({"task": "查询茅台价格"})
    return graph, result, llm


def call(name="lookup", ident="c1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": {"symbol": "600519"}, "id": ident}])


def answer(**updates):
    payload = {"answer": "最新价格为100元", "evidence_ids": ["c1"], "missing_information": []}
    payload.update(updates)
    return AIMessage(content=json.dumps(payload, ensure_ascii=False))


def test_tool_loop_and_validated_evidence():
    graph, result, llm = run([call(), answer()])
    assert {"agent", "tools", "finalize"} <= set(graph.get_graph().nodes)
    assert result["status"] == "completed"
    assert result["result"]["evidence"][0]["content"] == "600519: 100 CNY"
    assert result["tool_calls_used"] == 1
    assert llm.invoke.call_count == 2


def test_no_tools_can_report_missing_data():
    _, result, _ = run([answer(evidence_ids=[], missing_information=["缺少价格数据"])])
    assert result["status"] == "partial"


def test_invalid_output_gets_one_correction_attempt():
    _, result, llm = run([AIMessage(content='{}'), answer(evidence_ids=[], missing_information=["无数据"])])
    assert result["status"] == "partial"
    assert llm.invoke.call_count == 2


def test_invalid_output_eventually_fails():
    _, result, _ = run([AIMessage(content='{}'), AIMessage(content='{}')])
    assert result["status"] == "failed"
    assert result["error"]["type"] == "invalid_output"


def test_budget_stops_repeated_calls():
    _, result, llm = run([call(), call(ident="c2")], max_tool_rounds=1)
    assert result["status"] == "failed"
    assert result["error"]["type"] == "tool_budget_exceeded"
    assert llm.invoke.call_count == 2


def test_batch_cannot_exceed_call_budget():
    message = AIMessage(content="", tool_calls=call().tool_calls + call(ident="c2").tool_calls)
    _, result, _ = run([message], max_tool_calls=1)
    assert result["status"] == "failed"
    assert result["tool_calls_used"] == 0


def test_invented_evidence_is_rejected():
    _, result, _ = run([answer(), answer()])
    assert result["status"] == "failed"


def test_tool_exception_remains_visible_and_not_successful():
    @tool
    def broken(symbol: str) -> str:
        """Fail a lookup."""
        raise RuntimeError("offline")
    _, result, _ = run([call("broken"), answer()], tools=[broken])
    assert result["status"] == "partial"
    assert result["result"]["evidence"][0]["status"] == "error"


def test_llm_exception_returns_failure():
    _, result, _ = run([RuntimeError("provider unavailable")])
    assert result["status"] == "failed"
    assert result["error"]["type"] == "model_error"


def test_invocations_do_not_share_messages():
    graph, _, _ = run([answer(evidence_ids=[], missing_information=["无数据"])])
    llm = Mock()
    llm.bind_tools.return_value = llm
    llm.invoke.return_value = answer(evidence_ids=[], missing_information=["无数据"])
    with patch("src.stages.market_data.create_llm", return_value=llm):
        result = graph.invoke({"task": "另一个任务"})
    assert len(result["messages"]) == 3


def test_existing_evidence_is_validated_and_reusable():
    llm = Mock()
    llm.bind_tools.return_value = llm
    llm.invoke.return_value = answer(evidence_ids=["previous"])
    evidence = {"tool_call_id": "previous", "tool_name": "lookup", "content": "100 CNY",
                "retrieved_at": "2026-11-10T00:00:00Z", "status": "returned", "data_mode": "real"}
    with patch("src.stages.market_data.create_llm", return_value=llm):
        graph = create_market_data_agent(tools=[lookup])
        result = graph.invoke({"task": "整理已有行情", "existing_evidence": [evidence]})
    assert result["status"] == "completed"
    assert result["result"]["evidence"][0]["tool_call_id"] == "previous"
    invalid = graph.invoke({"task": "查询", "existing_evidence": [{"tool_call_id": "x"}]})
    assert invalid["status"] == "failed"
    assert invalid["error"]["type"] == "invalid_task"


def test_empty_task_returns_failure():
    graph = create_market_data_agent(tools=[lookup])
    assert graph.invoke({"task": "  "})["error"]["type"] == "invalid_task"


def test_mock_and_fallback_results_are_partial(monkeypatch):
    @tool
    def fallback(symbol: str) -> str:
        """Unavailable provider."""
        return "行情数据暂时无法获取"
    _, result, _ = run([call("fallback"), answer()], tools=[fallback])
    assert result["status"] == "partial"
    monkeypatch.setenv("USE_REAL_DATA", "false")
    _, result, _ = run([call(), answer()])
    assert result["status"] == "partial"
    assert result["result"]["evidence"][0]["data_mode"] == "mock"


def test_markdown_fenced_json_is_accepted():
    response = answer()
    response.content = '```json\n' + response.content + '\n```'
    _, result, _ = run([call(), response])
    assert result["status"] == "completed"


def test_output_repair_receives_actual_evidence_ids_and_reason():
    _, result, llm = run([call(), answer(evidence_ids=["wrong"]), answer()])
    assert result["status"] == "completed"
    feedback = llm.invoke.call_args.args[0][-1].content
    assert "c1" in feedback
    assert "未知" in feedback


def test_tool_results_include_evidence_manifest_before_synthesis():
    _, result, llm = run([call(), answer()])
    assert result["status"] == "completed"
    synthesis_input = llm.invoke.call_args.args[0]
    assert "c1" in synthesis_input[-1].content
    assert "不要重复" in synthesis_input[-1].content


def test_output_repair_does_not_bind_tools_or_execute_new_calls():
    _, result, llm = run([call(), answer(evidence_ids=["wrong"]), call(ident="duplicate")])
    assert result["status"] == "failed"
    assert result["error"]["type"] == "invalid_output"
    assert result["tool_calls_used"] == 1
    assert llm.bind_tools.call_count == 2  # Initial selection + synthesis, not repair.


def test_history_tool_reference_is_collected_from_store_not_model(monkeypatch):
    import json
    from src.datasets import DatasetStore
    monkeypatch.setenv("USE_REAL_DATA", "false")
    llm = Mock(); llm.bind_tools.return_value = llm
    llm.invoke.side_effect = [AIMessage(content="", tool_calls=[{
        "name": "get_price_history", "args": {"query": "600519", "start_date": "2025-01-02",
            "end_date": "2025-01-03"}, "id": "history1"}]),
        AIMessage(content=json.dumps({"answer": "已获取模拟历史数据", "evidence_ids": ["history1"], "missing_information": []}))]
    store = DatasetStore()
    with patch("src.stages.market_data.create_llm", return_value=llm):
        graph = create_market_data_agent()
        result = graph.invoke({"task": "获取去年历史价格"}, config={"configurable": {"dataset_store": store}})
    assert result["status"] == "partial"
    ref = result["result"]["dataset_refs"][0]
    assert store.get(ref["dataset_id"]).rows
    assert "rows" not in ref


def test_valuation_snapshot_reference_is_collected_by_market_agent(monkeypatch):
    from src.datasets import DatasetStore
    monkeypatch.setenv("USE_REAL_DATA", "false")
    llm = Mock(); llm.bind_tools.return_value = llm
    llm.invoke.side_effect = [AIMessage(content="", tool_calls=[{
        "name": "get_valuation_snapshot", "args": {"query": "茅台", "as_of_date": "2025-01-03"}, "id": "v1"}]),
        answer(evidence_ids=["v1"], missing_information=["股息率缺失"]) ]
    store = DatasetStore()
    with patch("src.stages.market_data.create_llm", return_value=llm):
        result = create_market_data_agent().invoke({"task": "获取茅台估值"},
            config={"configurable": {"dataset_store": store}})
    assert result["status"] == "partial"
    ref = result["result"]["dataset_refs"][0]
    assert ref["kind"] == "valuation_snapshot"
    assert store.get(ref["dataset_id"]).metrics["pe_ttm"].basis == "PE_TTM"
    assert result["result"]["evidence"][0]["as_of_date"] == "2025-01-03"
