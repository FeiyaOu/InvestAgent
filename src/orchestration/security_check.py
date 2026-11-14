"""Plan-time stock identity check: every 名称(代码) mention and portfolio code must match the snapshot.

Runs inside the planner repair loop so a model-recalled wrong code is corrected
before any data is fetched; the error text carries the correct code as feedback.
"""
import re

from src.data.tools import _security_directory, resolve_security
from src.orchestration.planner_schemas import TaskPlan

_MENTION = re.compile(r"([一-龥A-Za-z*]{2,12})\s*[（(]\s*((?:SH|SZ)?\.?[0-9]{6}(?:\.(?:SH|SZ))?)\s*[)）]",
                      re.IGNORECASE)


class SecurityIdentityError(ValueError):
    """A structurally valid plan names a stock whose code contradicts the exchange directory."""


def _hint(text: str, directory: dict[str, str]) -> str:
    """Longest official name contained in a mention such as 获取山西汾酒 -> 山西汾酒(600809)."""
    found = sorted(((name, code) for code, name in directory.items() if name in text), key=lambda x: -len(x[0]))
    return f"（{found[0][0]} 的代码是 {found[0][1]}）" if found else ""


def validate_plan_securities(plan: TaskPlan) -> None:
    directory = _security_directory()
    problems = []
    for task in plan.tasks:
        texts = [task.question]
        if task.analytics_parameters is not None:
            texts += task.analytics_parameters.subjects
        if task.strategy_parameters is not None:
            texts += task.strategy_parameters.subjects
        for text in texts:
            for name, code in _MENTION.findall(text):
                _, _, error = resolve_security(f"{name}({code})")
                if error and error.startswith("名称与代码不一致"):
                    problems.append(f"{task.task_id}: {error}{_hint(name, directory)}")
        portfolio = task.strategy_parameters.portfolio if task.strategy_parameters is not None else None
        for position in portfolio.positions if portfolio is not None else []:
            if position.name:
                _, _, error = resolve_security(f"{position.name}({position.symbol})")
                if error and error.startswith("名称与代码不一致"):
                    problems.append(f"{task.task_id} 持仓: {error}")
            elif directory and position.symbol not in directory:
                problems.append(f"{task.task_id} 持仓: 代码 {position.symbol} 不在沪深A股代码表中，请写明公司名并核对代码。")
    if problems:
        raise SecurityIdentityError("；".join(dict.fromkeys(problems)))
