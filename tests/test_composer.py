"""Composer safety boundaries and Supervisor wiring, without external APIs."""
from unittest.mock import Mock, patch

from src.stages.composer import composer
from src.response_graph import create_response_graph


def record(ident="m", category="market_data", status="completed", result=None):
    return {"task_id": ident, "category": category, "question": "查询股价", "depends_on": [],
            "status": status, "result": result if result is not None else {
                "answer": "价格100元", "evidence": [], "missing_information": []},
            "error": {"type": status, "message": "任务不可用"} if status in {"failed", "blocked", "unsupported"} else None}


def state(*records):
    return {"user_query": "查询股价并分析", "task_results": {r["task_id"]: r for r in records},
            "supervisor_status": "completed"}


def test_composer_passes_original_query_and_preserves_task_statuses():
    chain = Mock(); chain.invoke.return_value = {"answer": "查询到价格100元。"}
    with patch("src.stages.composer._create_chain", return_value=chain):
        result = composer(state(record(), {**record("a", "analytics", "unsupported"), "result": None}))
    assert "100元" in result["final_response"]
    assert "尚未接入" in result["final_response"]
    assert "a" in result["final_response"]
    assert chain.invoke.call_args.args[0]["user_query"] == "查询股价并分析"


def test_report_body_and_intermediates_never_reach_composer_model():
    chain = Mock(); chain.invoke.return_value = {"answer": "报告任务已处理。"}
    r = record("r", "report", result={"final_report": "SECRET_REPORT", "world_model": "SECRET_MODEL"})
    with patch("src.stages.composer._create_chain", return_value=chain):
        result = composer(state(r))
    assert "SECRET" not in str(chain.invoke.call_args)
    assert "SECRET" not in result["final_response"]
    assert "暂时隐藏" in result["final_response"]


def test_model_failure_falls_back_to_available_results():
    chain = Mock(); chain.invoke.side_effect = RuntimeError("secret")
    with patch("src.stages.composer._create_chain", return_value=chain):
        result = composer(state(record()))
    assert result["composition_status"] == "fallback"
    assert "100元" in result["final_response"]
    assert "secret" not in str(result)


def test_empty_model_output_uses_fallback():
    chain = Mock(); chain.invoke.return_value = {"answer": " "}
    with patch("src.stages.composer._create_chain", return_value=chain):
        result = composer(state(record()))
    assert result["composition_status"] == "fallback"


def test_clarification_and_total_failure_do_not_call_model():
    with patch("src.stages.composer._create_chain") as factory:
        result = composer({"supervisor_status": "needs_clarification", "plan": {
            "clarification_questions": ["请问哪家公司？"]}, "task_results": {}})
        assert "哪家公司" in result["final_response"]
        assert result["composition_status"] == "needs_clarification"
        failed = composer(state(record(status="failed", result={})))
        assert "失败" in failed["final_response"]
        factory.assert_not_called()


def test_missing_data_mock_mode_and_sources_are_visible():
    r = record(status="partial", result={"answer": "100元", "missing_information": ["缺少交易日期"],
        "evidence": [{"tool_name": "quote", "retrieved_at": "2026-11-10", "as_of_date": None,
                      "data_mode": "mock", "source_url": "https://example.com"}]})
    chain = Mock(); chain.invoke.return_value = {"answer": "结果仅供演示。"}
    with patch("src.stages.composer._create_chain", return_value=chain):
        result = composer(state(r))
    for text in ("缺少交易日期", "mock", "2026-11-10", "https://example.com", "部分完成"):
        assert text in result["final_response"]


def test_supervisor_then_composer_graph_preserves_records():
    md = Mock(); md.invoke.return_value = {"status": "completed", "error": None,
        "result": {"answer": "100元", "evidence": [], "evidence_ids": [], "missing_information": []}}
    report = Mock()
    chain = Mock(); chain.invoke.return_value = {"answer": "股价100元。"}
    task = {"task_id": "m", "category": "market_data", "question": "查茅台价格", "depends_on": []}
    graph = create_response_graph(market_data_graph=md, report_graph=report)
    with patch("src.stages.composer._create_chain", return_value=chain):
        result = graph.invoke({"user_query": "茅台多少钱？", "plan": {
            "status": "ready", "tasks": [task], "clarification_questions": []}})
    assert "100元" in result["final_response"]
    assert result["task_results"]["m"]["status"] == "completed"
    assert result["user_query"] == "茅台多少钱？"
    report.invoke.assert_not_called()


def test_real_chain_and_json_validation_with_mock_model():
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda
    with patch("src.stages.composer.create_llm", return_value=RunnableLambda(
            lambda prompt: AIMessage(content='{"answer": "价格100元。"}'))):
        result = composer(state(record()))
    assert result["composition_status"] == "completed"


def test_response_graph_handles_invalid_plan_without_model_and_clears_old_answer():
    graph = create_response_graph(market_data_graph=Mock(), report_graph=Mock())
    with patch("src.stages.composer._create_chain") as factory:
        result = graph.invoke({"user_query": "查询", "plan": None, "final_response": "old answer"})
    assert result["composition_status"] == "failed"
    assert "old answer" not in result["final_response"]
    factory.assert_not_called()


def test_incomplete_execution_is_not_composed():
    with patch("src.stages.composer._create_chain") as factory:
        result = composer({**state(record()), "supervisor_status": "running"})
    assert result["composition_status"] == "failed"
    factory.assert_not_called()


def test_invalid_result_identity_is_rejected_before_model_call():
    broken = state(record())
    broken["task_results"] = {"wrong": record()}
    with patch("src.stages.composer._create_chain") as factory:
        result = composer(broken)
    assert result["composition_error"]["type"] == "invalid_task_results"
    factory.assert_not_called()


def test_failed_task_error_is_displayed_without_model():
    broken = record(status="failed", result={})
    broken["error"] = {"type": "invalid_output", "message": "输出格式或证据引用验证失败。"}
    with patch("src.stages.composer._create_chain") as factory:
        result = composer(state(broken))
    assert "invalid_output" in result["final_response"]
    assert "证据引用" in result["final_response"]
    factory.assert_not_called()


def analytical_record():
    return record("a", "analytics", "partial", {"summary": "历史表现分析", "findings": [{
        "analysis_id": "analysis1", "tool_name": "analyze_price_performance", "metrics": {
            "period_return": .05, "annualized_volatility": None},
        "metric_units": {"period_return": "fraction", "annualized_volatility": "fraction"}, "table": []}],
        "analysis_refs": [{"analysis_id": "analysis1", "start_date": "2025-01-01", "end_date": "2025-12-31", "sample_size": 200}],
        "chart_refs": [], "dataset_refs": [{"dataset_id": "d", "symbol": "600519", "provider": "test",
            "start_date": "2025-01-01", "end_date": "2025-12-31", "data_mode": "mock", "adjustment": "qfq"}],
        "assumptions": {"effective": {"analysis1": {"periods_per_year": 252}}},
        "limitations": ["样本不足，历史不代表未来"], "missing_information": ["波动率不可用"],
        "missing_data_requests": [{"kind": "price_history", "subjects": ["600519"], "time_range": "一年",
                                   "reason": "补充有效样本"}]})


def test_composer_includes_analytics_metrics_assumptions_and_limits():
    chain = Mock(); chain.invoke.return_value = {"answer": "历史收益5%，部分指标不可用。"}
    with patch("src.stages.composer._create_chain", return_value=chain):
        result = composer(state(analytical_record()))
    assert "5.00%" in result["final_response"]
    for text in ("252", "波动率不可用", "样本不足", "mock", "qfq", "2025-12-31", "补充有效样本"):
        assert text in result["final_response"]
    assert "period_return" in chain.invoke.call_args.args[0]["task_results"]


def test_analytics_metrics_remain_visible_when_composition_model_fails():
    chain = Mock(); chain.invoke.side_effect = RuntimeError("offline")
    with patch("src.stages.composer._create_chain", return_value=chain):
        result = composer(state(analytical_record()))
    assert result["composition_status"] == "fallback"
    assert "5.00%" in result["final_response"]
    assert "不可用" in result["final_response"]


def test_invalid_numeric_analysis_is_rejected_without_model_call():
    broken = analytical_record()
    broken["result"]["findings"][0]["metrics"]["period_return"] = float("nan")
    with patch("src.stages.composer._create_chain") as factory:
        result = composer(state(broken))
    assert result["composition_error"]["type"] == "invalid_task_results"
    factory.assert_not_called()
