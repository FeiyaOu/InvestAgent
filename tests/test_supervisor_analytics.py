"""Analytics dispatch, reference handoff and per-request runtime isolation."""
import json
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

from src.analytics_artifacts import AnalysisStore
from src.analytics_tools import analyze_price_performance
from src.datasets import DatasetStore, PriceDataset
from src.supervisor import create_supervisor_graph
from src.parent_graph import create_parent_graph


def task(ident, category, deps=None):
    return {"task_id": ident, "category": category, "question": f"任务{ident}", "depends_on": deps or []}


def plan(*tasks):
    return {"status": "ready", "tasks": list(tasks), "clarification_questions": []}


def setup():
    ds, store = DatasetStore(), AnalysisStore()
    ref = ds.put(PriceDataset(kind="price_history", symbol="600519", market="SSE", currency="CNY",
        provider="test", retrieved_at=datetime.now(timezone.utc), data_mode="real", frequency="daily",
        adjustment="qfq", asset_type="stock", price_unit="CNY/share", volume_unit="not_available",
        rows=[{"date": date(2025, 1, i+1), "close": float(v)} for i, v in enumerate([100, 110, 99])]))
    config = {"configurable": {"dataset_store": ds, "analysis_store": store}}
    md = Mock(); md.invoke.return_value = {"status": "completed", "error": None, "result": {
        "answer": "已有历史数据", "evidence_ids": [], "evidence": [], "missing_information": [],
        "dataset_refs": [ref.model_dump(mode="json")]}}
    return ds, store, ref, config, md


def result(ref, analysis=None, status="completed"):
    refs = [analysis] if analysis else []
    return {"status": status, "error": None, "result": {"summary": "结果", "findings": [],
        "analysis_refs": refs, "chart_refs": [], "dataset_refs": [ref.model_dump(mode="json")],
        "assumptions": {}, "limitations": [], "missing_information": [], "missing_data_requests": []}}


def test_dispatch_hands_off_only_dependency_refs_and_validates_artifact():
    ds, store, ref, config, md = setup()
    created = json.loads(analyze_price_performance.invoke({"dataset_id": ref.dataset_id}, config=config))["analysis_ref"]
    analytics = Mock(); analytics.invoke.return_value = result(ref, created)
    graph = create_supervisor_graph(market_data_graph=md, analytics_graph=analytics)
    state = graph.invoke({"plan": plan(task("m", "market_data"), task("a", "analytics", ["m"]))}, config=config)
    record = state["task_results"]["a"]
    assert record["status"] == "completed"
    inputs = analytics.invoke.call_args.args[0]
    assert inputs["dataset_refs"] == [ref.model_dump(mode="json")]
    assert "evidence" not in inputs and "messages" not in inputs
    assert analytics.invoke.call_args.kwargs["config"]["configurable"]["analysis_store"] is store
    assert record["result"]["findings"][0]["metrics"]["period_return"] == created["metrics"]["period_return"]
    assert record["result"]["chart_refs"] == created["chart_refs"]


def test_analytics_chain_reuses_dependency_artifact_and_deduplicates_data():
    _, _, ref, config, md = setup()
    created = json.loads(analyze_price_performance.invoke({"dataset_id": ref.dataset_id}, config=config))["analysis_ref"]
    analytics = Mock(); analytics.invoke.side_effect = [result(ref, created), result(ref, created)]
    graph = create_supervisor_graph(market_data_graph=md, analytics_graph=analytics)
    state = graph.invoke({"plan": plan(task("m", "market_data"), task("a", "analytics", ["m"]),
        task("b", "analytics", ["m", "a"]))}, config=config)
    inputs = analytics.invoke.call_args_list[1].args[0]
    assert len(inputs["dataset_refs"]) == 1
    assert inputs["existing_analysis_refs"] == [created]
    assert state["task_results"]["b"]["status"] == "completed"


def test_unrelated_or_expired_data_is_not_exposed():
    ds, _, ref, config, md = setup()
    foreign = ds.put(ds.get(ref.dataset_id))
    analytics = Mock(); analytics.invoke.return_value = result(foreign)
    state = create_supervisor_graph(market_data_graph=md, analytics_graph=analytics).invoke({
        "plan": plan(task("m", "market_data"), task("a", "analytics", ["m"]))}, config=config)
    assert state["task_results"]["a"]["status"] == "failed"
    ds.clear()
    analytics.reset_mock()
    state = create_supervisor_graph(market_data_graph=md, analytics_graph=analytics).invoke({
        "plan": plan(task("m", "market_data"), task("a", "analytics", ["m"]))}, config=config)
    assert state["task_results"]["a"]["status"] == "failed"
    analytics.invoke.assert_not_called()


def test_failed_analytics_blocks_downstream_but_strategy_remains_unsupported():
    _, _, ref, config, md = setup()
    analytics = Mock(); analytics.invoke.return_value = {"status": "failed", "result": None,
        "error": {"type": "invalid_output", "message": "输出验证失败"}}
    state = create_supervisor_graph(market_data_graph=md, analytics_graph=analytics).invoke({"plan": plan(
        task("m", "market_data"), task("a", "analytics", ["m"]), task("b", "analytics", ["a"]),
        task("s", "investment_strategy"))}, config=config)
    assert state["task_results"]["a"]["error"]["type"] == "invalid_output"
    assert state["task_results"]["b"]["status"] == "blocked"
    assert state["task_results"]["s"]["status"] == "unsupported"


def test_no_data_uses_real_agent_missing_data_path_without_llm():
    with patch("src.stages.analytics.create_llm") as llm:
        state = create_supervisor_graph().invoke({"plan": plan(task("a", "analytics"))})
    record = state["task_results"]["a"]
    assert record["status"] == "partial"
    assert record["result"]["missing_data_requests"]
    llm.assert_not_called()


def test_parent_creates_both_stores_per_request_and_keeps_them_out_of_state():
    md = Mock()
    md.invoke.return_value = {"status": "completed", "error": None, "result": {
        "answer": "行情", "evidence_ids": [], "evidence": [], "missing_information": []}}
    chain = Mock(); chain.invoke.return_value = plan(task("m", "market_data"))
    composing = Mock(); composing.invoke.return_value = {"answer": "行情"}
    graph = create_parent_graph(market_data_graph=md)
    with patch("src.stages.planner._create_chain", return_value=chain), patch("src.stages.composer._create_chain", return_value=composing):
        outputs = [graph.invoke({"user_query": "查询"}) for _ in range(2)]
    configs = [call.kwargs["config"]["configurable"] for call in md.invoke.call_args_list]
    assert configs[0]["dataset_store"] is not configs[1]["dataset_store"]
    assert configs[0]["analysis_store"] is not configs[1]["analysis_store"]
    assert all("analysis_store" not in state and "dataset_store" not in state for state in outputs)


def test_real_analytics_executes_with_market_produced_data_in_parent_graph():
    from langchain_core.messages import AIMessage
    ds_configured = []
    md = Mock()
    def collect(inputs, config):
        ds = config["configurable"]["dataset_store"]
        ds_configured.append(ds)
        ref = ds.put(PriceDataset(kind="price_history", symbol="600519", market="SSE", currency="CNY",
            provider="test", retrieved_at=datetime.now(timezone.utc), data_mode="real", frequency="daily",
            adjustment="qfq", asset_type="stock", price_unit="CNY/share", volume_unit="not_available",
            rows=[{"date": date(2025, 1, i+1), "close": float(v)} for i, v in enumerate([100, 110, 99])]))
        return {"status": "completed", "error": None, "result": {"answer": "历史数据已获取", "evidence_ids": [],
            "evidence": [], "missing_information": [], "dataset_refs": [ref.model_dump(mode="json")]}}
    md.invoke.side_effect = collect
    planning = Mock(); planning.invoke.return_value = plan(task("m", "market_data"), task("a", "analytics", ["m"]))
    llm = Mock(); llm.bind_tools.return_value = llm
    def respond(messages):
        if messages[-1].content.startswith("计算结果清单"):
            manifest = json.loads(messages[-1].content.split("\n", 1)[1])
            return AIMessage(content=json.dumps({"summary": "区间下跌1%", "analysis_ids": [manifest["analysis_refs"][0]["analysis_id"]],
                "missing_information": [], "missing_data_requests": []}))
        inputs = json.loads(messages[-1].content)
        return AIMessage(content="", tool_calls=[{"id": "c", "name": "analyze_price_performance",
            "args": {"dataset_id": inputs["dataset_refs"][0]["dataset_id"]}}])
    llm.invoke.side_effect = respond
    composing = Mock(); composing.invoke.return_value = {"answer": "任务执行完成"}
    with patch("src.stages.planner._create_chain", return_value=planning), patch(
            "src.stages.analytics.create_llm", return_value=llm), patch("src.stages.composer._create_chain", return_value=composing):
        state = create_parent_graph(market_data_graph=md).invoke({"user_query": "分析茅台历史表现"})
    assert state["task_results"]["a"]["status"] == "completed"
    metric = state["task_results"]["a"]["result"]["findings"][0]["metrics"]["period_return"]
    assert abs(metric + .01) < 1e-10
    assert "analysis_store" not in state and "messages" not in state


def test_unrelated_task_data_not_granted_and_tool_numbers_cannot_be_forged():
    _, _, ref, config, md = setup()
    created = json.loads(analyze_price_performance.invoke({"dataset_id": ref.dataset_id}, config=config))["analysis_ref"]
    forged = result(ref, {**created, "metrics": {"period_return": 999.}})
    forged["result"]["findings"] = [{"metrics": {"period_return": 999.}}]
    analytics = Mock(); analytics.invoke.return_value = forged
    state = create_supervisor_graph(market_data_graph=md, analytics_graph=analytics).invoke({
        "plan": plan(task("m", "market_data"), task("a", "analytics", ["m"]))}, config=config)
    assert state["task_results"]["a"]["result"]["findings"][0]["metrics"] == created["metrics"]
    analytics.reset_mock()
    analytics.invoke.return_value = {"status": "partial", "error": None, "result": {
        "summary": "缺数据", "findings": [], "analysis_refs": [], "chart_refs": [], "dataset_refs": [],
        "assumptions": {}, "limitations": [], "missing_information": ["缺数据"], "missing_data_requests": []}}
    create_supervisor_graph(market_data_graph=md, analytics_graph=analytics).invoke({
        "plan": plan(task("m", "market_data"), task("a", "analytics"))}, config=config)
    assert analytics.invoke.call_args.args[0]["dataset_refs"] == []
