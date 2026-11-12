"""Structured history acquisition; providers mocked and data request-scoped."""
import json
import sys
from unittest.mock import Mock, patch

import pandas as pd

from src.datasets import DatasetStore
from src.tools import get_price_history


def fetch(store, **updates):
    args = {"query": "茅台", "start_date": "2025-01-02", "end_date": "2025-01-03",
            "asset_type": "stock", "adjustment": "qfq", **updates}
    return json.loads(get_price_history.invoke(args, config={"configurable": {"dataset_store": store}}))


def frame():
    return pd.DataFrame({"日期": ["2025-01-02", "2025-01-03"], "收盘": [100., 110.],
        "开盘": [99., 105.], "最高": [101., 111.], "最低": [98., 104.], "成交量": [2., 3.]})


def test_history_registers_dataset_and_returns_reference_not_rows(monkeypatch):
    monkeypatch.setenv("USE_REAL_DATA", "true")
    provider = Mock(); provider.stock_zh_a_hist.return_value = frame()
    store = DatasetStore()
    with patch.dict(sys.modules, {"akshare": provider}):
        result = fetch(store)
    assert result["status"] == "available"
    ref = result["dataset_ref"]
    assert "rows" not in ref
    dataset = store.get(ref["dataset_id"])
    assert dataset.symbol == "600519"
    assert dataset.rows[0].volume == 200.
    assert dataset.adjustment == "qfq"
    assert dataset.data_mode == "real"


def test_index_history_has_points_and_no_invented_volume(monkeypatch):
    monkeypatch.setenv("USE_REAL_DATA", "true")
    provider = Mock(); provider.index_zh_a_hist.return_value = frame()
    store = DatasetStore()
    with patch.dict(sys.modules, {"akshare": provider}):
        result = fetch(store, query="000300", asset_type="index", adjustment="none")
    dataset = store.get(result["dataset_ref"]["dataset_id"])
    assert dataset.price_unit == "points"
    assert dataset.volume_unit == "not_available"
    assert dataset.rows[0].volume is None


def test_errors_do_not_register_data_or_fabricate_success(monkeypatch):
    monkeypatch.setenv("USE_REAL_DATA", "true")
    provider = Mock(); provider.stock_zh_a_hist.side_effect = RuntimeError("secret")
    with patch.dict(sys.modules, {"akshare": provider}):
        for updates in ({}, {"start_date": "bad"}, {"query": "腾讯"},
                        {"start_date": "2025-02-01"}, {"asset_type": "index", "adjustment": "qfq"}):
            result = fetch(DatasetStore(), **updates)
            assert result["status"] == "unavailable"
            assert "dataset_ref" not in result
            assert "secret" not in str(result)


def test_invalid_provider_rows_fail_validation(monkeypatch):
    monkeypatch.setenv("USE_REAL_DATA", "true")
    provider = Mock(); provider.stock_zh_a_hist.return_value = frame().iloc[::-1]
    with patch.dict(sys.modules, {"akshare": provider}):
        result = fetch(DatasetStore())
    assert result["status"] == "unavailable"


def test_mock_history_is_explicit_and_does_not_import_provider(monkeypatch):
    monkeypatch.setenv("USE_REAL_DATA", "false")
    store = DatasetStore()
    with patch.dict(sys.modules, {"akshare": None}):
        result = fetch(store)
    assert result["dataset_ref"]["data_mode"] == "mock"
    assert store.get(result["dataset_ref"]["dataset_id"]).provider == "synthetic_demo"


def test_missing_store_is_explicit_failure():
    result = json.loads(get_price_history.invoke({"query": "600519", "start_date": "2025-01-02",
                                                "end_date": "2025-01-03"}))
    assert result["status"] == "unavailable"


def test_no_data_does_not_fall_back_to_fake_rows(monkeypatch):
    monkeypatch.setenv("USE_REAL_DATA", "true")
    provider = Mock(); provider.stock_zh_a_hist.return_value = pd.DataFrame()
    with patch.dict(sys.modules, {"akshare": provider}):
        assert fetch(DatasetStore())["error"]["type"] == "no_data"


def test_runtime_config_not_in_model_tool_schema():
    properties = get_price_history.tool_call_schema.model_json_schema()["properties"]
    assert "config" not in properties
    assert "dataset_store" not in properties
