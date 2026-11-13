"""Native provider failures must remain outside the application process."""
import json
import subprocess
from unittest.mock import patch

import pytest

from src.tools import _call_sina


def test_native_crash_becomes_python_error_without_exposing_stderr():
    completed = subprocess.CompletedProcess([], -5, stdout='', stderr='private crash dump')
    with patch('subprocess.run', return_value=completed) as run:
        with pytest.raises(RuntimeError, match='native provider exited'):
            _call_sina('stock_zh_index_daily', symbol='sh000300')
    assert run.call_args.kwargs['timeout'] == 60
    assert 'fork' not in run.call_args.args[0]


def test_subprocess_table_is_decoded_and_arguments_are_data():
    completed = subprocess.CompletedProcess([], 0, stdout='[{"date":"2025-01-02","close":100}]')
    with patch('subprocess.run', return_value=completed) as run:
        frame = _call_sina('stock_zh_a_daily', symbol='sh600519', adjust='qfq')
    assert frame.iloc[0]['close'] == 100
    assert json.loads(run.call_args.kwargs['input'])['kwargs']['adjust'] == 'qfq'


def test_unknown_provider_function_is_rejected_without_starting_process():
    with patch('subprocess.run') as run:
        with pytest.raises(ValueError):
            _call_sina('eval', symbol='x')
        run.assert_not_called()


def test_worker_timeout_is_bounded():
    with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('worker', 60)):
        with pytest.raises(subprocess.TimeoutExpired):
            _call_sina('stock_zh_index_daily', symbol='sh000300')
