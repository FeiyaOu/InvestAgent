"""Streamlit parent-graph UI migration; no external API calls."""
from pathlib import Path
from unittest.mock import Mock, patch
from streamlit.testing.v1 import AppTest

_APP = str(Path(__file__).parent.parent / "app" / "streamlit_app.py")


def task(ident="m", category="market_data", status="completed", result=None):
    return {"task_id": ident, "category": category, "question": "查询茅台", "depends_on": [],
            "status": status, "result": result or {"answer": "100元", "evidence": [], "missing_information": []},
            "error": None}


def fake(records=None, status="completed", final="查询到100元"):
    records = records or {"m": task()}
    plan = {"status": "ready", "tasks": [{k: r[k] for k in ("task_id", "category", "question", "depends_on")}
            for r in records.values()], "clarification_questions": []}
    graph = Mock()
    graph.stream.return_value = iter([
        ((), "updates", {"planner": {"plan": plan, "planning_status": "ready"}}),
        (("supervisor:test",), "custom", {"event": "task_started", "task_id": next(iter(records)),
                                             "category": next(iter(records.values()))["category"]}),
        (("supervisor:test",), "updates", {"supervisor": {"task_results": records}}),
        ((), "updates", {"supervisor": {"task_results": records, "supervisor_status": status}}),
        ((), "updates", {"composer": {"final_response": final, "composition_status": "completed"}}),
    ])
    return graph


def submit(graph, history=None):
    with patch("src.agent.create_invest_agent", return_value=graph):
        at = AppTest.from_file(_APP, default_timeout=30)
        at.run()
        if history:
            at.session_state["conversation_history"] = history
        at.text_area(key="query_input").input("茅台价格")
        next(b for b in at.button if "运行研究任务" in b.label).click()
        at.run()
    assert not at.exception
    return at


def test_parent_answer_and_explicit_summary_without_checkpoint():
    graph = fake()
    at = submit(graph, [{"query": "研究茅台", "response_preview": "此前结果", "status": "completed"}])
    assert "研究茅台" in graph.stream.call_args.args[0]["conversation_context"]
    assert "此前结果" in graph.stream.call_args.args[0]["conversation_context"]
    assert "100元" in at.session_state["last_result"]["final_response"]
    graph.get_state.assert_not_called()
    assert any("没有 checkpoint" in item.value for item in at.caption)


def test_partial_state_is_not_silent_success():
    records = {"a": {**task("a", "analytics", "unsupported"), "result": None,
                     "error": {"type": "capability_unavailable", "message": "尚未接入"}}}
    at = submit(fake(records, status="failed", final="分析能力尚未接入"))
    assert any("未完成" in item.value for item in at.error)
    assert "unsupported" in str(at.dataframe[0].value)


def test_report_nodes_visible_and_report_body_hidden():
    payload = {"perception_data": {"market_overview": "市场证据"}, "world_model": {"market_state": "震荡"},
               "reasoning_plans": [], "selected_plan": {"investment_thesis": "决策依据"},
               "final_report": "SECRET_REPORT"}
    at = submit(fake({"r": task("r", "report", result=payload)}, final="报告正文暂时隐藏"))
    assert {h.value for h in at.tabs[3].subheader} >= {"perception_data", "world_model", "reasoning_plans", "selected_plan"}
    assert len(at.tabs[3].json) == 4
    assert "SECRET_REPORT" not in str([j.value for j in at.json])


def test_rerender_does_not_execute_again_and_new_chat_clears_summary():
    graph = fake(); at = submit(graph)
    at.run()
    assert graph.stream.call_count == 1
    next(b for b in at.button if "新对话" in b.label).click()
    at.run()
    assert at.session_state["conversation_history"] == []
    assert at.session_state["last_result"] is None


def test_multiple_reports_stream_under_their_task_ids():
    graph = fake({"r1": task("r1", "report", result={"perception_data": {"topic": "A"}}),
                  "r2": task("r2", "report", result={"perception_data": {"topic": "B"}})})
    events = list(graph.stream.return_value)
    events[2:2] = [
        (("s", "r"), "updates", {"perception": {"perception_data": {"topic": "A"}}}),
        (("s",), "custom", {"event": "task_started", "task_id": "r2", "category": "report"}),
        (("s", "r"), "updates", {"perception": {"perception_data": {"topic": "B"}}}),
    ]
    graph.stream.return_value = iter(events)
    at = submit(graph)
    assert at.session_state["report_progress"]["r1"]["perception_data"]["topic"] == "A"
    assert at.session_state["report_progress"]["r2"]["perception_data"]["topic"] == "B"


def test_clarification_display_skips_task_execution():
    graph = Mock(); graph.stream.return_value = iter([
        ((), "updates", {"planner": {"planning_status": "needs_clarification", "plan": {
            "status": "needs_clarification", "tasks": [], "clarification_questions": ["哪家公司？"]}}}),
        ((), "updates", {"composer": {"final_response": "哪家公司？", "composition_status": "needs_clarification"}})])
    at = submit(graph)
    assert "哪家公司" in at.session_state["last_result"]["final_response"]
    assert any("补充" in item.value for item in at.info)


def test_real_parent_stream_drives_ui_with_mocked_specialists():
    from src.parent_graph import create_parent_graph
    md = Mock(); md.invoke.return_value = {"status": "completed", "error": None, "result": {
        "answer": "实际父图100元", "evidence": [], "evidence_ids": [], "missing_information": []}}
    planning = Mock(); planning.invoke.return_value = {"status": "ready", "tasks": [
        {"task_id": "m", "category": "market_data", "question": "查茅台", "depends_on": []}],
        "clarification_questions": []}
    composing = Mock(); composing.invoke.return_value = {"answer": "实际父图100元"}
    with patch("src.stages.planner._create_chain", return_value=planning), patch(
            "src.stages.composer._create_chain", return_value=composing):
        at = submit(create_parent_graph(market_data_graph=md, report_graph=Mock()))
    assert at.session_state["last_result"]["task_results"]["m"]["status"] == "completed"
    assert "实际父图100元" in at.session_state["last_result"]["final_response"]
    assert "messages" not in at.session_state["last_result"]
