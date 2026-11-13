"""Deterministic V1 risk checks and static price shocks; no market API or LLM."""
import json
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError
from src.strategy_state import StrategyInput
from src.strategy_artifacts import StrategyStore


def _context(config):
    runtime = config.get('configurable') or {}
    store = runtime.get('strategy_store')
    if not isinstance(store, StrategyStore) or not runtime.get('strategy_scope'):
        raise ValueError('请求内策略存储或任务范围缺失')
    request = StrategyInput.model_validate_json(json.dumps(runtime['strategy_input'], allow_nan=False))
    return request, store, runtime['strategy_scope']


def _unavailable(exc):
    return json.dumps({'status':'unavailable', 'error':{'type':'strategy_input_unavailable',
        'message':'策略工具输入不符合契约。' if isinstance(exc, ValidationError) else str(exc)}}, ensure_ascii=False)


@tool
def evaluate_risk_constraints(config: RunnableConfig) -> str:
    """Check only supplied risk limits using canonical holdings and upstream analysis.

    No thresholds are inferred. Historical individual risk is not portfolio risk.
    Missing data returns unknown, never a fabricated pass or suitability judgment.
    """
    try:
        req, store, scope = _context(config)
        checks = []
        for name, threshold in req.risk_constraints.model_dump(exclude_none=True).items():
            if name == 'max_single_asset_weight':
                positions = req.portfolio.positions if req.portfolio else []
                if not positions and req.portfolio is not None:
                    checks.append({'constraint':name, 'symbol':None, 'threshold':threshold,
                        'observed':0., 'unit':'fraction', 'status':'satisfied', 'reason':'全部为现金，无单股暴露'})
                elif not positions:
                    checks.append({'constraint':name, 'symbol':None, 'threshold':threshold,
                        'observed':None, 'status':'unknown', 'reason':'缺少非现金持仓'})
                for p in positions:
                    checks.append({'constraint':name, 'symbol':p.symbol, 'threshold':threshold,
                        'observed':p.weight, 'unit':'fraction', 'status':'violated' if p.weight > threshold else 'satisfied'})
            elif name in {'max_asset_annualized_volatility', 'max_asset_drawdown'}:
                symbols = [p.symbol for p in req.portfolio.positions] if req.portfolio else req.subjects
                metric = 'annualized_volatility' if name.endswith('volatility') else 'max_drawdown'
                for symbol in symbols or [None]:
                    candidates = [ref for ref in req.analysis_refs
                        if ref.get('tool_name') == 'analyze_price_performance'
                        and len(ref.get('dataset_refs', [])) == 1
                        and ref['dataset_refs'][0].get('symbol') == symbol
                        and ref.get('metric_units', {}).get(metric) == 'fraction'
                        and ref.get('metrics', {}).get(metric) is not None
                        and (not req.portfolio or (ref['end_date'] <= req.portfolio.as_of_date.isoformat()
                             and ref['dataset_refs'][0].get('currency') == req.portfolio.currency))]
                    ref = max(candidates, key=lambda r:r['end_date']) if candidates else None
                    value = abs(ref['metrics'][metric]) if ref else None
                    checks.append({'constraint':name, 'symbol':symbol, 'threshold':threshold,
                        'observed':value, 'unit':'fraction',
                        'status':'unknown' if value is None else 'violated' if value > threshold else 'satisfied',
                        'analysis_id':ref['analysis_id'] if ref else None,
                        'start_date':ref['start_date'] if ref else None, 'end_date':ref['end_date'] if ref else None,
                        'reason':'仅检查历史样本，非未来保证' if ref else '缺少兼容日期/币种/口径的单股表现产物'})
            else:
                checks.append({'constraint':name, 'threshold':threshold, 'observed':None, 'status':'unknown',
                               'reason':'V1没有组合风险估计产物，不以单股风险代替组合风险'})
        artifact = store.put(scope_id=scope, tool_name='evaluate_risk_constraints',
            inputs=req.model_dump(mode='json'), constraint_checks=checks,
            limitations=['只检查用户显式限制；历史风险不保证未来风险。'] if checks else ['未提供用户约束，不推断阈值或适合性。'])
        return json.dumps({'status':'available','artifact':artifact}, ensure_ascii=False, allow_nan=False)
    except (ValueError, KeyError, TypeError) as exc:
        return _unavailable(exc)


@tool
def stress_test_portfolio(scenario_id: str, config: RunnableConfig) -> str:
    """Apply an explicitly supplied static price-shock scenario to canonical long-only CNY weights.

    Every holding must have an explicit shock. Cash return is zero. No forecasts,
    probabilities, FX, correlation/path simulation, fees or rebalancing are inferred.
    """
    try:
        req, store, scope = _context(config)
        if req.portfolio is None:
            raise ValueError('组合压力测试需要持仓、现金权重、币种和持仓日期')
        scenario = next((s for s in req.scenario_assumptions if s.scenario_id == scenario_id), None)
        if scenario is None:
            raise ValueError('情景ID不存在，不猜测冲击值')
        symbols = {p.symbol for p in req.portfolio.positions}
        if set(scenario.price_shocks) != symbols:
            raise ValueError('情景冲击必须明确覆盖且仅覆盖全部持仓，不把缺失冲击当0')
        contributions = [{'symbol':p.symbol, 'weight':p.weight, 'shock':scenario.price_shocks[p.symbol],
            'contribution':p.weight * scenario.price_shocks[p.symbol]} for p in req.portfolio.positions]
        value = sum(row['contribution'] for row in contributions)
        result = {'scenario_id':scenario.scenario_id, 'name':scenario.name, 'origin':scenario.origin,
            'as_of_date':req.portfolio.as_of_date.isoformat(), 'currency':req.portfolio.currency,
            'portfolio_return':value, 'loss_fraction':max(-value, 0.), 'unit':'fraction',
            'cash_weight':req.portfolio.cash_weight, 'cash_return':0., 'contributions':contributions}
        artifact = store.put(scope_id=scope, tool_name='stress_test_portfolio', inputs=req.model_dump(mode='json'),
            scenario_results=[result], limitations=['静态价格冲击；现金收益0；不含费用、税费、FX、相关性变化或再平衡，不代表预测/概率。'])
        return json.dumps({'status':'available','artifact':artifact}, ensure_ascii=False, allow_nan=False)
    except (ValueError, KeyError, TypeError) as exc:
        return _unavailable(exc)
