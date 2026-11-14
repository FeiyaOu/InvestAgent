"""P0b: plan-time stock identity check against the snapshot, repaired through the planner loop."""
import json
from unittest.mock import Mock, patch

import pytest
from langchain_core.messages import AIMessage

from src.orchestration.planner import planner
from src.orchestration.planner_schemas import TaskPlan
from src.orchestration.security_check import SecurityIdentityError, validate_plan_securities

DIRECTORY = {"generated_at": "2026-11-14", "securities": {
    "600519": "贵州茅台", "600809": "山西汾酒", "600829": "人民同泰", "000568": "泸州老窖", "600036": "招商银行"}}


@pytest.fixture(autouse=True)
def directory(monkeypatch):
    monkeypatch.setattr("src.data.tools._DIRECTORY_CACHE", DIRECTORY)


def plan(question, **extra):
    return {"status": "ready", "clarification_questions": [], "tasks": [
        {"task_id": "prices", "category": "market_data", "question": question, "depends_on": []}, *extra.get("more", [])]}


def strategy_task(positions):
    return {"task_id": "risk", "category": "investment_strategy", "question": "评估组合风险", "depends_on": [],
            "strategy_parameters": {"portfolio": {"as_of_date": "2026-11-13", "currency": "CNY", "cash_weight": .5,
                                                  "positions": positions}}}


def test_consistent_or_name_only_mentions_pass():
    validate_plan_securities(TaskPlan.model_validate(plan("获取贵州茅台(600519)、泸州老窖和山西汾酒近一年日线")))


def test_question_mismatch_names_the_correct_code():
    with pytest.raises(SecurityIdentityError) as exc:
        validate_plan_securities(TaskPlan.model_validate(plan("获取贵州茅台(600519)、山西汾酒(600829)近一年日线")))
    assert "prices" in str(exc.value) and "600809" in str(exc.value) and "人民同泰" in str(exc.value)


def test_analytics_subjects_are_checked_too():
    payload = plan("获取日线", more=[{"task_id": "rank", "category": "analytics", "question": "同行排名",
        "depends_on": ["prices"], "analytics_parameters": {"subjects": ["山西汾酒(600829)"]}}])
    with pytest.raises(SecurityIdentityError):
        validate_plan_securities(TaskPlan.model_validate(payload))


def test_portfolio_names_and_codes_must_agree():
    ok = {"status": "ready", "clarification_questions": [], "tasks": [strategy_task(
        [{"symbol": "600519", "name": "贵州茅台", "weight": .3}, {"symbol": "600036", "weight": .2}])]}
    validate_plan_securities(TaskPlan.model_validate(ok))
    bad = {"status": "ready", "clarification_questions": [], "tasks": [strategy_task(
        [{"symbol": "600829", "name": "山西汾酒", "weight": .5}])]}
    with pytest.raises(SecurityIdentityError) as exc:
        validate_plan_securities(TaskPlan.model_validate(bad))
    assert "600809" in str(exc.value)


def test_unknown_portfolio_code_is_rejected_when_snapshot_is_available():
    bad = {"status": "ready", "clarification_questions": [], "tasks": [strategy_task([{"symbol": "699999", "weight": .5}])]}
    with pytest.raises(SecurityIdentityError):
        validate_plan_securities(TaskPlan.model_validate(bad))


def test_planner_repairs_identity_errors_with_the_correct_code():
    chain = Mock()
    chain.invoke.side_effect = [plan("获取山西汾酒(600829)近一年日线"), plan("获取山西汾酒(600809)近一年日线")]
    with patch("src.orchestration.planner._create_chain", return_value=chain):
        result = planner({"user_query": "山西汾酒近一年走势"})
    assert result["planning_status"] == "ready" and result["planning_attempts"] == 2
    assert "600809" in chain.invoke.call_args.args[0]["correction"]


def test_prompts_prefer_names_and_separate_data_range_from_window():
    from src.orchestration.planner import _SYSTEM
    from src.specialists.market_data.nodes import _SYSTEM as MARKET
    assert "优先只写名称" in _SYSTEM and "name" in _SYSTEM
    assert "不能只采集近30天" in _SYSTEM and "peer_rank" in _SYSTEM and "rank_peers" in _SYSTEM
    assert "不要自行补代码" in MARKET


def test_analytics_scope_violation_emits_a_diagnostic_event():
    from src.specialists.analytics.agent import create_analytics_agent
    from tests.test_analytics_agent import setup_data
    ds, _, ref, config = setup_data()
    other = ds.put(ds.get(ref.dataset_id))
    llm = Mock()
    llm.bind_tools.return_value = llm
    llm.invoke.return_value = AIMessage(content="", tool_calls=[{"name": "rank_peers", "id": "r1",
        "args": {"price_dataset_ids": [ref.dataset_id, other.dataset_id], "factors": ["momentum"]}}])
    with patch("src.specialists.analytics.nodes.create_llm", return_value=llm):
        events = list(create_analytics_agent().stream({"task": "同行排名", "dataset_refs": [ref.model_dump(mode="json")]},
                                                      config=config, stream_mode="custom"))
    (event,) = [e for e in events if e.get("event") == "analytics_diagnostic"]
    assert event["error_type"] == "dataset_scope_error" and event["tool"] == "rank_peers"
    assert event["unauthorized_count"] == 1 and event["arg_keys"] == ["factors", "price_dataset_ids"]
    assert other.dataset_id not in json.dumps(event)  # Counts and keys only, never raw identifiers.
