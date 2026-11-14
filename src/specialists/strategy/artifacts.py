"""Request-local deterministic Strategy artifacts, scoped to one specialist execution."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from threading import RLock
from uuid import uuid4


class StrategyStore:
    def __init__(self):
        self._items = {}
        self._lock = RLock()

    def put(self, *, scope_id, tool_name, inputs, constraint_checks=None, scenario_results=None, limitations=None):
        item = {'artifact_id':'strategy_' + uuid4().hex, 'scope_id':scope_id,
                'tool_name':tool_name, 'created_at':datetime.now(timezone.utc).isoformat(),
                'inputs':inputs, 'constraint_checks':constraint_checks or [],
                'scenario_results':scenario_results or [], 'limitations':limitations or []}
        json.dumps(item, allow_nan=False)  # Reject nonfinite nested results before registration.
        with self._lock:
            self._items[item['artifact_id']] = deepcopy(item)
        return deepcopy(item)

    def get(self, ident, scope_id):
        with self._lock:
            item = self._items[ident]
            if item['scope_id'] != scope_id:
                raise ValueError('策略产物超出任务范围')
            return deepcopy(item)

    def for_scope(self, scope_id):
        """All executed results, so a child cannot hide a violated constraint by omission."""
        with self._lock:
            return [deepcopy(item) for item in self._items.values() if item['scope_id'] == scope_id]

    def clear(self):
        with self._lock:
            self._items.clear()
