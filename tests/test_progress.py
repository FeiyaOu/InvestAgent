"""Research progress steps are derived from real planner/task events, not a fixed script."""
from app.progress import build_steps, progress_html

PLAN = {"status": "ready", "clarification_questions": [], "tasks": [
    {"task_id": "prices", "category": "market_data", "question": "批量采集茅台、五粮液近一年日线", "depends_on": []},
    {"task_id": "matrix", "category": "analytics", "question": "构建收益矩阵", "depends_on": ["prices"]},
    {"task_id": "risk", "category": "investment_strategy", "question": "评估组合风险", "depends_on": ["matrix"]}]}


def states(steps):
    return [step["state"] for step in steps]


def test_before_plan_only_planning_is_active():
    steps = build_steps({}, active_task=None, planner_attempts=[])
    assert [s["label"] for s in steps] == ["理解问题并规划任务", "汇总回答"]
    assert states(steps) == ["active", "pending"]


def test_planner_retry_is_visible():
    steps = build_steps({}, None, [{"attempt": 1, "status": "validation_failed"}, {"attempt": 2, "status": "started"}])
    assert "第 2 次" in steps[0]["detail"]


def test_tasks_follow_plan_order_and_real_statuses():
    state = {"plan": PLAN, "planning_status": "ready",
             "task_results": {"prices": {"status": "completed"}}}
    steps = build_steps(state, active_task="matrix", planner_attempts=[])
    assert [s["label"] for s in steps] == ["理解问题并规划任务", "数据采集", "计算分析", "策略与风险", "汇总回答"]
    assert states(steps) == ["done", "done", "active", "pending", "pending"]
    assert steps[1]["detail"] == "批量采集茅台、五粮液近一年日线"


def test_partial_failed_and_blocked_are_not_shown_as_done():
    state = {"plan": PLAN, "planning_status": "ready", "supervisor_status": "partial",
             "task_results": {"prices": {"status": "partial"}, "matrix": {"status": "failed"},
                              "risk": {"status": "blocked"}}}
    assert states(build_steps(state, "risk", []))[1:4] == ["partial", "failed", "failed"]


def test_composer_step_tracks_final_answer():
    running = {"plan": PLAN, "planning_status": "ready", "supervisor_status": "completed",
               "task_results": {t["task_id"]: {"status": "completed"} for t in PLAN["tasks"]}}
    assert build_steps(running, "risk", [])[-1]["state"] == "active"
    assert build_steps({**running, "final_response": "完成"}, "risk", [])[-1]["state"] == "done"


def test_clarification_and_planning_failure_skip_tasks():
    clarify = build_steps({"planning_status": "needs_clarification", "plan": {"status": "needs_clarification",
                           "tasks": [], "clarification_questions": ["哪家公司？"]}}, None, [])
    assert states(clarify) == ["done", "active"] and "澄清" in clarify[0]["detail"]
    failed = build_steps({"planning_status": "failed"}, None, [])
    assert states(failed)[0] == "failed"


def test_html_shows_progress_counts_elapsed_and_escapes_text():
    state = {"plan": {**PLAN, "tasks": [{**PLAN["tasks"][0], "question": "<script>x</script>"}]},
             "planning_status": "ready", "task_results": {"prices": {"status": "completed"}}}
    html = progress_html(build_steps(state, "prices", []), elapsed=12.4)
    assert "正在进行深度研究" in html and "已用时 12 秒" in html and "已完成 1/1 个任务" in html
    assert "<script>" not in html
