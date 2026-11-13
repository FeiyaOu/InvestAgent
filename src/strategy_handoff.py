"""Strategy boundary: canonical references in, canonical numerical artifacts out."""
import json
from copy import deepcopy
from src.datasets import DatasetStore
from src.analytics_artifacts import AnalysisStore
from src.market_data_state import MarketEvidence
from src.strategy_state import StrategyInput, StrategyResult, StrategyAnswer
from src.strategy_artifacts import StrategyStore


class StrategyReferenceError(ValueError):
    def __init__(self, field, hint):
        super().__init__(hint)
        self.diagnostics = [{'stage':'strategy','error_type':'reference_scope','field':field,
            'expected':'authorized reference in the correct field', 'received_type':'list',
            'received_preview':'[omitted]', 'hint':hint}]


def reference_manifest(req, artifacts):
    """Keep source citations separate from executed Strategy artifact identifiers."""
    return {
        'dataset_ids':[r['dataset_id'] for r in req.dataset_refs],
        'analysis_ids':[r['analysis_id'] for r in req.analysis_refs],
        'evidence_ids':[e['tool_call_id'] for e in req.evidence if usable_evidence(e)],
        'strategy_artifact_ids':[r['artifact_id'] for r in artifacts],
        'user_input':'仅用于用户持仓、限制和假设，不能证明市场事实',
        'rules':'上游analysis_ids/dataset_ids/evidence_ids用于opportunities/risks中的evidence_ids。'
                '不要输出artifact_ids；策略工具产物由代码选取。纯解释没有strategy_artifact_ids是正常情况。',
    }


def usable_evidence(evidence):
    if evidence.get('status') != 'returned':
        return False
    try:
        payload = json.loads(evidence.get('content', ''))
    except (ValueError, TypeError):
        return bool(evidence.get('content', '').strip())
    return not (isinstance(payload, dict) and payload.get('status') in {'unavailable', 'error', 'failed'})


def canonical_request(raw, config):
    req = StrategyInput.model_validate_json(json.dumps(raw, allow_nan=False))
    runtime = config.get('configurable') or {}
    ids = [r['dataset_id'] for r in req.dataset_refs]
    if len(ids) != len(set(ids)):
        raise ValueError('重复数据引用')
    if ids:
        ds = runtime.get('dataset_store')
        if not isinstance(ds, DatasetStore): raise ValueError('数据存储缺失')
        req.dataset_refs = [ds.get_ref(i).model_dump(mode='json') for i in ids]
    analysis_ids = [r['analysis_id'] for r in req.analysis_refs]
    if len(analysis_ids) != len(set(analysis_ids)):
        raise ValueError('重复分析引用')
    if analysis_ids:
        store = runtime.get('analysis_store')
        if not isinstance(store, AnalysisStore): raise ValueError('分析存储缺失')
        refs = [store.get_ref(i) for i in analysis_ids]
        if any(not {r['dataset_id'] for r in a['dataset_refs']} <= set(ids) for a in refs):
            raise ValueError('分析来源超出授权范围')
        req.analysis_refs = refs
    req.evidence = [MarketEvidence.model_validate(e).model_dump() for e in req.evidence]
    if not req.subjects:
        req.subjects = list(dict.fromkeys(r['symbol'] for r in req.dataset_refs))
    if len({e['tool_call_id'] for e in req.evidence}) != len(req.evidence):
        raise ValueError('证据ID重复')
    return req


def strategy_inputs(task, results, config):
    data, analyses, evidence = {}, {}, []
    for ident in task['depends_on']:
        record = results[ident]
        payload = record.get('result') or {}
        if record['category'] not in {'market_data','analytics'}:
            continue  # Report internals and arbitrary child state never enter Strategy.
        for ref in payload.get('dataset_refs',[]): data[ref['dataset_id']] = ref
        for ref in payload.get('analysis_refs',[]): analyses[ref['analysis_id']] = ref
        for e in payload.get('evidence',[]):
            item = deepcopy(e);item['tool_call_id'] = ident + ':' + item['tool_call_id'];evidence.append(item)
    params = task.get('strategy_parameters') or {}
    raw = {**params, 'task':task['question'], 'dataset_refs':list(data.values()),
           'analysis_refs':list(analyses.values()), 'evidence':evidence}
    if not raw.get('subjects'):
        raw['subjects'] = list(dict.fromkeys(ref['symbol'] for ref in data.values()))
    return canonical_request(raw, config).model_dump(mode='json')


def build_result(answer, req, artifacts, scope_id, config):
    store = (config.get('configurable') or {}).get('strategy_store')
    if not isinstance(store, StrategyStore): raise ValueError('策略存储缺失')
    if len(answer.artifact_ids) != len(set(answer.artifact_ids)) or not set(answer.artifact_ids) <= set(artifacts):
        raise StrategyReferenceError('artifact_ids', 'artifact_ids只允许本次执行的strategy_产物，不能填写上游analysis_引用；请删除artifact_ids字段。上游分析ID放入结论的evidence_ids。')
    for ident in artifacts:
        store.get(ident, scope_id)
    refs = store.for_scope(scope_id)
    if any(r['inputs'] != req.model_dump(mode='json') for r in refs):
        raise ValueError('策略产物输入不匹配')
    allowed = {'user_input'} | {r['dataset_id'] for r in req.dataset_refs} | {r['analysis_id'] for r in req.analysis_refs} | {r['artifact_id'] for r in refs}
    allowed |= {e['tool_call_id'] for e in req.evidence if usable_evidence(e)}
    for group in ('opportunities','risks'):
        for index, claim in enumerate(getattr(answer, group)):
            if not set(claim.evidence_ids) <= allowed:
                raise StrategyReferenceError(f'{group}.{index}.evidence_ids', '结论evidence_ids必须逐字复制当前引用清单中的ID，不要填写股票代码、工具名或自造ID。')
    checks = [row for ref in refs for row in ref['constraint_checks']]
    scenarios = [row for ref in refs for row in ref['scenario_results']]
    missing = list(answer.missing_information)
    requests = [r.model_dump() for r in answer.missing_data_requests]
    if req.scenario_assumptions and req.portfolio is None:
        missing.append('压力测试缺少持仓、现金权重、币种和持仓日期')
        requests.append({'kind':'portfolio','subjects':req.subjects,'time_range':req.time_range,'reason':missing[-1]})
    if any(row['status']=='unknown' for row in checks): missing.append('部分风险约束无法检查，详见检查结果')
    if not (req.dataset_refs or req.analysis_refs or any(usable_evidence(e) for e in req.evidence) or req.portfolio or refs):
        missing.append('未提供可解析证据或持仓，不形成市场事实判断')
        requests.append({'kind':'evidence','subjects':req.subjects,'time_range':req.time_range,'reason':missing[-1]})
    limits = ['历史风险不保证未来表现；情景是假设，不代表发生概率。', 'V1不支持估值预测、组合优化、HRP或Black-Litterman。']
    limits += [v for r in refs for v in r['limitations']]
    mock = any(r.get('data_mode') == 'mock' for r in req.dataset_refs + req.evidence)
    if mock: limits.append('包含模拟数据，不作为真实市场事实。')
    result = StrategyResult(summary=answer.summary, opportunities=answer.opportunities, risks=answer.risks,
        artifact_refs=refs, scenario_results=scenarios, constraint_checks=checks,
        dataset_refs=req.dataset_refs, analysis_refs=req.analysis_refs, evidence=req.evidence,
        assumptions={'portfolio':req.portfolio.model_dump(mode='json') if req.portfolio else None,
            'risk_constraints':req.risk_constraints.model_dump(exclude_none=True),
            'scenario_assumptions':[s.model_dump(mode='json') for s in req.scenario_assumptions]},
        limitations=list(dict.fromkeys(limits)), missing_information=list(dict.fromkeys(missing)), missing_data_requests=requests)
    return ('partial' if missing or requests or mock else 'completed'), result.model_dump(mode='json')


def strategy_result(raw, inputs, config):
    if not isinstance(raw,dict) or raw.get('status') not in {'completed','partial','failed'}:
        raise ValueError('策略状态无效')
    if raw['status']=='failed':
        # Only application-owned error codes/messages cross the specialist boundary.
        messages = {
            'invalid_strategy_input':'策略输入、数据引用或方法文件无效。',
            'model_error':'策略模型调用失败。',
            'invalid_output':'策略解释的格式或引用校验失败。',
            'duplicate_tool_call':'相同策略产物已计算，禁止重复调用。',
            'tool_budget_exceeded':'策略工具预算已达到上限。',
            'tool_scope_error':'策略工具或参数超出允许范围。',
            'tool_error':'策略工具产物无法验证。',
        }
        code = (raw.get('error') or {}).get('type')
        if code in messages:
            return 'failed',None,{'type':code,'message':messages[code]}
        return 'failed',None,{'type':'strategy_failed','message':'策略分析未完成，请查看执行记录。'}
    if raw.get('error') is not None: raise ValueError('可用策略不得带执行错误')
    parsed = StrategyResult.model_validate(raw['result'])
    req = canonical_request(inputs, config)
    answer = StrategyAnswer(summary=parsed.summary, opportunities=parsed.opportunities, risks=parsed.risks,
        artifact_ids=[r['artifact_id'] for r in parsed.artifact_refs], missing_information=parsed.missing_information,
        missing_data_requests=parsed.missing_data_requests)
    scope = raw['scope_id']
    expected = (config.get('configurable') or {}).get('strategy_expected_scope')
    if expected is not None and scope != expected: raise ValueError('策略执行scope不匹配')
    status, result = build_result(answer,req,answer.artifact_ids,scope,config)
    return ('partial' if raw['status']=='partial' else status),result,None
