# 工作流演进规格：保留报告流程，独立建设专家 Agent

- 决策日期：2026-11-10
- 当前状态：父图、公共入口与 Streamlit 已完成迁移，旧 Reactive 已删除（第 16 节）。
- 第 1–15 节记录各阶段决策与当时状态；涉及旧入口/未接入的叙述属于历史，以第 16 节为当前基线。
- 本轮范围：记录方案，不修改运行代码、节点逻辑或报告约束。

## 1. 已确认的边界

保留现有 Deliberative 报告生成流程，将其作为完整的报告子图接入未来父图。
本阶段不将报告内部五个阶段改写为自主 Agent，不以 skill 替代报告编排，
也不以新专家实现替换报告内部节点。

报告内部保持以下执行顺序及现有反馈路由：

```text
perception → modeling → reasoning → decision → report → validator
                                     ↑                    │
                                     └── 现有重试条件 ──────┘
```

保持现有节点函数、prompt、工具调用方式、输出结构、校验规则和实际重试行为。
`validate_report()` 继续是唯一报告校验入口，C1–C7 不变。
本决定不代表当前实现已满足规格中全部既有要求；已有差异另立任务处理，
不得在子图封装时顺便修改。

## 2. 保留当前逐节点 UI

当前界面继续以中间结果帮助用户理解研究过程。
「节点结果」视图完整、展开显示：

| 节点 | State 字段 |
|---|---|
| perception | `perception_data` |
| modeling | `world_model` |
| reasoning | `reasoning_plans` |
| decision | `selected_plan`（单数，沿用实际字段）|

节点返回后即可更新相应输出；未返回与失败状态应有明确提示。
最终报告的正文、下载和报告评估暂时隐藏，保留恢复展示的开关。
隐藏仅属于 UI 行为：后端仍生成、校验并保留 `final_report`。
本决定不引入新的图表、量化结果或虚构的专家执行状态。

## 3. 目标父图

```text
用户输入 + 对话上下文
          ↓
父级 Planner：识别任务、对象、依赖和期望产物
          ↓
Supervisor：调度、跟踪结果、补充任务
          ├─ 数据查询 Agent
          ├─ 分析 Agent
          ├─ 策略 / 风险 Agent
          └─ 报告子图（保留现有内部实现）
          ↓
汇总回答 + 分阶段展示
```

其他 Agent / 图独立开发、独立测试，完成后再整合进父图。
专家可拥有专属工具与方法型 skills，但不因此修改现有报告内部实现。
未来是否在报告内部复用新专家，属于另一次明确的架构决策。

## 4. 目标任务路由

父图按任务能力和用户要求的产物路由，不再仅按问题复杂度决定是否生成报告。

- 价格、行情等问题交给数据查询 Agent。
- 估值比较、因子或历史表现分析交给分析 Agent。
- 投资机会、情景与风险问题交给策略 / 风险 Agent。
- 明确请求生成投研报告时，才调用报告子图；报告主题或时间范围缺失时按需澄清。
- 同一消息可以拆出多个任务，并允许普通问题与报告请求共存。
- 独立任务可并行；存在依赖的任务等待所需结果。
- 已完成的结果先展示；最终汇总协调各任务结果，局部失败不得抹去已成功的结果。

例：

| 用户请求 | 目标路径 |
|---|---|
| 茅台和五粮液现在什么价格？ | 数据查询 Agent |
| 比较它们的估值，并分析未来一年的投资机会。 | 分析 + 策略 / 风险，不自动生成报告 |
| 生成一份新能源行业未来一年的投资研究报告。 | 报告子图 |
| 查茅台股价，同时生成新能源行业报告。 | 数据查询 + 报告子图，按完成情况展示 |

以上为未来父图规则，不表示当前 `assess_query` 已更改。
现有 C8–C9 和原入口路由在父图迁移前继续保持；整合时再同步规格与测试。

## 5. 分阶段实施与验收

1. **冻结基线**：保留报告链和当前节点结果 UI；本规格记录完成。
2. **独立建设专家**：数据查询、分析、策略 / 风险 Agent 各自具备输入输出契约、
   mock 测试、失败处理及有界工具执行，不改报告节点。
3. **封装报告子图**：复用现有节点函数及内部边；仅新增必要的图构建与边界适配。
   通过回归测试确认节点顺序、输出及校验/重试行为保持一致。
4. **整合父图**：添加任务计划、Supervisor、按任务收集结果及最终汇总；
   在边界隔离任务状态，避免并行任务覆盖 `final_response` / `final_report`。
5. **接入 UI**：父图事件映射到执行记录及结果视图，保持报告四个中间字段可见；
   最终报告仍隐藏，除非后续明确恢复。

所有实现遵循项目 TDD 和 API 隔离要求。验收应覆盖：报告回归、普通分析不触发报告、
混合请求的独立结果、依赖执行、部分失败和逐节点展示。

## 6. 本阶段不做

- 不重写五个报告阶段，不新增其内部自主工具循环。
- 不改变报告 JSON、C1–C7 或既有校验入口。
- 不因保存本方案而引入数据库、供应商 API 或量化库。
- 不宣称父图、Supervisor 或报告子图已上线。


## 7. 报告阅读视图与数据可视化（2026-11-10 已确认，待实现）

### 7.1 范围与启用时机

后续新增独立的报告阅读视图，以「结构化报告内容 + 数据图表」展示最终报告，
JSON 保留作为数据交换与下载格式。
这是展示层扩展，不改变报告子图内部节点逻辑、报告 JSON 或 C1–C7。
数值数据通过独立的结果 / 数据集引用提供给展示层，无需塞入现有报告 JSON。

当前继续保留四节点完整输出 UI，最终报告正文、下载和评估仍隐藏。
本决定不自动启用报告阅读视图；后续明确恢复最终报告展示时再接入。

### 7.2 首版技术选择

- **Streamlit 原生组件**：页面布局、指标卡、报告分区、表格、来源列表。
- **Plotly**：交互式价格、成交量、相对基准收益、回撤及估值比较图。
- **pandas Styler**：按需用于财务与同业比较表的格式和条件着色。
- **ECharts**：仅在后续确有复杂图表联动需求时评估，不作为首版依赖。
- 不为报告美化迁移 React；本次文档更新不安装依赖。

### 7.3 目标阅读结构

1. 报告标题、研究区间、数据截至时间。
2. 评级与实际可用的关键指标，如区间收益、波动率、最大回撤。
3. 核心投资论点。
4. 有数据支持的价格 / 成交量及相对基准表现图。
5. 基本面、市场面、消息面、分析师观点。
6. 候选方案比较及最终决策依据。
7. 风险因素、数据缺失与分析限制。
8. 来源、引用和 JSON 下载。

上述模块按实际结果展示，不要求每份行业报告都包含个股价格或组合风险指标。

### 7.4 数据规则与复用

- 报告文字、评级、维度摘要和风险列表来自现有报告结构。
- 图表与数值指标来自 API 的结构化数据和确定性计算工具结果；
  不从 LLM 叙述中猜测、补造或提取未经核验的数字用于绘图。
- 展示层通过任务 ID / artifact ID 读取对应数据，保证报告与图表关联同一研究任务。
- 保留来源、日期、单位、价格复权口径及模拟 / 降级状态；模拟数据明确标识。
- 缺少数据时隐藏相应图表或提示不可用，不用零值替代缺失值。
- 切换标签、展开内容等纯展示操作复用已有结果，不重新调用 LLM 或数据 API。

### 7.5 实施验收

实现时先写 mock 测试，验证报告分区、图表数据关联、无数据与模拟数据提示、
纯展示操作不触发重新研究，以及 JSON 下载。
恢复报告阅读视图后，四节点详情仍需可查看；报告校验仍仅通过 `validate_report()`。


## 8. Market Data Agent：独立子图（2026-11-10 已确认并实现首版）

### 8.1 范围

采用显式 LangGraph 子图 + ToolNode 的 ReAct 循环。独立开发、测试和调用，
尚未接入父图或 UI；原 `perception.py`、报告节点与报告 UI 保持不变。
首版复用现有五个工具，不引入新的供应商或数据库。

```text
initialize → agent → tools → agent
                 └→ finalize → END
                      └─ 输出校验失败且可重试 → agent
```

`src/market_data_agent.py` 仅负责编排，模型调用位于 `src/stages/market_data.py`；
独立状态和 Pydantic 契约位于 `src/market_data_state.py`。

### 8.2 接口与状态

- 构建入口：`create_market_data_agent()`，返回可 invoke / stream 的编译子图。
- 输入：必填 `task`；可选 `subject`、`time_range`、`existing_evidence`。
- 状态：局部 messages、工具轮数与调用次数、输出修正次数、工具证据、result、status、error。
- 输出：`result` 包含 answer、evidence_ids、missing_information、evidence；
  使用 Pydantic 验证，证据引用必须存在，无证据时必须说明缺失信息。
- evidence 保留工具原文、名称、调用 ID、采集时间、执行状态、数据模式。
  已有证据按同一模型验证；采集时间不代表行情发生时间。
- 旧工具缺乏可靠的结构化来源和行情日期，source_url / as_of_date 默认空；
  不允许模型补造这些元数据。status=returned 只表示工具返回，不保证数据可用或事实正确。
- 最终状态：completed / partial / failed；失败时 result 为 None，error 包含 type / message。
  缺失信息、工具异常、模拟模式或识别到的降级文本导致 partial。
  降级文本识别为兼容旧接口的启发式检查，不替代未来结构化数据状态。

### 8.3 执行控制

- 默认最多 3 轮工具执行、累计 8 次工具调用；整批调用超预算时不执行该批。
- 最终 JSON 或证据引用校验失败后，默认最多修正 1 次；预算可由构建参数调整。
- 工具异常转换为 ToolMessage 供模型处理，模型或未处理工具异常返回失败状态。
- 复用 LLM 工厂的供应商重试设置；上述预算限制调用数量，不保证总耗时。
  同步工具的网络超时沿用原实现，本版不提供可强制中断的请求级超时。
- 不安装私有 checkpointer；独立 invoke 默认相互隔离，未来由父图统一设计持久化边界。
- graph.stream 提供节点更新，包含局部消息、工具结果与最终状态；前端接线待后续实现。

### 8.4 调用与验收

```python
from src.market_data_agent import create_market_data_agent

graph = create_market_data_agent()
state = graph.invoke({"task": "查询茅台最新可用股价", "subject": "茅台"})
# state["status"] 与 state["error"] 用于失败处理
# state["result"] 用于展示回答和证据
```

测试采用 mock 模型与本地测试工具，不访问真实 API。覆盖工具循环、已有证据、
输出修正与失败、未知证据引用、空任务、工具异常、模拟及降级数据、
工具预算与多次调用隔离。运行：`pytest tests/test_market_data_agent.py -q`。

历史行情、财务、估值与公告结构化工具、硬超时机制、父图和 UI 整合仍待后续任务。


## 9. 报告子图封装完成（2026-11-10）

- 新增 `src/report_graph.py`，`create_report_graph()` 编译现有六节点报告链，
  不配置私有 checkpointer，可独立调用，也可继承父图 checkpoint。
- 六个节点函数原样复用；节点内部实现、prompt、工具调用、输出字段及实际校验重试行为均未修改。
- `route_after_validator` 移至报告编排模块，并从 `src.agent` 继续导出，兼容已有调用。
- 原 `create_invest_agent()` 的 Deliberative 分支挂载为 `report_workflow`，完成后退出。
  `route_after_assess` 仍返回原逻辑标签 perception，由条件边映射到 report_workflow；
  Reactive 路径、C8–C9 路由策略和公开调用参数不变。
- Streamlit 通过 `subgraphs=True` 消费内部节点更新，跳过重复的父级汇总事件；
  四节点完整输出继续展示，最终报告展示开关仍关闭。
- 仍使用现有共享 `InvestAgentState`，本次不改变输入初始化和多轮生命周期策略。
- 此入口只是现有双路径编排，不代表目标 Planner / Supervisor 已实现；
  Market Data Agent 仍独立，未接入报告或原入口。
- 回归测试覆盖独立报告执行、重试顺序、父图返回状态和嵌套 UI 事件。


## 10. 父图任务规划与调度（2026-11-10 已确认，待分步实现）

本节明确第 3–5 节的父图方案与最新实施顺序。第 8、9 节为已实现基线；
当前运行入口仍使用原双路径，不能将本节目标视为已经上线。

### 10.1 目标结构与四类任务

```text
用户输入 + 对话上下文
          ↓
Planner：拆解任务、分类、识别依赖
          ↓
Supervisor：分派就绪任务、跟踪状态、收集结果
          ├─ market_data 子图（已独立实现）
          ├─ analytics Agent（待建设）
          ├─ investment_strategy Agent（待建设）
          └─ report 子图（已封装，内部实现保持不变）
          ↓
Composer：按用户原问题汇总回答
```

四个能力入口不要求相同的内部结构：report 保持完整工作流，其余专家可使用工具循环。
原 Reactive 工具路径将在新父图切换完成时移除，由 market_data 承担行情和数据查询。
不同时维护两套简单查询实现；迁移前仍保留旧入口以便增量验证。

| category | 职责 | 示例 |
|---|---|---|
| `market_data` | 获取、核实与整理数据证据 | 查茅台与五粮液最新价格 |
| `analytics` | 数值计算、估值比较、历史表现或因子分析 | 比较两家公司估值 |
| `investment_strategy` | 投资机会、情景、组合与风险解释 | 分析未来一年投资机会 |
| `report` | 明确要求的完整投研报告 | 生成新能源行业未来一年投研报告 |

复杂分析不自动升级为 report。明确报告请求可以与普通查询任务共存。
报告内部五阶段及 validator 不因父图整合而重写，也不替换成新专家。

### 10.2 Planner 契约

Planner 接收用户原文和可用对话上下文，只生成计划，不调用数据工具或执行专家。
计划经 Pydantic 和确定性检查后才可执行，最低包含：

- `task_id`：计划内唯一标识。
- `category`：上述四个类别之一。
- `question`：保留主体、时间范围和用户意图的具体任务描述。
- `depends_on`：所依赖的 task_id 列表；无依赖使用空列表。

计划不得存在重复 ID、未知依赖、自依赖或有向环。
应保留相关问题的共享上下文，不把报告内部的固定阶段再次拆成父级重复任务。
可独立的任务不强加依赖；确需数据或分析产物的任务必须表达依赖。
需要澄清或无法可靠规划时返回明确状态，不生成伪造的可执行计划。
具体类名、其他字段、计划失败处理与有界重试在 Planner 独立实现阶段细化并同步规格。

### 10.3 Supervisor 与结果管理

Supervisor 执行已验证计划，代码负责依赖判断、调度、状态更新及完成门槛；
不要求每次分派都额外调用 LLM。需要动态补充任务时，后续显式设计重新规划机制。

- 按 task_id 保存状态与结果，不让多个任务覆盖共享 final_response / final_report。
- 通过边界适配调用不同子图的输入输出，不要求现有子图共享同一 State。
- 收集 completed、partial、failed、unsupported 等结果；状态枚举和依赖失败策略在实现时定稿。
- analytics 与 investment_strategy 接入前仍可被 Planner 分类，但 Supervisor 明确标为能力未接入，
  不静默转给 report 或 market_data，不生成伪结果。
- 初期可以顺序执行；后续允许独立任务并行，不承诺首次实现即提供并行调度。
- 局部失败保留其他任务的成功结果；全部任务终止后进入 Composer，避免无限调度。
- 原报告的部分错误行为保持原状，由外层适配报告实际 error / validation_errors，
  不因子图正常返回就宣称所有校验通过。

### 10.4 Composer 与 UI

Composer 接收原问题、任务计划和各任务结果，统一组织回答，去重并说明数据来源、
时间口径、缺失能力、部分失败和不确定性，不把未完成任务表述成已完成。
报告正文展示仍受现有隐藏开关控制；不得通过汇总步骤绕过该开关直接输出完整报告。

UI 后续展示任务列表、类别、依赖及执行状态，并及时展示已经完成的结果。
报告四个中间字段继续可见，报告子图内部的流式节点事件继续保留。
纯 UI 展开与切换不得重启研究。

### 10.5 分步实施顺序与验收

各阶段单独实现、测试和汇报，不在一次改动中完成全部父图：

1. **本轮：规格同步**。仅记录本方案，不写运行代码。
2. **下一步：Planner**。独立实现契约、模型节点及确定性计划校验；mock 测试多问题、
   四类任务、对话指代、依赖、非法计划及规划失败。暂不切换旧入口。
3. **Supervisor**。先接入 market_data 与 report；测试调度、边界适配、状态隔离、
   缺失能力及依赖/局部失败，不修改报告内部实现。
4. **Composer 与入口切换**。组合新父图并移除旧 Reactive 路径；
   将 C8–C9 的旧模式约束改为任务类别和响应完整性要求，同步测试、文档与结构检查。
   迁移前旧 C8–C9 仍约束旧入口。
5. **UI 接入**。展示任务进度、部分结果及原报告节点输出，覆盖流式与失败场景。
6. **后续专家**。分别建设 analytics 与 investment_strategy，通过契约测试后接入。

不因本方案自动引入数据库、API 供应商、量化库或改变最终报告输出结构。


## 11. 独立 Planner 首版（2026-11-10 已实现，未接入旧入口）

### 11.1 代码与调用

- `src/planner_schemas.py`：PlanTask、TaskPlan、PlannerState。
- `src/stages/planner.py`：`planner(state, max_retries=1)`，可直接调用或注册为 LangGraph 节点。
- 不执行工具、专家或报告子图，不改变 `src/agent.py` 和 Streamlit 的当前行为。

```python
from src.stages.planner import planner

update = planner({
    "user_query": "茅台和五粮液现在什么价格？比较估值并分析未来一年投资机会。",
    "conversation_context": "",  # 父图后续提供相关对话或研究摘要
})
```

输入 user_query 必须为非空文本；可选 conversation_context 为文本，默认为空。
不自动读取数据库或旧入口消息；后续父图负责构造上下文。

### 11.2 输出契约与校验

返回部分状态更新：plan、planning_status、planning_error、planning_attempts。

- plan 为经 Pydantic 验证的字典，包含 status、tasks、clarification_questions。
- tasks 每项严格包含 task_id、category、question、depends_on；category 为第 10 节四类值。
- ready：1–12 个任务、无澄清问题；needs_clarification：无任务且至少一个非空澄清问题。
- 校验拒绝空白任务描述、非法类别、重复 ID、重复依赖、未知依赖、自依赖和循环依赖；
  允许依赖计划中位置靠后的任务，不强制列表按拓扑顺序排列。
- 非法输入、模型初始化/调用异常或无效输出耗尽修正次数时，planning_status=failed，
  plan=None，planning_error 提供 type 和用户可读 message，避免复用过期计划。
- 默认最多一次输出修正，即最多两次规划生成；max_retries 可设为 0–3。
  JSON 解析或计划验证错误提供修正反馈；供应商异常直接失败，供应商内部重试仍由 LLM 工厂控制。
- planning_attempts 为本节点的生成尝试次数，不包含供应商内部重试。

### 11.3 语义规则与验证边界

Prompt 要求保留主体与时间范围、利用上下文解析指代、仅明确报告请求产生 report，
不因 analytics / investment_strategy 尚未接入而更改分类，也不重复拆分报告内部阶段。
对象或意图不明确时请求澄清。

确定性验证只保证结构与依赖合法；不能证明模型没有遗漏问题、分类正确或准确理解指代。
当前 mock 测试验证契约、上下文传入、混合计划、修正链和节点集成；
未运行真实模型/API 的语义评估，后续可用固定案例集独立评估规划质量。

下一步仍是独立建设 Supervisor，接入 market_data / report；本轮不提前实施。


## 12. 独立 Supervisor 首版（2026-11-10 已实现，未切换入口）

### 12.1 入口与范围

`src/supervisor.py` 提供 `create_supervisor_graph()`，状态定义位于 `src/supervisor_state.py`。
它是确定性顺序调度子图，不新增 LLM 调用，不自动重新规划，不包含 Planner / Composer。
已接入独立 market_data 与 report 子图；不修改报告内部代码和旧入口 / UI。

```python
from src.stages.planner import planner
from src.supervisor import create_supervisor_graph

planning = planner({"user_query": "查询茅台价格"})
# failed 时先处理 planning_error；needs_clarification 时先向用户澄清。
if planning["planning_status"] == "ready":
    state = create_supervisor_graph().invoke({"plan": planning["plan"]})
    records = state["task_results"]
```

每次 initialize 重新验证 TaskPlan，清空旧任务结果。
无效计划不执行专家；澄清计划直接返回 needs_clarification。
无私有 checkpointer；未来父图的持久化、任务恢复策略另行接入。

### 12.2 调度、任务结果与状态

- 在计划列表中选择首个所有前置任务已终止的未执行任务，不要求计划预先拓扑排序。
- completed / partial 前置任务允许继续；failed / unsupported / blocked 前置任务使下游 blocked。
  partial 允许继续不代表证据充分，结果仍保留缺失信息供后续解释。
- analytics / investment_strategy 返回 unsupported；不转交其他专家。
- 每个任务只执行一次，不自动重试；异常作为该任务 failed 收集，独立任务继续运行。
- task_results 按 task_id 保存原任务字段及 status、result、error；不覆盖共享 final_report。
- supervisor_status 为 running / completed / partial / failed / needs_clarification。
  全部任务 completed 才整体 completed；有可用的 completed / partial 结果但非全部成功时为 partial；
  没有可用结果时为 failed。逐任务 error 是失败详情，supervisor_error 用于计划或调度级错误。
- 支持最多12个任务，在默认图递归预算内终止；首版不做并行调度。

### 12.3 子图边界适配

Market Data：任务 question 映射到 task；直接依赖的 market_data 证据传入 existing_evidence。
为避免多个任务的 tool_call_id 冲突，在传入时加前置 task_id 命名空间。
返回结果用 MarketDataResult 验证，保留子图的 completed / partial / failed 状态。

Report：每次创建全新报告输入，retry_count=0、messages=[]、四阶段结果与报告清空。
可选 report_parameters 按报告 task_id 提供 research_topic、industry_focus、time_horizon，
拒绝非报告任务参数和额外字段。缺少参数时 research_topic / industry_focus 沿用完整任务 question，
时间范围为「按任务描述」；此为保留意图的临时适配，不是准确的行业与时间抽取。
后续 Planner / 父图整合应细化结构化参数，避免整句作为行业工具查询参数。

报告子图继续自行采集数据；前置任务只控制就绪，不向其内部注入新专家或跳过阶段。
完整返回状态（包括四节点输出和 final_report）保留在对应任务 result 中。
报告未完成、已有 error 或 JSON 无效时为 failed；JSON 无效时仍保留节点输出。
报告正常终止后仅通过 validate_report() 复核；存在约束问题则 partial，不宣称校验通过，
已有报告错误仍为 failed。不在 Supervisor 复制 C1–C7 约束实现或错误分级规则。

### 12.4 流式与验收边界

图节点为 initialize → supervisor（每次执行一项任务并更新 task_results）→ finish。
通过 stream(..., subgraphs=True) 可消费子图更新和逐任务结果；尚未接入 Streamlit。
子图消息与报告全文不自动展示，报告正文隐藏策略仍由未来 Composer / UI 保持。

mock 测试覆盖分类调度、依赖顺序、证据传递、状态隔离、未接入能力、下游阻断、
局部异常、报告适配与复核、完整12任务终止，以及真实子图结构下的嵌套执行和事件。
不访问真实模型或行情 API；未新增数据库或强制网络超时。
下一步为 Composer 与新父图入口整合，本轮不提前实现。


## 13. Composer 与 Supervisor 接线（2026-11-10 已实现，未切换入口）

- 新增 `src/stages/composer.py`，`composer(state)` 汇总终止任务；
  `src/composer_state.py` 定义 ResponseState 与非空回答的 Pydantic 模型。
- 新增 `src/response_graph.py` 的 `create_response_graph()`：
  START → execution（现有 Supervisor 子图）→ composer → END。
- 输入 user_query、已验证的 plan、可选 report_parameters；
  返回原任务结果、supervisor_status，以及 final_response、composition_status、composition_error。
- 不自动调用 Planner；暂不切换 `src/agent.py`、不移除旧 Reactive、不改 Streamlit。

```python
from src.stages.planner import planner
from src.response_graph import create_response_graph

query = "查询茅台最新价格"
planning = planner({"user_query": query})
if planning["planning_status"] == "ready":
    result = create_response_graph().invoke({"user_query": query, "plan": planning["plan"]})
    answer = result["final_response"]
```

### 13.1 汇总行为

有可用 market_data 回答时，通过 LLM 生成简洁汇总，并验证非空 answer。
同时附加确定性的逐任务结果：类别、问题、完成状态、数据回答、缺失信息、工具名、
数据模式、数据日期、采集时间及实际存在的来源链接。采集时间不冒充行情日期。
模型失败、JSON 解析失败或输出无效时，不额外重试，返回逐任务结果作为 fallback；
不丢失 Supervisor 已收集的成功结果，不泄漏模型调用的原始异常。

澄清状态直接返回澄清问题，不调用模型；没有可用结果时返回任务状态或通用失败提示。
仅有报告产物而没有数据回答时，直接返回状态，不调用模型。
Supervisor 尚未终止时拒绝汇总。
composition_status=completed 只表示汇总完成，不代表所有任务或证据完整；
业务完成情况仍以 supervisor_status 和逐任务 status 为准。

### 13.2 报告展示边界

Composer 按白名单构造模型输入：report 只包含任务信息、状态和正文隐藏提示，
不传入 final_report、world_model 等报告负载，也不在回答中渲染其正文。
原始报告与四节点结果仍保存在 task_results，供未来 UI 的节点详情使用。
此保证针对程序的数据传递边界；LLM 自由文字的事实正确性仍需后续真实模型评估。

### 13.3 验收与后续

mock 测试覆盖部分成功、未接入能力、数据缺失与模拟标识、来源展示、模型失败回退、
报告负载隔离、澄清、无效计划、真实解析链，以及 Supervisor → Composer 图内连通。
不访问真实模型或行情 API。下一步再整合 Planner 并迁移入口 / UI，不提前实施。


## 14. ParentState 与统一 TaskResult（2026-11-10 已实现契约，未接父图）

### 14.1 父级状态与初始化

`src/parent_state.py` 定义独立 ParentState、Pydantic ParentRequest 与 create_parent_state()。
父级只包含 user_query、conversation_context、report_parameters，以及 planning、supervisor、
composition 各阶段状态、错误、plan、task_results 和 final_response。
plan / final_response 和各阶段状态在新请求时初始化为 None；次数为0，结果字典为空。
输入非空问题与结构化报告参数通过 Pydantic 验证；输入无效时构造函数抛 ValidationError，
未来用户入口负责捕获并提示，当前尚未接线。

不包含子图 messages、current_phase、retry_count、顶层 final_report 或 Supervisor 的 last_task_id。
子图局部字段保留在子图，报告完整输出作为某个任务的 result 保存。
create_parent_state() 每次新建并复制输入，不复用上一请求的计划、结果或回答；
仅显式传入的 conversation_context 作为对话上下文，不自动保存工具消息。
本轮不增加 request/thread 身份、数据库或 checkpointer。

### 14.2 统一任务结果边界

`src/task_contracts.py` 定义 TaskResult（继承 PlanTask）和 TaskError。
统一信封字段为 task_id、category、question、depends_on、status、result、error。

- status 仅允许 completed / partial / failed / blocked / unsupported，记录只保存终止结果。
- completed / partial 必须有字典 result 且 error=None。
- failed 必须有结构化 error，允许保留字典 result（如失败报告的节点结果）。
- blocked / unsupported 必须有结构化 error 且 result=None，不伪造未执行任务产物。
- error 严格包含非空 type / message；拒绝额外信封字段。
- result 是各专家自行验证的局部载荷，不强迫不同子图采用同一种内容结构。
  TaskResult 不代替 MarketDataResult 或 validate_report() 的领域校验。

validate_task_results() 验证结果映射的 key 与 task_id 一致，并返回独立深复制字典。
Supervisor 在写出每个终止结果时验证 TaskResult；Composer 在汇总前验证结果映射，
无效数据返回 composition_status=failed / invalid_task_results，不调用模型。
统一契约不能证明结果事实正确，也不在此处验证整个任务依赖图；计划仍由 TaskPlan 验证。

### 14.3 与现有组件复用及后续范围

Planner / Supervisor / Composer 现有节点接口继续使用部分字典状态更新，
与 ParentState 同名边界字段兼容，不将三个组件的全部局部 State 无条件合并。
父图未来通过适配只投影必要字段，尤其不把局部消息作为用户对话历史。
当前顺序调度按任务结果字典覆盖更新；未来并行时再定义按 task_id 合并的 reducer。

本轮不构建完整父图、不迁移 Streamlit、不改报告节点、不删除旧 Reactive。
测试覆盖请求隔离、输入复制、状态一致性、失败报告产物保留、结果 key 校验、
Composer 无效边界处理，以及手动顺序复用 Planner → Supervisor → Composer。
下一步再基于该契约设计初始化、规划失败/澄清路由与父图接线。


## 15. 完整父图接线（2026-11-10 已实现，旧 UI 尚未切换）

### 15.1 独立入口

`src/parent_graph.py` 提供 `create_parent_graph()`，使用 ParentState：

```text
START → initialize → planner → supervisor → composer → END
             │           └─ needs_clarification / failed → composer
             └─ 输入无效 → composer
```

```python
from src.parent_graph import create_parent_graph

graph = create_parent_graph()
state = graph.invoke({
    "user_query": "查询茅台股价，同时比较它和五粮液的估值",
    "conversation_context": "",
})
print(state["final_response"])
```

initialize 每次验证请求并重置本轮输出。无效输入转换为 planning_status=failed，
不调用模型或执行专家；规划失败 / 需要澄清时跳过 Supervisor，Composer 返回相应提示。
成功规划后通过适配节点执行已有 Supervisor，后者调度 market_data / report；
analytics / investment_strategy 仍 unsupported。

### 15.2 状态边界

父图只向 Supervisor 传入 plan / report_parameters，
只接回 task_results / supervisor_status / supervisor_error。
结果映射经过统一契约验证，并检查任务 ID、分类、问题和依赖与本轮计划一致；
成功或部分成功的执行必须具有完整任务结果集合。
边界异常返回 execution_error，不向用户泄漏原始异常。

messages、last_task_id、retry_count、current_phase 等局部字段不进入父级通道，
报告数据仅保留在对应任务 result，不变成父级 final_report。
Composer 输入类型同步为 ParentState，确保 LangGraph 不会过滤掉 planning_status。
当前不设置 checkpoint，不提供自动多轮存储；调用方显式提供对话摘要。

### 15.3 展示与兼容性

graph.stream(..., subgraphs=True) 可观察规划、内部执行、逐任务结果与汇总事件。
报告正文仍隐藏；原报告节点与四节点结果展示规则不变。
`src/agent.py`、`create_response_graph()` 与 Streamlit 旧入口继续保留，
本轮仅新增可独立调用的完整父图，不自动将浏览器页面切换到新流程。
下一步单独迁移入口 / UI，并同步旧 Reactive 和 C8–C9 的替换策略。

测试使用 mock 模型和子图，覆盖完整请求、上下文传递、混合任务部分成功、
无效输入、澄清、规划失败、报告隔离、过期结果重置、图复用及嵌套流式事件。
未运行真实行情或模型 API 的集成评估。


## 16. 公共入口与 UI 迁移完成（2026-11-10）

### 16.1 入口和旧编排删除

`src/agent.py` 仅保留公共门面：create_invest_agent() 创建新父图，
run_invest_agent(user_query, *, conversation_context="", report_parameters=None, config=None)
返回 ParentState。不再接受 thread_id 或全局报告主题/行业/时间参数。
旧 assess_query、reactive_agent、should_continue_tools、extract_reactive_response、
route_after_assess 和 MemorySaver 编排已删除。报告 validator 路由仍位于 report_graph.py。
报告子图内部节点函数、提示、调用与校验行为未改。

### 16.2 会话与返回结构迁移

公共返回不再含顶层 processing_mode、messages 或 final_report。
调用方从 plan、task_results、planning/supervisor/composition 状态和 final_response 读取结果。
报告四字段与完整报告仍保留在对应 report 任务 result 内。
不把 RunnableConfig 中的 thread_id 当作记忆，不调用 get_state()。
Streamlit 显式拼接最近三轮问题及回答摘要作为 conversation_context，
每条问题上限800字符、回答摘要上限1200字符；仅保留在 session_state 中。
新对话清空摘要、结果与进度，页面更新时清除旧版状态结构。

### 16.3 UI 与流式状态

UI 消费 stream_mode=[updates, custom]、subgraphs=True 的父图事件。
只将根更新写入父级快照，嵌套 task_results 用于提前显示结果；
不将子图 messages 或内部 current_phase 合并到父状态。
Supervisor 发出 task_started(task_id, category)，UI 依此将四个报告节点字段分组。
本机制面向当前顺序执行；未来并行必须给每项内部事件提供独立 task_id，不能复用单一活动任务变量。

页面展示任务 ID、类别、问题、依赖、状态；已返回的数据答案先展示，随后展示 Composer 回答。
报告四节点按任务分别显示，最终报告正文、下载、评估仍隐藏。
partial、failed、澄清与模型汇总 fallback 有显式提示；不再声称尚未接入 Supervisor。
分析与策略任务仍 unsupported。
移除未绑定任务的全局报告高级参数，要求用户把报告主题/行业/时间写入问题；
底层 report_parameters 仍供明确知道计划 task_id 的程序调用者使用。
精确的报告参数抽取仍待完善，不能因 UI 迁移宣称已解决。

### 16.4 规格和验证迁移

C8 更新为四类 TaskCategory 与有效计划，C9 更新为非空用户响应。
结构 lint 检查 TaskCategory；测试不再依赖旧 Reactive / MemorySaver 接口。
单元测试继续 mock API；集成测试改为新公共入口，明确报告请求并从任务结果取报告，
不再因旧路由不匹配而静默 skip。集成标记显式启用时才保留真实 API key，日常测试仍清除 key。
README、AGENTS、主规格和架构文档同步为当前运行方式。

测试覆盖入口代理、旧参数拒绝、会话摘要传递、混合/未接入状态、报告四字段隐藏策略、
多报告流式隔离、页面 rerun 不重复执行、新对话清空及真实父图结构驱动 UI（模型/工具 mock）。
本次未执行真实模型或行情 API 集成测试。


## 17. Market Data 输出兼容与失败可见性（2026-11-10）

针对页面仅显示任务失败、终端只有 Streamlit width 弃用提示的问题，修复：
- Market Data 最终输出接受完整 JSON Markdown 围栏，去围栏后仍严格 JSON 解析和 Pydantic 校验；
  不接受截断 JSON，也不放宽证据引用验证。
- 输出修正提示提供字段校验类型或错误原因及真实可用证据 ID，默认修正次数不变。
- Supervisor 保留经过 TaskError 校验的子图错误，Composer 和 UI 展示错误类型与说明；
  不把原始供应商异常或 API 密钥发送给前端。
- Streamlit 使用 width="stretch" 替代弃用参数，最低依赖相应更新为1.49。
这些提示本身不是数据请求失败的证据。历史运行没有保留具体错误，不能据此认定根因；
本轮验证仅基于 mock 复现的输出处理问题，不宣称真实行情调用已验证恢复。


## 18. Planner / Supervisor / Market Data 执行调试视图（2026-11-10）

Streamlit「执行记录」新增实时与完成后可查看的三个区域：
- Planner：完整任务计划、依赖、规划次数与状态/错误。
- Supervisor：任务开始、任务描述、依赖及其状态、结果收集时的终止状态与错误。
- Market Data：按 task_id 展示初始化输入、AI 最终文本与 tool_calls、工具参数与调用 ID、
  ToolMessage 原文、工具轮数/调用次数、输出修正提示及校验状态和结果摘要。

同一个 AIMessage 的多个 tool_calls 显示为同轮批次，便于区分并行候选调用与跨轮重复查询。
事件 received_at 为 UI 收到节点结果的时间，不用于宣称单工具执行起止或实际耗时。
这些是可观测模型输出与工具事件，不是模型隐藏推理。

调试记录独立存于本会话 debug_events，不写入 ParentState、对话摘要或数据库；
新对话清空，不因 rerun 再调用模型。只序列化白名单消息字段，不展示系统 prompt、
供应商元数据和配置；报告正文仍隐藏。当前调度顺序执行，task_id 关联沿用 task_started。


## 19. 证据 ID 修正不再重复查数（2026-11-10）

实际调试记录显示，同轮已查询两只股票，随后模型编造 evidence_ids，
校验修正时又调用相同工具，造成额外一轮行情查询。

工具节点现在在完整 ToolMessage 批次后追加显式证据 ID 清单，要求逐字引用，
数据足够时直接回答；原 ToolMessage 内容及 ID 保持不变。
output_retries>0 时模型不再绑定工具，修正提示要求只修复已有 JSON / 引用；
即使模型仍返回 tool_calls，也返回 invalid_output，不执行新查询。
正常研究阶段仍允许根据缺失数据继续调用工具，未新增跨轮缓存或强制去重。
证据引用校验和修正次数上限不变，不自动把未知引用替换成所有证据。

mock 测试覆盖清单传递、修正时不绑定工具及阻断重复查询；
本轮没有真实 API 延迟基准，不能将日志中的可避免时间视为固定加速保证。


## 20. Analytics 分步建设开始（2026-11-12）

已确认定量分析工具及与 Market Data / Strategy 的按需依赖关系，见 [Analytics 实施规格](analytics-agent.md)。
步骤1数据契约与请求内存储已实现，步骤2结构化采集待实施。父图调度及报告内部保持不变。


## 21. 历史日线数据采集与引用交接（2026-11-12）

Analytics 步骤2的股票/指数历史价格已接入 Market Data：请求内 DatasetStore、真实注册引用、
JSON-safe 元数据及 UI 展示。原报告工具列表与节点不改，Analytics 仍未接入。
详细接口、单位、范围与生命周期限制见 [Analytics 实施规格](analytics-agent.md)。


## 22. V1 表现/基准计算工具（2026-11-12）

analyze_price_performance 与 compare_with_benchmark 已独立实现，指标与图表序列保存为请求内分析产物。
详见 [Analytics 实施规格](analytics-agent.md)。尚未接入 Agent / Supervisor / UI，Analytics 仍 unsupported。


## 23. V1 小目录因子与估值链路（2026-11-12）

新增 compute_factors、get_valuation_snapshot、compare_valuations；估值指标增加 basis 元数据，
AnalysisArtifact 增加比较表。Market Data 可收集真实注册估值引用；Analytics Agent 仍待建设，
报告内部保持不变。公式、来源、可比性与限制见 [Analytics 实施规格](analytics-agent.md)。


## 24. 独立 Analytics 子图（2026-11-12）

四工具的局部 ReAct 子图、输入/产物范围验证、有界执行与缺失数据要求已实现。
数值和图表引用取自实际 AnalysisStore，输出修正不重新计算。
详见 [Analytics 实施规格](analytics-agent.md) 步骤4–5。尚未接入 Supervisor/UI，报告内部未改。


## 25. Analytics 完成与未完成状态核对（2026-11-12）

[Analytics实施规格](analytics-agent.md) 顶部维护当前状态清单及设计原则落实情况。
独立四工具/数据层/子图已完成，父级调度、产物交接、分析汇总、图表与methodology skill未完成。
明确区分“产物可绘图”与“已接UI”、“比较工具支持字段”与“已采集字段”。
当前不需要无风险利率，独立协方差矩阵未提供，真实模型/API端到端验证未执行。
本次仅同步文档，未改变运行状态。


## 26. Analytics 方法型 skill 接入（2026-11-12）

已创建 research_skills/analytics-methodology/SKILL.md，独立 Analytics 子图在有效请求初始化时固定加载到系统上下文。
工具选择、解释和缺失处理由方法指导，公式/权限/预算仍由代码控制；文件缺失明确失败。
状态及部署/测试边界见 [Analytics实施规格](analytics-agent.md)。父级调度与UI尚未接入，报告不改。


## 27. Analytics 调度与共享引用接入（2026-11-12）

父图/已有计划执行图按请求注入DatasetStore和AnalysisStore；Supervisor已调度Analytics，
仅传显式前置任务的canonical引用，并从实际存储重建数值产物包装TaskResult。
Strategy仍unsupported。Planner的数据依赖细化、Composer分析消费及图表UI仍未完成。
详见 [Analytics实施规格](analytics-agent.md) 步骤6；报告内部未改。


## 28. Planner 分析数据依赖与 Composer 分析回答（2026-11-12）

Planner补充价格/基准/估值采集规划规则、当前日期和可选analytics_parameters，
生成计划须具备Analytics直接数据依赖；Supervisor传递结构化分析参数。
Composer消费实际分析指标、单位、表格、假设、来源和缺失要求，模型失败时确定性保留。
报告正文仍隐藏，图表UI未实现。详细契约/验证边界见 [Analytics实施规格](analytics-agent.md) 步骤7a。


## 29. 分析看板与 Plotly 首版（2026-11-12）

「分析与策略」页新增指标卡、结果表、累计收益/回撤/基准/因子曲线和可比估值柱状图。
只展示确定性计算产物，显示来源、模式、假设与缺失限制。
Supervisor 通过 custom event 交接已引用产物，UI 保存当前会话最近请求快照；
完整序列不进入父图状态或 Composer。重绘不重新执行，新请求替换，新对话清空。
无快照时保留已有指标并提示，不伪造曲线。报告内部与阶段输出保持，正文仍隐藏。
详见 [Analytics 实施规格](analytics-agent.md) 步骤7b。


## 行情回退与估值引用执行修正（2026-11-12）

真实复现东方财富 stock_zh_a_hist 返回 Push2RateLimitError，而新浪 stock_zh_a_daily 可返回同区间日线。
结构化个股历史采集在东方财富异常或空结果时回退新浪，保留请求区间与复权；新浪成交量已为股，
不再乘100，来源及链接记录实际供应商。指数路径不变，不回退模拟数据。
失败只暴露异常类名，不返回可能含敏感内容的原始异常文本。数据验证失败仍不注册数据集。

Analytics 明确 dataset_refs 是引用，pe_ttm/pb 是字段，PE_TTM/PB_MRQ 是口径。
估值任务仅持有2–20个估值快照、无既有产物、未调用工具而直接回答时，节点补发一次
compare_valuations 默认比较，以实际工具结果决定可比性；仍遵守数据范围和工具预算。
该保护不影响已有工具选择、输出修复或价格分析路径。工具返回后不重复补发。
报告子图内部保持不变。回归测试隔离真实API；真实接口探测单独执行。
