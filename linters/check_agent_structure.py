# -*- coding: utf-8 -*-
"""
InvestAgent 结构校验 Linter

Harness Engineering 核心理念的实践：
1. "文档会腐烂，lint 规则不会" — 用 AST 强制执行结构不变量
2. 错误信息中嵌入修复指令 — Agent 可以自我纠正
3. 在 CI 中央层面强制执行 — 阻塞不合格的合并

用法：
    python linters/check_agent_structure.py

检查项：
    1. src/stages/reporter.py 中必须包含 validate_report 函数
    2. src/stages/reporter.py 中必须定义 REQUIRED_DIMENSIONS 常量（含全部4个维度）
    3. src/state.py 中必须定义 VALID_PROCESSING_MODES 常量（含 reactive 和 deliberative）
    4. src/agent.py 中必须包含 create_invest_agent 函数
    5. 5个 stage 节点函数必须存在于对应模块（perception/modeling/reasoning/decision/report_generation）
    6. spec/invest_spec.md 必须存在
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def get_root() -> Path:
    return Path(__file__).parent.parent


def _parse_source(path: Path) -> tuple[ast.Module | None, list[str]]:
    """解析 Python 源文件，返回 AST 和错误列表"""
    if not path.exists():
        return None, [
            f"ERROR: {path} 不存在。\n"
            f"FIX: 创建该文件并实现对应功能。参考 spec/invest_spec.md。\n"
        ]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        return tree, []
    except SyntaxError as e:
        return None, [f"ERROR: {path} 语法错误: {e}\nFIX: 修复语法错误后重新运行 lint。\n"]


def _get_func_names(tree: ast.Module) -> set[str]:
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def _get_assign_names(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _source_contains(path: Path, text: str) -> bool:
    return text in path.read_text(encoding="utf-8")


# ============================================================
# 检查项 1：validate_report 函数存在
# ============================================================

def check_validate_report(root: Path) -> list[str]:
    reporter = root / "src" / "stages" / "reporter.py"
    tree, errors = _parse_source(reporter)
    if errors:
        return errors

    if "validate_report" not in _get_func_names(tree):
        return [
            "ERROR: src/stages/reporter.py 缺少 validate_report() 函数。\n"
            "FIX: 添加 def validate_report(report: dict) -> list[dict] 函数，\n"
            "     逐条检查 spec/invest_spec.md 中的约束条件 C1–C7。\n"
        ]
    return []


# ============================================================
# 检查项 2：REQUIRED_DIMENSIONS 常量及维度完整性
# ============================================================

def check_required_dimensions(root: Path) -> list[str]:
    reporter = root / "src" / "stages" / "reporter.py"
    tree, errors = _parse_source(reporter)
    if errors:
        return errors

    source = reporter.read_text(encoding="utf-8")
    if "REQUIRED_DIMENSIONS" not in source:
        return [
            "ERROR: src/stages/reporter.py 缺少 REQUIRED_DIMENSIONS 常量。\n"
            "FIX: 添加 REQUIRED_DIMENSIONS = ['fundamental', 'market', 'news', 'analyst']，\n"
            "     确保与 spec/invest_spec.md 中的维度定义一致。\n"
        ]

    errors = []
    for dim in ["fundamental", "market", "news", "analyst"]:
        if f'"{dim}"' not in source and f"'{dim}'" not in source:
            errors.append(
                f"ERROR: REQUIRED_DIMENSIONS 缺少维度 '{dim}'。\n"
                f"FIX: 在 REQUIRED_DIMENSIONS 列表中添加 '{dim}'，\n"
                f"     确保与 spec/invest_spec.md 的维度定义一致。\n"
            )
    return errors


# ============================================================
# 检查项 3：VALID_PROCESSING_MODES 常量（C8 约束的锚点）
# ============================================================

def check_valid_processing_modes(root: Path) -> list[str]:
    state_file = root / "src" / "state.py"
    tree, errors = _parse_source(state_file)
    if errors:
        return errors

    source = state_file.read_text(encoding="utf-8")
    if "VALID_PROCESSING_MODES" not in source:
        return [
            "ERROR: src/state.py 缺少 VALID_PROCESSING_MODES 常量。\n"
            "FIX: 添加 VALID_PROCESSING_MODES = {'reactive', 'deliberative'}，\n"
            "     对应 spec/invest_spec.md 的 C8 约束。\n"
        ]

    errors = []
    for mode in ["reactive", "deliberative"]:
        if f'"{mode}"' not in source and f"'{mode}'" not in source:
            errors.append(
                f"ERROR: VALID_PROCESSING_MODES 缺少 '{mode}'。\n"
                f"FIX: 在 VALID_PROCESSING_MODES 中添加 '{mode}'（C8 约束要求）。\n"
            )
    return errors


# ============================================================
# 检查项 4：create_invest_agent 函数存在于 agent.py
# ============================================================

def check_create_invest_agent(root: Path) -> list[str]:
    agent_file = root / "src" / "agent.py"
    tree, errors = _parse_source(agent_file)
    if errors:
        return errors

    if "create_invest_agent" not in _get_func_names(tree):
        return [
            "ERROR: src/agent.py 缺少 create_invest_agent() 函数。\n"
            "FIX: 添加 def create_invest_agent() -> CompiledGraph 函数，\n"
            "     构建并返回编译后的 LangGraph StateGraph。\n"
        ]
    return []


# ============================================================
# 检查项 5：5个 stage 节点函数存在于对应模块
# ============================================================

STAGE_FUNCTIONS = {
    "src/stages/perception.py": "perception",
    "src/stages/modeling.py": "modeling",
    "src/stages/reasoning.py": "reasoning",
    "src/stages/decision.py": "decision",
    "src/stages/reporter.py": "report_generation",
}


def check_stage_functions(root: Path) -> list[str]:
    errors = []
    for rel_path, func_name in STAGE_FUNCTIONS.items():
        stage_file = root / rel_path
        tree, parse_errors = _parse_source(stage_file)
        if parse_errors:
            errors.extend(parse_errors)
            continue
        if func_name not in _get_func_names(tree):
            errors.append(
                f"ERROR: {rel_path} 缺少 {func_name}() 节点函数。\n"
                f"FIX: 添加 def {func_name}(state: InvestAgentState) -> dict 函数，\n"
                f"     作为 LangGraph 节点函数处理对应阶段的逻辑。\n"
            )
    return errors


# ============================================================
# 检查项 6：spec/invest_spec.md 必须存在
# ============================================================

def check_spec_exists(root: Path) -> list[str]:
    spec = root / "spec" / "invest_spec.md"
    if not spec.exists():
        return [
            "ERROR: spec/invest_spec.md 不存在。\n"
            "FIX: 创建规格文档，定义 C1–C9 约束条件和报告格式。\n"
            "     这是项目的一等公民文档，所有实现都是其可执行表达。\n"
        ]
    return []


# ============================================================
# 主函数
# ============================================================

def main() -> int:
    root = get_root()
    all_errors: list[str] = []

    checks = [
        ("检查1: validate_report 函数", check_validate_report),
        ("检查2: REQUIRED_DIMENSIONS 常量", check_required_dimensions),
        ("检查3: VALID_PROCESSING_MODES 常量", check_valid_processing_modes),
        ("检查4: create_invest_agent 函数", check_create_invest_agent),
        ("检查5: stage 节点函数", check_stage_functions),
        ("检查6: spec/invest_spec.md 存在", check_spec_exists),
    ]

    print("=" * 60)
    print("InvestAgent 结构 Lint 检查")
    print("=" * 60)

    for name, check_fn in checks:
        errors = check_fn(root)
        if errors:
            print(f"\n❌ {name}")
            for e in errors:
                print(e)
            all_errors.extend(errors)
        else:
            print(f"✓  {name}")

    print("\n" + "=" * 60)
    if all_errors:
        print(f"结果：FAILED — 发现 {len(all_errors)} 个问题")
        return 1
    else:
        print("结果：PASSED — 所有结构检查通过")
        return 0


if __name__ == "__main__":
    sys.exit(main())
