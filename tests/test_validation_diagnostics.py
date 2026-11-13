import pytest
from pydantic import ValidationError
from src.planner_schemas import TaskPlan
from src.validation_diagnostics import validation_diagnostics


def test_diagnostics_identify_type_without_exposing_values():
    raw = {'status': 'ready', 'tasks': [{'task_id': 'a', 'category': 'analytics', 'question': 'test',
        'depends_on': [], 'analytics_parameters': {'assumptions': 'secret-token'}}], 'clarification_questions': []}
    with pytest.raises(ValidationError) as caught:
        TaskPlan.model_validate(raw)
    rows = validation_diagnostics(caught.value, stage='planner', attempt=2, raw=raw)
    item = rows[0]
    assert item['field'] == 'tasks.0.analytics_parameters.assumptions'
    assert item['received_type'] == 'str'
    assert item['task_id'] == 'a'
    assert item['expected'] == 'JSON object'
    assert 'secret-token' not in str(rows)
    assert item['hint']


@pytest.mark.parametrize('value,kind', [('private', 'str'), (['private'], 'list'), (42, 'int')])
def test_assumptions_invalid_types_are_distinguished(value, kind):
    from src.planner_schemas import AnalyticsTaskParameters
    with pytest.raises(ValidationError) as caught:
        AnalyticsTaskParameters.model_validate({'assumptions': value})
    row = validation_diagnostics(caught.value, stage='planner', attempt=1)[0]
    assert row['received_type'] == kind
    assert row['expected'] == 'JSON object'
    assert row['received_preview'] == '[omitted]'
