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
        ((), "updates", {"composer": {"final_response": final, "composition_status": "completed",
                                      "composition_summary": final}}),
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


def page_text(at):
    """Visible text from markdown and st.html blocks (the shell renders its cards with st.html)."""
    return " ".join([str(m.value) for m in at.markdown] + [e.proto.body for e in at.get("html")])


def open_view(at, name):
    next(b for b in at.button if b.label.endswith(name)).click()
    at.run()
    assert not at.exception


def test_home_shows_hero_examples_capabilities_and_navigation():
    at = AppTest.from_file(_APP).run()
    assert not at.exception
    assert not at.tabs  # No result views before the first question.
    page = page_text(at)
    assert "想研究什么" in page and "行业研究报告" in page and "不构成任何投资建议" in page
    labels = {b.label for b in at.button}
    assert {"当前对话", "报告中心", "研究记录"} <= {label.split(" ")[-1] for label in labels}
    assert any("不知道从哪里开始" in e.label for e in at.expander)


def test_status_pill_reflects_data_mode_honestly():
    at = AppTest.from_file(_APP).run()
    page = page_text(at)
    assert "上下文保留最近 3 轮" in page
    assert ("真实数据" in page) or ("模拟数据" in page)
    assert "数据服务正常" not in page  # Import success is not upstream health.


def test_result_view_shows_question_card_and_history_lists_turns():
    at = submit(fake())
    page = page_text(at)
    assert "你的问题" in page and "茅台价格" in page
    open_view(at, "研究记录")
    page = page_text(at)
    assert "茅台价格" in page and "仅当前会话" in page


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


def test_report_nodes_remain_visible_when_final_report_is_unreadable():
    payload = {"perception_data": {"market_overview": "市场证据"}, "world_model": {"market_state": "震荡"},
               "reasoning_plans": [], "selected_plan": {"investment_thesis": "决策依据"},
               "final_report": "SECRET_REPORT"}
    at = submit(fake({"r": task("r", "report", result=payload)}, final="报告内容不可读取，请查看节点结果"))
    assert {h.value for h in next(t for t in at.tabs if t.label=='报告生成过程').subheader} >= {"perception_data", "world_model", "reasoning_plans", "selected_plan"}
    assert len(next(t for t in at.tabs if t.label=='报告生成过程').json) == 4
    assert "SECRET_REPORT" not in str([j.value for j in at.json])


def test_rerender_does_not_execute_again_and_new_chat_clears_summary():
    graph = fake()
    at = submit(graph)
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
    graph = Mock()
    graph.stream.return_value = iter([
        ((), "updates", {"planner": {"planning_status": "needs_clarification", "plan": {
            "status": "needs_clarification", "tasks": [], "clarification_questions": ["哪家公司？"]}}}),
        ((), "updates", {"composer": {"final_response": "哪家公司？", "composition_status": "needs_clarification"}})])
    at = submit(graph)
    assert "哪家公司" in at.session_state["last_result"]["final_response"]
    assert any("补充" in item.value for item in at.info)


def test_real_parent_stream_drives_ui_with_mocked_specialists():
    from src.orchestration.parent_graph import create_parent_graph
    md = Mock()
    md.invoke.return_value = {"status": "completed", "error": None, "result": {
        "answer": "实际父图100元", "evidence": [], "evidence_ids": [], "missing_information": []}}
    planning = Mock()
    planning.invoke.return_value = {"status": "ready", "tasks": [
        {"task_id": "m", "category": "market_data", "question": "查茅台", "depends_on": []}],
        "clarification_questions": []}
    composing = Mock()
    composing.invoke.return_value = {"answer": "实际父图100元"}
    with patch("src.orchestration.planner._create_chain", return_value=planning), patch(
            "src.orchestration.composer._create_chain", return_value=composing):
        at = submit(create_parent_graph(market_data_graph=md, report_graph=Mock()))
    assert at.session_state["last_result"]["task_results"]["m"]["status"] == "completed"
    assert "实际父图100元" in at.session_state["last_result"]["final_response"]
    assert "messages" not in at.session_state["last_result"]


def test_debug_views_show_plan_dispatch_and_market_tool_calls():
    from langchain_core.messages import AIMessage, ToolMessage
    graph = fake()
    events = list(graph.stream.return_value)
    events[2:2] = [
        (("supervisor:s", "market:m"), "updates", {"agent": {"messages": [AIMessage(content="", tool_calls=[
            {"name": "get_stock_performance", "args": {"query": "茅台"}, "id": "c1"},
            {"name": "get_stock_performance", "args": {"query": "五粮液"}, "id": "c2"}])]}}),
        (("supervisor:s", "market:m"), "updates", {"tools": {"messages": [
            ToolMessage(content="茅台100元", tool_call_id="c1")], "tool_rounds": 1, "tool_calls_used": 2}}),
        (("supervisor:s", "market:m"), "updates", {"finalize": {"status": "completed", "result": {"answer": "100元"}}}),
    ]
    graph.stream.return_value = iter(events)
    at = submit(graph)
    trace = at.session_state["debug_events"]
    tool_request = next(e for e in trace if e["node"] == "agent")
    assert len(tool_request["details"]["messages"][0]["tool_calls"]) == 2
    assert "五粮液" in str(tool_request)
    assert any(e["details"].get("tool_rounds") == 1 for e in trace)
    assert any("Planner" in e.label for e in at.expander)
    assert any("Supervisor" in e.label for e in at.expander)
    assert any("Market Data" in e.label for e in at.expander)
    assert "messages" not in at.session_state["last_result"]


def test_analytics_dashboard_charts_survive_rerun_without_reexecution():
    from tests.test_analytics_dashboard import artifact
    snapshot = artifact().model_dump(mode="json")
    summary = {key: value for key, value in snapshot.items() if key != "series"}
    summary["chart_refs"] = [{"analysis_id": "a1", "series_key": key} for key in snapshot["series"]]
    payload = {"summary": "区间表现", "findings": [], "analysis_refs": [summary],
               "dataset_refs": snapshot["dataset_refs"], "missing_information": [], "missing_data_requests": []}
    graph = fake({"a": task("a", "analytics", result=payload)})
    events = list(graph.stream.return_value)
    events.insert(2, (("s",), "custom", {"event": "analysis_artifacts", "task_id": "a", "artifacts": {"a1": snapshot}}))
    graph.stream.return_value = iter(events)
    at = submit(graph)
    assert len(at.get("plotly_chart")) == 2
    assert any(item.label == "区间收益" for item in at.metric)
    assert at.session_state["analysis_snapshots"]["a"]["a1"]["series"]
    at.run()
    assert not at.exception
    assert len(at.get("plotly_chart")) == 2
    assert graph.stream.call_count == 1
    next(b for b in at.button if "新对话" in b.label).click()
    at.run()
    assert at.session_state["analysis_snapshots"] == {}


def test_analytics_dashboard_missing_snapshot_preserves_metrics_without_fake_chart():
    from tests.test_analytics_dashboard import artifact
    data = artifact().model_dump(mode="json")
    data.pop("series")
    graph = fake({"a": task("a", "analytics", result={"summary": "表现", "analysis_refs": [data],
        "dataset_refs": data["dataset_refs"], "missing_information": [], "missing_data_requests": []})})
    at = submit(graph)
    assert not at.get("plotly_chart")
    assert any("没有可解析" in item.value for item in at.warning)
    assert at.metric


def test_planner_diagnostic_events_display_and_survive_rerun():
    graph = fake()
    old = list(graph.stream.return_value)
    event = {'event': 'planner_attempt', 'run_id': 'test-run', 'stage': 'planner', 'attempt': 1,
             'status': 'validation_failed', 'diagnostics': [{'field': 'tasks.0.analytics_parameters.assumptions',
             'received_type': 'str', 'expected': 'JSON object', 'hint': '请使用对象'}]}
    graph.stream.return_value = iter([((), 'custom', event)] + old)
    at = submit(graph)
    assert any('planner_attempt' in x.value for x in at.json)
    assert any(e['node'] == 'planner_attempt' for e in at.session_state['debug_events'])
    at.run()
    assert any('JSON object' in x.value for x in at.json)
    assert not at.exception


def test_strategy_results_display_deterministic_checks_and_scenarios():
    from src.specialists.strategy.agent import create_strategy_agent
    from tests.test_strategy_agent import answer
    from tests.test_strategy_tools import context
    _,cfg=context()
    llm=Mock()
    llm.bind_tools.return_value=llm
    llm.invoke.side_effect=answer
    with patch('src.specialists.strategy.nodes.create_llm',return_value=llm):
        result=create_strategy_agent().invoke(cfg['configurable']['strategy_input'],config=cfg)
    record=task('s','investment_strategy',result=result['result'])
    at=submit(fake({'s':record}, final='策略结果'))
    assert any(m.label=='情景组合收益' and m.value=='-8.00%' for m in at.metric)
    assert any('violated' in str(d.value) for d in at.dataframe)
    at.run()
    assert not at.exception
    assert any(m.label=='情景组合收益' for m in at.metric)


def test_strategy_field_diagnostics_are_visible_in_execution_record():
    graph=fake()
    old=list(graph.stream.return_value)
    event={'event':'strategy_diagnostic','stage':'strategy','error_type':'invalid_strategy_input',
           'message':'输入无效','diagnostics':[{'field':'portfolio.as_of_date','received_type':'missing'}]}
    graph.stream.return_value=iter([((), 'custom', event)]+old)
    at=submit(graph)
    assert any('portfolio.as_of_date' in item.value for item in at.json)


def test_completed_report_can_be_read_and_downloaded_without_reexecution(valid_report):
    import json
    graph=fake({'r':task('r','report',result={'final_report':json.dumps(valid_report,ensure_ascii=False),
        'perception_data':{'market_overview':'市场证据'}})},final='报告已生成')
    at=submit(graph)
    open_view(at, '报告中心')
    assert any(valid_report['research_topic'] in m.value for m in at.markdown)
    buttons=at.get('download_button')
    assert len(buttons)==2
    assert {'下载 Markdown','下载 HTML'}=={b.proto.label for b in buttons}
    at.run()
    assert not at.exception and graph.stream.call_count==1
    next(b for b in at.button if '新对话' in b.label).click()
    at.run()
    open_view(at, '报告中心')
    assert not at.get('download_button')


def test_failed_report_cannot_be_downloaded_as_completed(valid_report):
    record=task('r','report','failed',result={'final_report':valid_report})
    record['error']={'type':'report_failed','message':'报告流程失败'}
    at=submit(fake({'r':record},status='failed',final='报告失败'))
    open_view(at, '报告中心')
    assert not at.get('download_button')


def test_partial_report_is_draft_and_multiple_reports_have_distinct_downloads(valid_report):
    record=task('r1','report','partial',result={'final_report':valid_report})
    another=task('r2','report',result={'final_report':valid_report})
    at=submit(fake({'r1':record,'r2':another},status='partial'))
    open_view(at, '报告中心')
    assert len(at.get('download_button'))==4
    assert any('草稿' in item.value for item in at.warning)


def test_product_views_and_collapsed_developer_area_are_separated():
    at=submit(fake())
    labels=[t.label for t in at.tabs]
    assert set(labels) == {'报告生成过程','任务规划与调度','专家执行记录'}  # Product results are one page, not tabs.
    debug=next(e for e in at.expander if e.label=='开发者调试')
    assert debug.proto.expanded is False


def test_example_click_only_fills_input_and_report_center_offers_report_example():
    with patch('src.agent.create_invest_agent') as factory:
        at=AppTest.from_file(_APP).run()
        next(b for b in at.button if b.label=='比较两家公司').click()
        at.run()
        assert '收益、波动率和最大回撤' in at.text_area(key='query_input').value
        factory.assert_not_called()
        open_view(at, '报告中心')
        next(b for b in at.button if b.label=='试试生成报告').click()
        at.run()
        assert at.session_state['view'] == '当前对话'  # Filling an example returns to the input.
        assert '请生成新能源行业' in at.text_area(key='query_input').value
        factory.assert_not_called()


def test_progress_panel_follows_real_events_and_run_time_is_recorded():
    import app.progress as progress
    calls = []
    real = progress.progress_html
    def spy(steps, elapsed):
        calls.append([(s["label"], s["state"]) for s in steps])
        return real(steps, elapsed)
    with patch("app.progress.progress_html", side_effect=spy):
        at = submit(fake())
    assert calls[0] == [("理解问题并规划任务", "active"), ("汇总回答", "pending")]
    assert ("数据采集", "done") in calls[-1] and calls[-1][-1] == ("汇总回答", "done")
    assert isinstance(at.session_state["conversation_history"][-1]["seconds"], int)
    assert "正在进行深度研究" not in page_text(at)  # Panel is cleared once results are shown.


def evidence_task():
    return task(result={"answer": "茅台最新收盘100元", "missing_information": ["缺少分红数据"], "evidence": [
        {"tool_call_id": "c1", "tool_name": "get_price_history", "content": "{}", "status": "returned",
         "retrieved_at": "2026-11-14T10:00:00+00:00", "data_mode": "real", "as_of_date": "2026-11-13",
         "source_url": "https://finance.sina.com.cn/"}]})


def test_result_page_has_answer_head_summary_sections_and_sources():
    at = submit(fake({"m": evidence_task()}, final="茅台最新收盘100元。"))
    page = page_text(at)
    assert "InvestAgent 研究助手" in page and "用时" in page and "1 条数据证据" in page
    assert "核心结论" in page and "茅台最新收盘100元。" in page
    assert "数据与证据" in page and "01" in page
    assert any("缺少分红数据" in w.value for w in at.warning)
    sources = next(e for e in at.expander if "参考来源" in e.label)
    assert sources.dataframe[0].value["工具"].tolist() == ["get_price_history"]


def test_fallback_answer_is_never_shown_as_a_model_summary():
    graph = fake()
    events = list(graph.stream.return_value)
    events[-1] = ((), "updates", {"composer": {"final_response": "逐任务明细", "composition_status": "fallback",
                                               "composition_summary": None}})
    graph.stream.return_value = iter(events)
    at = submit(graph)
    assert "核心结论" not in page_text(at)
    assert any("汇总生成失败" in w.value for w in at.warning)
    assert any("逐任务" in e.label for e in at.expander)


def test_report_section_links_to_report_center(valid_report):
    import json
    at = submit(fake({"r": task("r", "report", result={"final_report": json.dumps(valid_report, ensure_ascii=False)})},
                     final="报告已生成"))
    assert "研究报告" in page_text(at)
    next(b for b in at.button if "前往报告中心" in b.label).click()
    at.run()
    assert at.session_state["view"] == "报告中心" and at.get("download_button")
