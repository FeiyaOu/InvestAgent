"""Deterministic V1 risk checks and static price shocks; no market API or LLM."""
import json
from typing import Literal

import pandas as pd
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import ValidationError

from src.core.datasets import DatasetStore
from src.specialists.analytics.artifacts import AnalysisStore
from src.specialists.strategy import portfolio_risk
from src.specialists.strategy.artifacts import StrategyStore
from src.specialists.strategy.state import StrategyInput


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


def _analysis_store(config):
    store = (config.get('configurable') or {}).get('analysis_store')
    if not isinstance(store, AnalysisStore):
        raise ValueError('请求内分析存储缺失')
    return store


def _portfolio_check(req, config, name, threshold):
    """Portfolio-level limits use the shared constant-weight replay; never a single-stock proxy."""
    row = {'constraint':name, 'symbol':None, 'threshold':threshold, 'observed':None, 'unit':'fraction', 'status':'unknown'}
    has_matrix = any(r.get('tool_name') == 'build_return_matrix' for r in req.analysis_refs)
    if not req.portfolio or not has_matrix:
        return {**row, 'reason':('缺少持仓' if not req.portfolio else '缺少收益矩阵产物') + '；不以单股风险代替组合风险'}
    ref, frame = portfolio_risk.compatible_matrix(req, _analysis_store(config))
    if ref is None:
        return {**row, 'reason':f'{frame}；不以单股风险代替组合风险'}
    port = portfolio_risk.portfolio_returns(frame, {p.symbol:p.weight for p in req.portfolio.positions})
    metrics, reasons = portfolio_risk.risk_metrics(port, ref['assumptions']['periods_per_year'])
    metric = 'annualized_volatility' if name == 'max_portfolio_volatility' else 'max_drawdown'
    value = metrics[metric]
    return {**row, 'observed':value, 'analysis_id':ref['analysis_id'], 'start_date':ref['start_date'], 'end_date':ref['end_date'],
            'status':'unknown' if value is None else 'violated' if value > threshold else 'satisfied',
            'reason':reasons.get(metric) or '当前权重对历史收益的恒定权重回放，非未来保证'}


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
                checks.append(_portfolio_check(req, config, name, threshold))
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


@tool
def assess_portfolio_risk(return_matrix_analysis_id: str, config: RunnableConfig) -> str:
    """Replay current weights over an authorized return matrix: volatility, drawdown, 1-day VaR/CVaR.

    Constant weights (daily rebalanced), cash return 0; losses are positive fractions.
    Historical VaR/CVaR need 100 (95%) / 250 (99%) returns; parametric uses a normal model.
    Every non-cash holding must be in the matrix; nothing is silently dropped.
    """
    try:
        req, store, scope = _context(config)
        if req.portfolio is None or not req.portfolio.positions:
            raise ValueError('组合风险需要非现金持仓、权重和持仓日期')
        ref, frame = portfolio_risk.compatible_matrix(req, _analysis_store(config), return_matrix_analysis_id)
        if ref is None:
            raise ValueError(frame)
        port = portfolio_risk.portfolio_returns(frame, {p.symbol:p.weight for p in req.portfolio.positions})
        ppy = ref['assumptions']['periods_per_year']
        metrics, reasons = portfolio_risk.risk_metrics(port, ppy)
        values = portfolio_risk.nav(port)
        result = {'return_matrix_analysis_id':ref['analysis_id'], 'as_of_date':req.portfolio.as_of_date.isoformat(),
            'start_date':ref['start_date'], 'end_date':ref['end_date'], 'observations':len(port),
            'cash_weight':req.portfolio.cash_weight, 'metrics':metrics, 'reasons':reasons,
            'units':{k:'loss_fraction' if 'var' in k or k == 'max_drawdown' else 'fraction' for k in metrics},
            'method':{'weighting':'constant_weight_daily_rebalanced', 'cash_return':0., 'horizon_days':1,
                'historical_quantile':'numpy_linear', 'parametric_model':'normal', 'periods_per_year':ppy,
                'min_observations':portfolio_risk.MIN_OBSERVATIONS}}
        series = {'portfolio_nav':[{'date':str(day), 'value':float(v)} for day, v in values.items()]}
        artifact = store.put(scope_id=scope, tool_name='assess_portfolio_risk', inputs=req.model_dump(mode='json'),
            risk_results=[result], series=series, limitations=[
                '按当前权重对历史收益做恒定权重回放（每日再平衡），不是该组合的真实历史业绩，也不预示未来。',
                '参数法基于正态假设，会低估厚尾风险；VaR不是最大可能损失。',
                *ref['limitations']])
        return json.dumps({'status':'available','artifact':artifact}, ensure_ascii=False, allow_nan=False)
    except (ValueError, KeyError, TypeError) as exc:
        return _unavailable(exc)


@tool
def replay_historical_scenario(scenario_key: Literal['2008_gfc', '2015_crash', '2020_covid'], config: RunnableConfig) -> str:
    """Replay current weights buy-and-hold through a fixed historical crash window.

    Windows are code-owned (2008_gfc, 2015_crash, 2020_covid). Uses authorized price datasets
    covering the window; cash return 0. If any holding lacks coverage (e.g. listed later),
    per-holding results are listed but no portfolio figure is computed and no proxy is used.
    """
    try:
        req, store, scope = _context(config)
        if req.portfolio is None or not req.portfolio.positions:
            raise ValueError('情景重演需要非现金持仓、权重和持仓日期')
        datasets = (config.get('configurable') or {}).get('dataset_store')
        if not isinstance(datasets, DatasetStore):
            raise ValueError('请求内数据存储缺失')
        name, start, end = portfolio_risk.HISTORICAL_SCENARIOS[scenario_key]
        loaded = [(ref['dataset_id'], datasets.get(ref['dataset_id'])) for ref in req.dataset_refs if ref['kind'] == 'price_history']

        def covering(symbol, index):
            reasons = []
            for ident, data in loaded:
                if data.symbol == symbol and (data.asset_type == 'index') == index:
                    series, reason = portfolio_risk.window_prices(data, start, end)
                    if series is not None:
                        return series, ident, None
                    reasons.append(reason)
            return None, None, reasons[0] if reasons else '缺少该标的的价格数据集'

        contributions, paths = [], {}
        for p in req.portfolio.positions:
            series, ident, reason = covering(p.symbol, False)
            if series is None:
                contributions.append({'symbol':p.symbol, 'weight':p.weight, 'status':'not_covered', 'period_return':None,
                                      'contribution':None, 'dataset_id':None, 'reason':reason})
                continue
            period = float(series.iloc[-1] / series.iloc[0] - 1)
            contributions.append({'symbol':p.symbol, 'weight':p.weight, 'status':'covered', 'period_return':period,
                'contribution':p.weight * period, 'dataset_id':ident, 'first_date':series.index[0],
                'last_date':series.index[-1], 'reason':None})
            paths[p.symbol] = series / series.iloc[0]
        full = len(paths) == len(req.portfolio.positions)
        value = None
        if full:
            joined = pd.concat(paths, axis=1, join='inner')
            value = req.portfolio.cash_weight + sum(joined[p.symbol] * p.weight for p in req.portfolio.positions)
        portfolio_return = sum(c['contribution'] for c in contributions) if full else None
        benchmarks = []
        for symbol in dict.fromkeys(data.symbol for _, data in loaded if data.asset_type == 'index'):
            series, ident, _ = covering(symbol, True)
            if series is not None:
                benchmarks.append({'symbol':symbol, 'dataset_id':ident, 'period_return':float(series.iloc[-1] / series.iloc[0] - 1)})
        result = {'scenario_id':scenario_key, 'name':name, 'origin':'historical_replay',
            'start_date':start.isoformat(), 'end_date':end.isoformat(), 'as_of_date':req.portfolio.as_of_date.isoformat(),
            'currency':req.portfolio.currency, 'portfolio_return':portfolio_return,
            'loss_fraction':max(-portfolio_return, 0.) if full else None,
            'max_drawdown':portfolio_risk.max_drawdown(value) if full else None,
            'coverage_weight':sum(c['weight'] for c in contributions if c['status'] == 'covered'),
            'cash_weight':req.portfolio.cash_weight, 'cash_return':0., 'unit':'fraction',
            'contributions':contributions, 'benchmarks':benchmarks}
        series = {'portfolio_value':[{'date':str(day), 'value':float(v)} for day, v in value.items()]} if full else None
        limits = ['买入持有回放：情景期间不再平衡；现金收益0；不含费用、税费与流动性冲击。',
                  '历史情景只说明当时发生过的走势，不代表未来会重演，也不是发生概率。',
                  '复权价格的区间收益可比，但价格水平不等于当时的实际成交价。']
        if not full:
            limits.append(f'{scenario_key} 有持仓未覆盖情景区间，未计算组合收益；不使用指数或行业代理。')
        artifact = store.put(scope_id=scope, tool_name='replay_historical_scenario', inputs=req.model_dump(mode='json'),
            scenario_results=[result], series=series, limitations=limits)
        return json.dumps({'status':'available','artifact':artifact}, ensure_ascii=False, allow_nan=False)
    except (ValueError, KeyError, TypeError) as exc:
        return _unavailable(exc)
