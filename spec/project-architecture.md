# InvestAgent — 当前项目架构

> 架构权威文档。2026-11-10：公共入口与 Streamlit 已完成父图迁移。
> 历史设计及分步决策见 [工作流演进规格](workflow-evolution.md)，最新迁移见第 16 节。

## 1. 请求级父图

```text
src/agent.py 公共门面 → create_parent_graph()
START → initialize → planner → supervisor → composer → END
             │           └─ 澄清/失败 ────────┘
             └─ 无效输入 ────────────────────┘
```

Planner 产生四类任务和依赖。Supervisor 是确定性顺序调度图，不额外调用 LLM：

| 类别 | 实现 | 当前状态 |
|---|---|---|
| market_data | src/market_data_agent.py | 已接入，工具循环与输出验证 |
| analytics | 待建设 | unsupported |
| investment_strategy | 待建设 | unsupported |
| report | src/report_graph.py | 已接入，原六节点流程 |

独立任务依次执行；依赖任务等待前置结果。partial 可传递可用证据，失败依赖阻断下游。
已完成任务结果先供 UI 展示，再由 Composer 汇总；不进行无界重试或动态重新规划。

## 2. 状态边界

- ParentState：输入、计划、各阶段状态/错误、按 task_id 分组的 TaskResult、最终回答。
- SupervisorState：局部调度状态，last_task_id 不进入父级。
- MarketDataState：局部 messages、工具预算、证据与结果，不充当用户对话历史。
- InvestAgentState：原报告局部状态，四阶段数据、final_report、validator 重试字段保持兼容。
- 子图通过显式适配输入和结果；父级只接回 task_results、supervisor_status、supervisor_error。
- TaskResult 约束终止状态、结果与错误的一致性；领域内容仍由各自模型和 validate_report() 验证。

当前不启用 checkpoint。每请求重新初始化，Streamlit 显式传入最近三轮文本摘要。
refresh / 重启可能丢失会话；thread_id 不再是公开 API 参数，也不代表自动记忆。
未来数据库、多轮恢复和并行 reducer 需要独立设计。

## 3. 报告子图与数据层

```text
perception → modeling → reasoning → decision → report → validator
                                      ↑                   │
                                      └─ 现有重试条件 ─────┘
```

节点函数、prompt、工具调用、输出格式与实际校验重试行为保持不变。
校验只通过 validate_report()；C1–C7 见 [主规格](invest_spec.md)。
工具 fallback 和模拟标记保留。AKShare 只在 src/tools.py 调用。
Market Data 复用五个现有工具，不自动提供尚未实现的结构化历史/财务分析能力。
报告参数缺失时当前适配仍用完整任务描述，准确抽取主题/行业/时间是待完善事项。

## 4. 展示和可观测性

Streamlit 直接调用父图，无独立 HTTP 后端。
通过 updates + custom / subgraphs=True 消费事件，task_started 标识子图所属任务。
只将根事件合并到父级快照，任务结果与报告进度单独展示；不调用 get_state()。
页面显示任务列表、数据证据、分析状态、每个报告的四节点输出和执行记录。
最终报告正文/下载/评估仍隐藏；后续阅读视图使用 Streamlit + Plotly（见演进规格第 7 节）。
LangFuse 回调可选，未配置时不影响运行；追踪不等于会话持久化。

## 5. 入口与验证

```python
from src.agent import run_invest_agent
state = run_invest_agent("茅台最新价格？", conversation_context="")
print(state["final_response"])
```

不再提供 assess/reactive 编排；run_invest_agent 的旧 thread_id 和全局报告参数已移除。
显式按任务 ID 的 report_parameters 和 RunnableConfig 为可选输入。
create_response_graph() 保留为已有计划的执行/汇总组件，不作为另一条旧 Reactive 入口。
C8 为四类任务与有效计划，C9 为非空用户响应；结构 lint 检查 TaskCategory。

- 单元与 AppTest 测试全部 mock 外部模型/API。
- integration 显式启用并要求真实 key，不在日常单元检查中运行。
- 启动：make run；验证：pytest tests/ -q、python linters/check_agent_structure.py。


## Analytics 建设进展（2026-11-12）

已确认的职责、V1/V2 工具及局部 State 见 [Analytics 实施规格](analytics-agent.md)。
已完成数据契约、请求内 DatasetStore 和 Market Data 历史日线采集引用；计算工具待建设，Analytics 在 Supervisor 中仍为 unsupported。
