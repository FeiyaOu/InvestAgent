"""Supervisor/Analytics boundary: scoped references and canonical calculation outputs."""
from langchain_core.runnables import RunnableConfig

from src.analytics_artifacts import AnalysisStore
from src.analytics_state import AnalyticsResult
from src.datasets import DatasetStore
from src.task_contracts import TaskError


def _stores(config):
    runtime = config.get("configurable") or {}
    ds, analyses = runtime.get("dataset_store"), runtime.get("analysis_store")
    if not isinstance(ds, DatasetStore) or not isinstance(analyses, AnalysisStore):
        raise ValueError("请求内数据与分析存储缺失")
    return ds, analyses


def analytics_inputs(task: dict, results: dict, config: RunnableConfig) -> dict:
    """Only direct dependencies grant scope; Analytics results carry their source refs."""
    data_ids, analysis_ids = [], []
    for ident in task["depends_on"]:
        record = results[ident]
        if record["category"] not in {"market_data", "analytics"}:
            continue
        payload = record.get("result") or {}
        data_ids.extend(ref["dataset_id"] for ref in payload.get("dataset_refs", []))
        if record["category"] == "analytics":
            analysis_ids.extend(ref["analysis_id"] for ref in payload.get("analysis_refs", []))
    data_ids, analysis_ids = list(dict.fromkeys(data_ids)), list(dict.fromkeys(analysis_ids))
    refs, existing = [], []
    if data_ids or analysis_ids:
        ds, store = _stores(config)
        refs = [ds.get_ref(ident).model_dump(mode="json") for ident in data_ids]
        for ident in data_ids:
            ds.get(ident)
        for ident in analysis_ids:
            ref = store.get_ref(ident)
            if not {source["dataset_id"] for source in ref["dataset_refs"]} <= set(data_ids):
                raise ValueError("前置分析产物来源超出前置任务数据范围")
            existing.append(ref)
    params = task.get("analytics_parameters") or {}
    return {"task": task["question"],
            "subjects": params.get("subjects") or list(dict.fromkeys(ref["symbol"] for ref in refs)),
            "time_range": params.get("time_range", ""), "dataset_refs": refs,
            "existing_analysis_refs": existing, "assumptions": params.get("assumptions", {})}


def analytics_result(raw, inputs, config: RunnableConfig):
    if not isinstance(raw, dict) or raw.get("status") not in {"completed", "partial", "failed"}:
        raise ValueError("分析返回状态无效")
    if raw["status"] == "failed":
        try:
            error = TaskError.model_validate(raw.get("error")).model_dump()
        except ValueError:
            error = {"type": "analytics_failed", "message": "分析任务执行失败。"}
        return "failed", None, error
    if raw.get("error") is not None:
        raise ValueError("可用分析状态不能同时包含执行错误")
    parsed = AnalyticsResult.model_validate(raw.get("result"))
    allowed = {ref["dataset_id"] for ref in inputs["dataset_refs"]}
    returned = [ref["dataset_id"] for ref in parsed.dataset_refs]
    if len(returned) != len(set(returned)) or not set(returned) <= allowed:
        raise ValueError("分析结果的数据引用越界或重复")
    ids = [ref["analysis_id"] for ref in parsed.analysis_refs]
    if len(ids) != len(set(ids)):
        raise ValueError("分析引用重复")
    canonical = []
    if ids or allowed:
        ds, store = _stores(config)
        for ident in ids:
            ref = store.get_ref(ident)
            if not {source["dataset_id"] for source in ref["dataset_refs"]} <= allowed:
                raise ValueError("分析结果产物来源越界")
            canonical.append(ref)
    # Rebuild numerical findings and charts from runtime storage, never child text.
    limitations = list(dict.fromkeys(parsed.limitations + [text for ref in canonical for text in ref["limitations"]]))
    missing = list(parsed.missing_information)
    undefined = any(value is None for ref in canonical for value in ref["metrics"].values())
    if undefined:
        missing.append("部分指标不可定义或不可比较，详见计算限制。")
    if not canonical and not (missing or parsed.missing_data_requests):
        raise ValueError("无分析产物且未说明缺失数据")
    result = AnalyticsResult(summary=parsed.summary,
        findings=[{key: ref[key] for key in ("analysis_id", "tool_name", "metrics", "metric_units", "table")}
                  for ref in canonical], analysis_refs=canonical,
        chart_refs=[chart for ref in canonical for chart in ref["chart_refs"]],
        dataset_refs=inputs["dataset_refs"], assumptions={"requested": inputs["assumptions"],
            "effective": {ref["analysis_id"]: ref["assumptions"] for ref in canonical}},
        limitations=limitations, missing_information=list(dict.fromkeys(missing)),
        missing_data_requests=parsed.missing_data_requests)
    partial = (raw["status"] == "partial" or missing or parsed.missing_data_requests or not canonical or
               any(ref["data_mode"] == "mock" for ref in inputs["dataset_refs"]))
    return "partial" if partial else "completed", result.model_dump(mode="json"), None
