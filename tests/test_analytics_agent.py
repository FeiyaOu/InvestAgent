"""Independent Analytics subgraph: real computation, fake LLM, no APIs."""
import json
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage

from src.analytics_agent import create_analytics_agent
from src.analytics_artifacts import AnalysisStore
from src.datasets import DatasetStore, PriceDataset


def setup_data(mode="real"):
    ds, analyses = DatasetStore(), AnalysisStore()
    ref = ds.put(PriceDataset(kind="price_history", symbol="600519", market="SSE", currency="CNY",
        provider="test", retrieved_at=datetime.now(timezone.utc), data_mode=mode, frequency="daily",
        adjustment="qfq", asset_type="stock", price_unit="CNY/share", volume_unit="not_available",
        rows=[{"date": date(2025, 1, i+1), "close": float(v)} for i, v in enumerate([100, 110, 99, 105])]))
    return ds, analyses, ref, {"configurable": {"dataset_store": ds, "analysis_store": analyses}}


def answer(ids=None, **updates):
    return AIMessage(content=json.dumps({"summary": "历史表现分析", "analysis_ids": ids or [],
        "missing_information": [], "missing_data_requests": [], **updates}, ensure_ascii=False))


def call(ident):
    return AIMessage(content="", tool_calls=[{"name": "analyze_price_performance",
        "args": {"dataset_id": ident}, "id": "c1"}])


def result_answer(messages):
    # The program-provided manifest contains IDs; no test guesses generated IDs.
    manifest = json.loads(messages[-1].content.split("\n", 1)[1])
    return answer([item["analysis_id"] for item in manifest["analysis_refs"]])


def run(responses, inputs=None, config=None, **options):
    llm = Mock(); llm.bind_tools.return_value = llm; llm.invoke.side_effect = responses
    graph = create_analytics_agent(**options)
    with patch("src.stages.analytics.create_llm", return_value=llm):
        result = graph.invoke(inputs or {"task": "分析茅台表现"}, config=config)
    return result, llm


def test_tools_compute_and_final_output_uses_actual_artifacts():
    ds, store, ref, config = setup_data()
    llm = Mock(); llm.bind_tools.return_value = llm
    counter = iter(["call", "answer"])
    def respond(messages):
        return call(ref.dataset_id) if next(counter) == "call" else result_answer(messages)
    llm.invoke.side_effect = respond
    with patch("src.stages.analytics.create_llm", return_value=llm):
        result = create_analytics_agent().invoke({"task": "分析茅台", "dataset_refs": [ref.model_dump(mode="json")]}, config=config)
    assert result["status"] == "completed"
    finding = result["result"]["findings"][0]
    assert abs(finding["metrics"]["period_return"] - .05) < 1e-10
    assert store.get(finding["analysis_id"]).tool_name == "analyze_price_performance"
    assert "series" not in result["result"]["analysis_refs"][0]
    assert result["result"]["chart_refs"]
    assert result["tool_calls_used"] == 1


def test_no_data_returns_structured_requirement_without_llm():
    result, llm = run([])
    assert result["status"] == "partial"
    assert result["result"]["missing_data_requests"]
    llm.invoke.assert_not_called()


def test_invalid_or_expired_dataset_fails_before_llm():
    _, _, ref, _ = setup_data()
    ds2, store2 = DatasetStore(), AnalysisStore()
    result, llm = run([], {"task": "分析", "dataset_refs": [ref.model_dump(mode="json")]},
        {"configurable": {"dataset_store": ds2, "analysis_store": store2}})
    assert result["status"] == "failed"
    llm.invoke.assert_not_called()


def test_missing_runtime_stores_is_explicit():
    _, _, ref, _ = setup_data()
    result, llm = run([], {"task": "分析", "dataset_refs": [ref.model_dump(mode="json")]})
    assert result["error"]["type"] == "missing_store"
    llm.invoke.assert_not_called()


def test_tool_cannot_access_dataset_outside_task_scope():
    ds, store, ref, config = setup_data()
    other = ds.put(ds.get(ref.dataset_id))
    result, _ = run([call(other.dataset_id)], {"task": "分析", "dataset_refs": [ref.model_dump(mode="json")]}, config)
    assert result["error"]["type"] == "dataset_scope_error"
    assert result["tool_calls_used"] == 0


def test_invented_analysis_id_is_rejected_and_repair_has_no_tools():
    _, _, ref, config = setup_data()
    result, llm = run([answer(["invented"]), answer(["invented"])],
        {"task": "分析", "dataset_refs": [ref.model_dump(mode="json")]}, config)
    assert result["status"] == "failed"
    assert result["error"]["type"] == "invalid_output"
    assert llm.bind_tools.call_count == 1


def test_repair_tool_call_is_never_executed():
    _, _, ref, config = setup_data()
    result, _ = run([AIMessage(content='{}'), call(ref.dataset_id)],
        {"task": "分析", "dataset_refs": [ref.model_dump(mode="json")]}, config)
    assert result["error"]["type"] == "invalid_output"
    assert result["tool_calls_used"] == 0


def test_tool_budget_is_bounded():
    _, _, ref, config = setup_data()
    result, _ = run([call(ref.dataset_id)], {"task": "分析", "dataset_refs": [ref.model_dump(mode="json")]},
        config, max_tool_calls=0)
    assert result["error"]["type"] == "tool_budget_exceeded"


def test_no_calculation_cannot_be_claimed_as_completed():
    _, _, ref, config = setup_data()
    result, _ = run([answer(), answer()], {"task": "分析", "dataset_refs": [ref.model_dump(mode="json")]}, config)
    assert result["status"] == "failed"


def test_model_failure_is_safe_and_empty_task_is_invalid():
    _, _, ref, config = setup_data()
    result, _ = run([RuntimeError("secret")], {"task": "分析", "dataset_refs": [ref.model_dump(mode="json")]}, config)
    assert result["error"]["type"] == "model_error"
    assert "secret" not in str(result)
    result, _ = run([], {"task": " "})
    assert result["error"]["type"] == "invalid_input"


def test_existing_artifact_can_be_reused_but_not_with_conflicting_assumptions():
    from src.analytics_tools import analyze_price_performance
    ds, store, ref, config = setup_data()
    created = json.loads(analyze_price_performance.invoke({"dataset_id": ref.dataset_id}, config=config))["analysis_ref"]
    inputs = {"task": "解释已有表现", "dataset_refs": [ref.model_dump(mode="json")], "existing_analysis_refs": [created]}
    result, llm = run([answer([created["analysis_id"]])], inputs, config)
    assert result["status"] == "completed"
    assert result["tool_calls_used"] == 0
    result, llm = run([], {**inputs, "assumptions": {"periods_per_year": 365}}, config)
    assert result["error"]["type"] == "invalid_reference"
    llm.invoke.assert_not_called()


def test_missing_metric_and_mock_data_produce_partial_result():
    ds, store, ref, config = setup_data(mode="mock")
    counter = iter(["call", "answer"])
    def respond(messages):
        if next(counter) == "call":
            return AIMessage(content="", tool_calls=[{"name": "compute_factors", "args": {
                "dataset_id": ref.dataset_id, "window": 20}, "id": "f1"}])
        return result_answer(messages)
    result, _ = run(respond, {"task": "计算因子", "dataset_refs": [ref.model_dump(mode="json")]}, config)
    assert result["status"] == "partial"
    assert result["result"]["missing_information"]
    assert any("模拟" in item for item in result["result"]["limitations"])


def test_explicit_assumptions_override_model_arguments():
    _, store, ref, config = setup_data()
    counter = iter(["call", "answer"])
    def respond(messages):
        if next(counter) == "call":
            return AIMessage(content="", tool_calls=[{"name": "compute_factors", "args": {
                "dataset_id": ref.dataset_id, "window": 20}, "id": "f1"}])
        return result_answer(messages)
    result, _ = run(respond, {"task": "2日因子", "dataset_refs": [ref.model_dump(mode="json")],
                             "assumptions": {"window": 2, "periods_per_year": 365}}, config)
    ref = result["result"]["analysis_refs"][0]
    assert ref["assumptions"]["window"] == 2
    assert ref["assumptions"]["periods_per_year"] == 365


def test_calculation_error_is_retained_in_partial_response():
    _, _, ref, config = setup_data()
    invalid = AIMessage(content="", tool_calls=[{"name": "compute_factors", "args": {
        "dataset_id": ref.dataset_id, "factors": ["unknown"]}, "id": "bad"}])
    result, _ = run([invalid, answer(missing_information=["无法完成该因子，请调整参数"],
        missing_data_requests=[{"kind": "price_history", "subjects": ["茅台"], "time_range": "一年",
                                "reason": "需要更长历史样本"}])],
        {"task": "分析", "dataset_refs": [ref.model_dump(mode="json")]}, config)
    assert result["status"] == "partial"
    assert result["tool_errors"]
    assert result["result"]["missing_data_requests"]


def test_old_messages_and_outputs_are_reset_between_invocations():
    from langchain_core.messages import HumanMessage
    _, _, ref, config = setup_data()
    result, llm = run([answer(missing_information=["需要更长样本"])], {"task": "分析",
        "dataset_refs": [ref.model_dump(mode="json")], "messages": [HumanMessage(content="OLD_SECRET")],
        "result": {"old": True}, "analysis_artifacts": [{"analysis_id": "old"}],
        "tool_calls_used": 99}, config)
    assert result["tool_calls_used"] == 0
    assert "OLD_SECRET" not in str(llm.invoke.call_args)
    assert result["status"] == "partial"
    assert result["analysis_artifacts"] == []


def test_foreign_analysis_artifact_is_rejected():
    from src.analytics_tools import analyze_price_performance
    ds, store, ref, config = setup_data()
    other = ds.put(ds.get(ref.dataset_id))
    foreign = json.loads(analyze_price_performance.invoke({"dataset_id": other.dataset_id}, config=config))["analysis_ref"]
    result, llm = run([], {"task": "分析", "dataset_refs": [ref.model_dump(mode="json")],
                           "existing_analysis_refs": [foreign]}, config)
    assert result["error"]["type"] == "invalid_reference"
    llm.invoke.assert_not_called()


def test_runtime_methodology_is_loaded_into_system_context_from_fixed_path(tmp_path, monkeypatch):
    from src.stages import analytics
    skill = tmp_path / "SKILL.md"
    skill.write_text('---\nname: analytics-methodology\ndescription: test\n---\n只选择完成当前问题所需的工具。', encoding="utf-8")
    monkeypatch.setattr(analytics, "METHODOLOGY_PATH", skill)
    monkeypatch.chdir(tmp_path)  # Loading must not depend on launch cwd.
    _, _, ref, config = setup_data()
    result, llm = run([answer(missing_information=["需补充背景"])],
        {"task": "分析", "dataset_refs": [ref.model_dump(mode="json")]}, config)
    system = [msg.content for msg in llm.invoke.call_args.args[0] if msg.type == "system"]
    assert any("只选择完成当前问题所需的工具。" in text for text in system)
    assert any("analysis_ids" in text for text in system)  # Output schema still present.
    assert result["status"] == "partial"


def test_missing_methodology_returns_explicit_failure_without_model(tmp_path, monkeypatch):
    from src.stages import analytics
    monkeypatch.setattr(analytics, "METHODOLOGY_PATH", tmp_path / "missing.md")
    _, _, ref, config = setup_data()
    result, llm = run([], {"task": "分析", "dataset_refs": [ref.model_dump(mode="json")]}, config)
    assert result["error"]["type"] == "methodology_unavailable"
    llm.invoke.assert_not_called()


def test_repository_methodology_is_nonempty_and_reloaded_after_edits(tmp_path, monkeypatch):
    from src.stages import analytics
    body = analytics.load_analytics_methodology()
    assert "analyze_price_performance" in body
    assert "compare_valuations" in body
    skill = tmp_path / "SKILL.md"
    monkeypatch.setattr(analytics, "METHODOLOGY_PATH", skill)
    skill.write_text("第一版方法", encoding="utf-8")
    assert analytics.load_analytics_methodology() == "第一版方法"
    skill.write_text("第二版方法", encoding="utf-8")
    assert analytics.load_analytics_methodology() == "第二版方法"
    skill.write_text(" ", encoding="utf-8")
    import pytest
    with pytest.raises(ValueError):
        analytics.load_analytics_methodology()


def test_valuation_references_cannot_be_dismissed_without_computation():
    from src.datasets import ValuationDataset
    ds, store, _, config = setup_data()
    refs = [ds.put(ValuationDataset(kind='valuation_snapshot', symbol=symbol, market=market,
        currency='CNY', provider='test', retrieved_at=datetime.now(timezone.utc), data_mode='real',
        as_of_date=date(2025, 1, 3), metrics={
            'pe_ttm': {'value': pe, 'unit': 'multiple', 'basis': 'PE_TTM'},
            'pb': {'value': pb, 'unit': 'multiple', 'basis': 'PB_MRQ'}})).model_dump(mode='json')
        for symbol, market, pe, pb in [('600519', 'SSE', 21., 6.), ('000858', 'SZSE', 23., 2.)]]
    llm = Mock(); llm.bind_tools.return_value = llm
    replies = iter([False, True])
    def respond(messages):
        return result_answer(messages) if next(replies) else answer(missing_information=['未看到估值字段'])
    llm.invoke.side_effect = respond
    with patch('src.stages.analytics.create_llm', return_value=llm):
        result = create_analytics_agent().invoke({'task': '比较茅台和五粮液估值', 'dataset_refs': refs}, config=config)
    assert result['status'] == 'completed'
    assert result['tool_calls_used'] == 1
    assert result['result']['findings'][0]['metrics']['pe_ttm.median'] == 22.
