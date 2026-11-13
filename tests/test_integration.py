"""Opt-in live parent-graph integration tests (DASHSCOPE_API_KEY required)."""
import json
import os

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def api_key():
    key = os.getenv("DASHSCOPE_API_KEY")
    if not key:
        pytest.skip("DASHSCOPE_API_KEY 未设置")
    return key


def test_market_data_parent_response(api_key):
    from src.agent import run_invest_agent
    state = run_invest_agent("查询上证指数最新可用行情")
    assert state["planning_status"] == "ready"
    assert any(t["category"] == "market_data" for t in state["plan"]["tasks"])
    assert state["final_response"].strip()


def test_report_results_are_task_local(api_key):
    from src.agent import run_invest_agent
    from src.stages.reporter import validate_report
    state = run_invest_agent("请生成新能源行业中期投研报告，重点关注光伏。")
    assert state["planning_status"] == "ready"
    reports = [r for r in state["task_results"].values() if r["category"] == "report"]
    assert reports, "明确报告请求必须规划 report 任务"
    for record in reports:
        assert record["status"] in {"completed", "partial"}, record.get("error")
        payload = record["result"]
        for key in ("perception_data", "world_model", "reasoning_plans", "selected_plan", "final_report"):
            assert payload.get(key) is not None
        errors = validate_report(json.loads(payload["final_report"]))
        if record["status"] == "completed":
            assert not errors
    assert "final_report" not in state
