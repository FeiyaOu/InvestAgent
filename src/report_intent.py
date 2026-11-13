"""Conservative explicit report-intent checks; not a replacement for semantic planning."""
import re

_REPORT = r'(?:投研|研究|行业|投资|分析|完整)?报告'
_GENERATE = r'(?:生成|撰写|编写|出具|制作|写(?:一份|份)?|给我(?:一份)?|提供一份)'
_NEGATE = r'(?:不要|无需|不用|不需要|不必|别|暂不|不想|不希望)'


class ReportIntentError(ValueError):
    pass


def explicit_report_intent(query: str) -> str:
    decisions = []
    for clause in re.split(r'[，,。！？!?；;\n]', query):
        matches = []
        for match in re.finditer(_GENERATE + r'.{0,120}?' + _REPORT, clause):
            prefix = clause[:match.start()]
            if re.search(r'(?:如何|怎么|怎样).{0,16}$', prefix):
                continue  # Explaining how to generate a report is not a generation request.
            negative = re.search(_NEGATE + r'(?:再|帮我|为我|直接|自动|给我){0,2}$', prefix)
            matches.append((match.start(), 'forbidden' if negative else 'requested'))
        for match in re.finditer(_NEGATE + r'(?:生成|撰写|编写|提供)?(?:一份|完整|投研|研究|行业|投资|分析){0,3}报告', clause):
            matches.append((match.start(), 'forbidden'))
        if matches:
            decisions.append(sorted(matches)[-1][1])
    return decisions[-1] if decisions else 'unspecified'


def validate_report_intent(query, plan):
    if plan.status != 'ready':
        return
    intent = explicit_report_intent(query)
    has_report = any(task.category == 'report' for task in plan.tasks)
    if intent == 'requested' and not has_report:
        raise ReportIntentError('用户明确要求生成投研报告，计划必须包含category=report的任务。报告子图内部完成研究流程，不得用market_data/analytics/investment_strategy替代报告；用户另问的独立问题可保留。')
    if intent == 'forbidden' and has_report:
        raise ReportIntentError('用户明确不需要报告，删除category=report任务，按原问题规划查询或分析。')
