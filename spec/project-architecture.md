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
| analytics | src/analytics_agent.py | 已接入调度、分析汇总与 Plotly 看板 |
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

已完成数据契约、请求内存储、结构化价格/估值快照采集、四个V1计算工具和独立Analytics子图。
analytics-methodology运行时skill已创建并固定加载；Supervisor调度/引用交接及父图双Store注入已完成；Planner数据依赖首版与Composer分析汇总已完成；Plotly 分析看板首版已完成（当前会话最近请求快照）。
父图analytics已启用；未执行真实模型/API端到端评估。
完整状态、无风险利率适用范围、样本不足及协方差产物边界见 [Analytics实施规格](analytics-agent.md)。

Planner计划现在检查Analytics的直接数据依赖，并支持可选analytics_parameters；Composer展示分析指标、假设和限制，见Analytics规格步骤7a。


### MiniRacer 原生崩溃隔离（2026-11-13）
用户报告libmini_racer.dylib地址池初始化FATAL并终止Python进程；本机AKShare的新浪解码路径使用MiniRacer。
尚未证明具体触发条件（并发、重载或运行库状态），不把加锁视为已验证根因修复。
所有现有stock_zh_a_daily和stock_zh_index_daily调用统一经src.tools._call_sina执行：
使用当前Python解释器启动独立进程（不使用multiprocessing fork），白名单函数名与JSON参数通过stdin传入，
返回JSON记录后再按现有数据契约验证。原生进程异常退出转换为Python异常，由既有工具fallback处理；
设置60秒超时，不向用户透传原始stderr。新解释器生命周期隔离V8，服务不因该子进程原生崩溃退出。
不修改依赖版本、不禁用工具并行；每次新浪回退增加启动开销。
单元测试mock进程退出和超时、参数/结果传输，并继续隔离所有网络请求。
用户原始原生崩溃未稳定复现，本次验证的是进程隔离与故障转换边界。


## Planner 输出可靠性改进计划（2026-11-13，已确认/待实现）

先统一Pydantic诊断并通过custom events在执行记录展示每次尝试；再简化LLM输出，
由代码补齐固定默认值；核实当前ChatTongyi/模型的结构化输出机制后再迁移Planner。
保留运行时Pydantic和依赖图业务校验，不将方法存在等同严格schema支持。
问题证据、实施边界与验收见[Planner校验问题识别与改进计划](workflow-evolution.md#planner-校验问题识别与改进计划2026-11-13)。


Planner可靠性阶段一首版已实现（2026-11-13）：共享validation_diagnostics格式化字段级错误，
planner_attempt custom事件交接逐次尝试诊断，Streamlit执行记录展示。输入值预览省略，
完整原始响应不存储；输出简化、提供方能力核实和结构化迁移仍待实施。


Planner后续交付（2026-11-13）：模型schema投影移除固定missing_data，运行时补齐no_fill。
默认tool_calling通过ChatTongyi.with_structured_output(dict schema)提交计划，仍用Pydantic校验。
PLANNER_OUTPUT_MODE=json可切回原解析路径；这不是strict JSON Schema。真实3例/模式均首次通过，
尚无失败率改善证据，详见工作流演进规格阶段二、三交付记录。
