"""Safe field-level validation metadata, independent of graph/UI implementation."""
from pydantic import ValidationError

_EXPECTED = {'model_type': 'JSON object', 'dict_type': 'JSON object',
    'list_type': 'JSON array', 'string_type': 'string', 'int_type': 'integer',
    'literal_error': 'allowed enum value', 'missing': 'required field',
    'extra_forbidden': 'no extra field'}


def validation_diagnostics(exc: ValidationError, *, stage: str, attempt: int, raw=None) -> list[dict]:
    rows = []
    for error in exc.errors(include_url=False):
        loc = error['loc']
        value = error.get('input')
        kind = error['type']
        task_id = None
        if isinstance(raw, dict) and len(loc) > 1 and loc[0] == 'tasks' and isinstance(loc[1], int):
            tasks = raw.get('tasks')
            if isinstance(tasks, list) and loc[1] < len(tasks) and isinstance(tasks[loc[1]], dict):
                ident = tasks[loc[1]].get('task_id')
                # Only machine identifiers are eligible for display.
                if isinstance(ident, str) and ident.isascii() and ident.replace('_', '').replace('-', '').isalnum():
                    task_id = ident[:80]
        expected = _EXPECTED.get(kind, 'value satisfying schema/business constraints')
        hint = f'请按schema修正该字段：{expected}。'
        if kind == 'value_error':
            # Match known constraints, never forward arbitrary validator exception text.
            message = error.get('msg', '')
            for marker, guidance in (
                ('未知依赖', 'unknown/missing dependency：depends_on只能引用本计划中存在的task_id。'),
                ('有向环', '任务依赖不得形成环。'), ('不得重复', '删除重复的任务ID或依赖。'),
                ('依赖自身', '任务不得依赖自身。'),
                ('analytics_parameters', 'analytics_parameters仅用于analytics任务。'),
                ('ready', 'ready计划须含任务且不得同时请求澄清。'),
                ('澄清计划', '澄清计划须无任务并包含非空澄清问题。')):
                if marker in message:
                    hint = guidance
                    break
        rows.append({'stage': stage, 'attempt': attempt, 'error_type': kind,
            'field': '.'.join(map(str, loc)) or '$', 'task_id': task_id,
            'expected': expected, 'received_type': 'missing' if kind == 'missing' else type(value).__name__,
            'received_preview': '[omitted]',
            'hint': 'assumptions请传入JSON对象{}，或省略该字段。' if loc and loc[-1] == 'assumptions'
                    else hint})
    return rows
