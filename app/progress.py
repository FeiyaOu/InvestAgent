"""Research progress panel derived from real planner/task events (pure functions, no Streamlit calls)."""
from html import escape

CATEGORY_LABELS = {"market_data": "数据采集", "analytics": "计算分析",
                   "investment_strategy": "策略与风险", "report": "研究报告"}
_RESULT_STATES = {"completed": "done", "partial": "partial", "failed": "failed",
                  "blocked": "failed", "unsupported": "failed"}
_STATE_TEXT = {"done": "已完成", "active": "进行中", "pending": "等待中", "partial": "部分完成", "failed": "未完成"}


def build_steps(state: dict, active_task: str | None, planner_attempts: list[dict]) -> list[dict]:
    """[{label, detail, state}] in execution order: planning, each planned task, composition."""
    planning = state.get("planning_status")
    attempt = max((a.get("attempt", 1) for a in planner_attempts), default=1)
    if planning in {"ready", "needs_clarification"}:
        plan_state = "done"
        detail = (f"已拆解为 {len((state.get('plan') or {}).get('tasks', []))} 个任务" if planning == "ready"
                  else "问题需要澄清，未执行专家任务")
    elif planning == "failed":
        plan_state, detail = "failed", "未能生成有效计划"
    else:
        plan_state = "active"
        detail = f"第 {attempt} 次规划（上次校验未通过，正在修正）" if attempt > 1 else "识别研究对象、时间范围与所需数据"
    steps = [{"label": "理解问题并规划任务", "detail": detail, "state": plan_state}]
    results = state.get("task_results") or {}
    for task in (state.get("plan") or {}).get("tasks", []) if planning == "ready" else []:
        record = results.get(task["task_id"])
        task_state = (_RESULT_STATES.get(record["status"], "failed") if record
                      else "active" if task["task_id"] == active_task else "pending")
        steps.append({"label": CATEGORY_LABELS.get(task["category"], task["category"]),
                      "detail": task["question"], "state": task_state})
    if state.get("final_response"):
        compose = "done"
    elif state.get("supervisor_status") in {"completed", "partial", "failed"} or planning in {"needs_clarification", "failed"}:
        compose = "active"
    else:
        compose = "pending"
    steps.append({"label": "汇总回答", "detail": "整理结论、数据来源与局限说明", "state": compose})
    return steps


def progress_html(steps: list[dict], elapsed: float) -> str:
    tasks = steps[1:-1]
    finished = sum(step["state"] in {"done", "partial", "failed"} for step in tasks)
    counter = f" · 已完成 {finished}/{len(tasks)} 个任务" if tasks else ""
    rows = "".join(
        f'<div class="zh-step {step["state"]}"><span class="zh-step-dot">{index}</span>'
        f'<div><b>{escape(step["label"])}</b><small>{escape(step["detail"])}</small></div>'
        f'<em>{_STATE_TEXT[step["state"]]}</em></div>'
        for index, step in enumerate(steps, start=1))
    return (f'<section class="zh-progress"><div class="zh-progress-head"><i class="zh-orbit"></i>'
            f'<div><h2>正在进行深度研究</h2><p>已用时 {int(elapsed)} 秒{counter}</p></div></div>'
            f'<div class="zh-steps">{rows}</div></section>')
