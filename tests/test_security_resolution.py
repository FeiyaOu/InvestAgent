"""P0: security name/code cross-check against the exchange directory; mismatches fail loudly."""
import json
import sys
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from src.core.datasets import DatasetStore
from src.data import tools
from src.data.tools import get_price_history, get_price_history_batch, get_valuation_snapshot

DIRECTORY = {"generated_at": "2026-11-14", "securities": {
    "600519": "贵州茅台", "600809": "山西汾酒", "600829": "人民同泰", "000568": "泸州老窖", "000858": "五粮液"}}


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("USE_REAL_DATA", "true")
    monkeypatch.setattr("src.data.tools._DIRECTORY_CACHE", DIRECTORY)
    mock = Mock()
    mock.stock_zh_a_hist.return_value = pd.DataFrame({"日期": ["2025-01-02", "2025-01-03"], "收盘": [100., 101.]})
    mock.stock_value_em.return_value = pd.DataFrame({"数据日期": ["2025-01-03"], "PE(TTM)": [20.], "市净率": [2.], "市销率": [5.]})
    monkeypatch.setattr("src.data.tools._call_sina", lambda function, **kw: getattr(mock, function)(**kw))
    with patch.dict(sys.modules, {"akshare": mock}):
        yield mock


@pytest.mark.parametrize("query,code,name", [
    ("山西汾酒(600809)", "600809", "山西汾酒"), ("山西汾酒（600809）", "600809", "山西汾酒"),
    ("茅台(600519)", "600519", "贵州茅台"), ("泸州老窖", "000568", "泸州老窖"), ("600829", "600829", "人民同泰"),
    ("贵州茅台(SH600519)", "600519", "贵州茅台"),
])
def test_consistent_queries_resolve_to_official_names(provider, query, code, name):
    assert tools.resolve_security(query) == (code, name, None)


def test_mismatch_is_rejected_and_points_to_the_right_code(provider):
    code, name, error = tools.resolve_security("山西汾酒(600829)")
    assert code is None and name is None
    assert "600829" in error and "人民同泰" in error and "600809" in error


def test_unknown_name_is_not_guessed(provider):
    assert tools.resolve_security("不存在的公司")[0] is None


def test_missing_snapshot_falls_back_to_static_map_as_unverified(provider, monkeypatch):
    monkeypatch.setattr("src.data.tools._DIRECTORY_CACHE", {"generated_at": None, "securities": {}})
    assert tools.resolve_security("贵州茅台(600519)") == ("600519", None, None)  # Static map agrees; name unverified.
    assert tools.resolve_security("茅台(000858)")[2]  # Static map still catches a contradiction.


def test_resolution_never_calls_the_network(provider):
    tools.resolve_security("山西汾酒(600809)")
    provider.stock_info_a_code_name.assert_not_called()
    provider.stock_individual_info_em.assert_not_called()


def test_loader_reads_snapshot_once_and_tolerates_corrupt_files(tmp_path, monkeypatch):
    good = tmp_path / "dir.json"
    good.write_text(json.dumps(DIRECTORY, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("src.data.tools._DIRECTORY_PATH", good)
    assert tools._security_directory()["600809"] == "山西汾酒"
    good.write_text("{}", encoding="utf-8")
    assert tools._security_directory()["600809"] == "山西汾酒"  # Cached for the process.
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    monkeypatch.setattr("src.data.tools._DIRECTORY_PATH", bad)
    monkeypatch.setattr("src.data.tools._DIRECTORY_CACHE", None)
    assert tools._security_directory() == {}
    assert "不可用" in tools._unverified_name_note()


def test_committed_snapshot_covers_both_exchanges():
    snapshot = json.loads(tools._DIRECTORY_PATH.read_text(encoding="utf-8"))
    securities = snapshot["securities"]
    assert len(securities) > 4000 and snapshot["generated_at"]
    assert securities["600519"] == "贵州茅台" and securities["600809"] == "山西汾酒"
    assert securities["000858"] == "五粮液" and securities["000568"] == "泸州老窖"


def store_config():
    store = DatasetStore()
    return store, {"configurable": {"dataset_store": store}}


def test_history_rejects_mismatch_without_registering_and_records_name(provider):
    store, config = store_config()
    bad = json.loads(get_price_history.invoke({"query": "山西汾酒(600829)", "start_date": "2025-01-02",
                                               "end_date": "2025-01-03"}, config=config))
    assert bad["status"] == "unavailable" and bad["error"]["type"] == "symbol_mismatch"
    assert "600809" in bad["error"]["message"] and not store._datasets
    good = json.loads(get_price_history.invoke({"query": "山西汾酒(600809)", "start_date": "2025-01-02",
                                                "end_date": "2025-01-03"}, config=config))
    assert good["dataset_ref"]["security_name"] == "山西汾酒"
    assert store.get(good["dataset_ref"]["dataset_id"]).security_name == "山西汾酒"


def test_valuation_and_batch_apply_the_same_check(provider):
    store, config = store_config()
    bad = json.loads(get_valuation_snapshot.invoke({"query": "山西汾酒(600829)"}, config=config))
    assert bad["error"]["type"] == "symbol_mismatch"
    batch = json.loads(get_price_history_batch.invoke({"queries": ["贵州茅台(600519)", "山西汾酒(600829)"],
        "start_date": "2025-01-02", "end_date": "2025-01-03"}, config=config))
    assert batch["status"] == "partial"
    assert batch["items"][0]["dataset_ref"]["security_name"] == "贵州茅台"
    assert "600809" in batch["items"][1]["error"]["message"]


def test_unverified_name_is_flagged_in_limitations(provider, monkeypatch):
    monkeypatch.setattr("src.data.tools._DIRECTORY_CACHE", {"generated_at": "2026-11-14", "securities": {}})
    _, config = store_config()
    result = json.loads(get_price_history.invoke({"query": "000568", "start_date": "2025-01-02",
                                                  "end_date": "2025-01-03"}, config=config))
    assert result["dataset_ref"]["security_name"] is None
    assert any("证券简称" in item and "2026-11-14" in item for item in result["limitations"])


def test_mock_mode_never_imports_the_directory_provider(monkeypatch):
    monkeypatch.setenv("USE_REAL_DATA", "false")
    monkeypatch.setattr("src.data.tools._DIRECTORY_CACHE", DIRECTORY)
    with patch.dict(sys.modules, {"akshare": None}):
        assert tools.resolve_security("贵州茅台(600519)") == ("600519", "贵州茅台", None)
