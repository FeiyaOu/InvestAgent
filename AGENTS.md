# InvestAgent — AGENTS.md

> 项目导航入口（给 AI Agent 和开发者看的地图）。
> 遵循 Harness Engineering "地图而非手册" 原则：~50 行入口，指向深层文档。

## 项目定位

任务型智能投研助手：用户输入 → Planner → Supervisor → Composer。
- 数据任务调用 Market Data 子图；明确报告请求调用原报告子图。
- Analytics 已接入计算、汇总与图表；Strategy/Risk V1 已接入约束检查和静态压力测试。
- 无 checkpoint 自动记忆；Streamlit 显式传入本会话摘要。

## 关键文件导航

| 文件 | 用途 |
|---|---|
| `spec/invest_spec.md` | 规格文档（一等公民）— C1–C9 约束权威来源 |
| `spec/project-architecture.md` | 架构决策文档 — 所有技术选型的依据 |
| `src/agent.py` | 公共门面（调用 parent_graph.py，无旧 Reactive 路径）|
| `src/parent_graph.py` | 父图接线，ParentState 与 TaskResult 见同目录对应文件 |
| `spec/strategy-agent-development.md` | Strategy/Risk实施步骤与验收记录 |
| `src/schemas.py` | 原报告 Pydantic 模型|
| `src/tools.py` | AKShare 工具函数（`@tool` 装饰器，含 fallback）|
| `src/stages/reporter.py` | `validate_report()`（唯一报告校验入口）|
| `src/stages/validator.py` | 校验节点（触发有向环②的地方）|

## 开发约定

1. **TDD 强制**：所有新功能必须先写失败的测试，再写实现
2. **Spec 同步**：修改约束或报告结构时必须同步更新 `spec/invest_spec.md`
3. **测试隔离**：单元测试禁止调用真实 API，mock AKShare 和 DASHSCOPE_API_KEY
4. **单一校验入口**：报告校验只通过 `validate_report()`，不在其他地方散落校验逻辑
5. **Fallback 必须**：所有 AKShare 调用必须有 `try/except`，网络异常不得崩溃 Agent

## 测试命令

```bash
pytest tests/ -q                              # 全部单元测试
pytest tests/test_reporter.py -v              # C1–C7 约束测试
pytest tests/test_agent.py -v                 # C8–C9 任务/响应测试
pytest tests/ -m integration                  # 集成测试（需真实 DASHSCOPE_API_KEY）
python linters/check_agent_structure.py       # 结构 lint 检查
```

## 架构约束

- 依赖方向：`tools ← stages/* ← agent.py`
- AKShare 只在 `src/tools.py` 中调用，stage 模块不直接调用 AKShare
- LLM 调用只在 `src/stages/` 中发生，`agent.py` 只负责编排
- 禁止反向依赖（`validator` 不能 import `perception`）
