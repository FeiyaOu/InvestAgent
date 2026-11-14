from unittest.mock import Mock, patch

import pytest

from src.orchestration.parent_graph import create_parent_graph
from src.orchestration.planner_schemas import TaskPlan
from tests.test_strategy_agent import answer
from tests.test_strategy_tools import context


def strategy_task():
    _,cfg=context()
    inputs=cfg['configurable']['strategy_input']
    return {'task_id':'s','category':'investment_strategy','question':'检查组合仓位并做跌10%压力测试','depends_on':[],
        'strategy_parameters':{k:v for k,v in inputs.items() if k not in {'task','dataset_refs','analysis_refs','evidence'}}}


def test_plan_parameters_and_real_parent_dispatch_to_strategy_with_stores():
    task=strategy_task()
    payload={'status':'ready','tasks':[task],'clarification_questions':[]}
    assert TaskPlan.model_validate(payload).to_state()['tasks'][0]['strategy_parameters']['portfolio']['as_of_date']=='2026-11-13'
    llm=Mock()
    llm.bind_tools.return_value=llm
    llm.invoke.side_effect=answer
    with patch('src.orchestration.planner._create_chain') as planner, patch('src.specialists.strategy.nodes.create_llm',return_value=llm), patch('src.orchestration.composer._create_chain',side_effect=RuntimeError()):
        planner.return_value.invoke.return_value=payload
        result=create_parent_graph().invoke({'user_query':'检查组合'})
    record=result['task_results']['s']
    assert record['status']=='completed'
    assert record['result']['scenario_results'][0]['portfolio_return']==pytest.approx(-.08)
    assert 'portfolio_return' in result['final_response']
    assert 'strategy_store' not in result and 'messages' not in result


def test_parameters_cannot_be_attached_to_other_category():
    task=strategy_task()
    task['category']='market_data'
    with pytest.raises(ValueError):
        TaskPlan.model_validate({'status':'ready','tasks':[task],'clarification_questions':[]})


def test_portfolio_risk_chain_exports_series_by_event_only():
    import json
    from datetime import date, datetime, timedelta, timezone

    import numpy as np
    from langchain_core.messages import AIMessage

    from src.core.datasets import PriceDataset
    from src.specialists.analytics.tools import build_return_matrix

    def market(inputs, config):
        ds = config["configurable"]["dataset_store"]
        refs = []
        for seed, symbol in enumerate(("600519", "000858")):
            closes = 100 * np.cumprod(1 + np.random.default_rng(seed).normal(0, .015, 300))
            refs.append(ds.put(PriceDataset(kind="price_history", symbol=symbol, market="SSE", currency="CNY",
                provider="test", retrieved_at=datetime.now(timezone.utc), data_mode="real", asset_type="stock",
                frequency="daily", adjustment="qfq", price_unit="CNY/share", volume_unit="not_available",
                rows=[{"date": date(2024, 1, 1) + timedelta(days=i), "close": float(v)} for i, v in enumerate(closes)])))
        return {"status": "completed", "error": None, "result": {"answer": "已采集", "evidence_ids": [],
                "evidence": [], "missing_information": [], "dataset_refs": [r.model_dump(mode="json") for r in refs]}}

    def analytics(inputs, config):
        ids = [ref["dataset_id"] for ref in inputs["dataset_refs"]]
        matrix = json.loads(build_return_matrix.invoke({"dataset_ids": ids}, config=config))["analysis_ref"]
        return {"status": "completed", "error": None, "result": {"summary": "收益矩阵", "findings": [],
                "analysis_refs": [matrix], "chart_refs": matrix["chart_refs"], "dataset_refs": inputs["dataset_refs"],
                "assumptions": {}, "limitations": [], "missing_information": [], "missing_data_requests": []}}

    def respond(messages):
        refs = json.loads(messages[-1].content.split("\n", 1)[1])["available_references"]
        return AIMessage(content=json.dumps({"summary": "组合风险已评估", "risks": [
            {"text": "存在尾部损失", "evidence_ids": refs["strategy_artifact_ids"][:1]}]}, ensure_ascii=False))

    payload = {"status": "ready", "clarification_questions": [], "tasks": [
        {"task_id": "m", "category": "market_data", "question": "采集两只股票2年日线", "depends_on": []},
        {"task_id": "a", "category": "analytics", "question": "构建收益矩阵", "depends_on": ["m"]},
        {"task_id": "s", "category": "investment_strategy", "question": "评估组合风险", "depends_on": ["m", "a"],
         "strategy_parameters": {"portfolio": {"as_of_date": "2026-11-13", "currency": "CNY", "cash_weight": .2,
             "positions": [{"symbol": "600519", "weight": .5}, {"symbol": "000858", "weight": .3}]}}}]}
    md, an, llm = Mock(), Mock(), Mock()
    md.invoke.side_effect, an.invoke.side_effect, llm.invoke.side_effect = market, analytics, respond
    with patch("src.orchestration.planner._create_chain") as planner, \
            patch("src.specialists.strategy.nodes.create_llm", return_value=llm), \
            patch("src.orchestration.composer._create_chain", side_effect=RuntimeError()):
        planner.return_value.invoke.return_value = payload
        graph = create_parent_graph(market_data_graph=md, analytics_graph=an)
        events = list(graph.stream({"user_query": "评估组合风险"}, stream_mode=["updates", "custom"], subgraphs=True))
    custom = [p for _, mode, p in events if mode == "custom"]
    matrix_event = next(p for p in custom if p.get("event") == "analysis_artifacts")
    assert all(snap["series"] == {} for snap in matrix_event["artifacts"].values())
    strategy_event = next(p for p in custom if p.get("event") == "strategy_artifacts")
    assert strategy_event["task_id"] == "s"
    (series,) = strategy_event["series"].values()
    assert series["portfolio_nav"]
    final = [u for ns, mode, u in events if mode == "updates" and not ns and "supervisor" in u][-1]
    record = final["supervisor"]["task_results"]["s"]
    assert record["status"] == "completed" and record["result"]["risk_results"]
    assert '{"date"' not in json.dumps(final)  # Only series names (series_keys), never data points.
