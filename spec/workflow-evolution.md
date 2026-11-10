# 工作流演进规格：保留报告流程，独立建设专家 Agent

- 决策日期：2026-11-10
- 状态：方案已确认；报告子图已封装并接入原双路径入口，目标 Planner / Supervisor 父图整合尚未实现。
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
