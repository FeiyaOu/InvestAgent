# InvestAgent — 规格文档 (Specification)

> 本文档是项目的"一等公民"。所有实现代码都是本规格的可执行表达。
> 修改本文档时必须同步更新对应的测试和实现。

---

## 当前运行架构（2026-11-13）

公共入口和 Streamlit 已切换为请求级父图：

```text
用户输入 + 显式会话摘要
  → initialize → Planner → Supervisor → Composer → final_response
                     │        ├─ market_data 子图（LLM / ToolNode 循环）
                     │        ├─ report 子图（原六节点保持不变）
                     │        ├─ analytics 子图（计算与图表）
                     │        └─ investment_strategy 子图（V1约束/压力测试）
                     └─ 澄清或失败 → Composer，不执行专家
```

任务按能力与产物分类，不按整条消息复杂度二选一；只有明确报告请求产生 report 任务。
父级采用 ParentState，task_results 按 task_id 保存统一 TaskResult；
报告 final_report、四节点输出均在对应任务 result 内，父级不提供顶层 processing_mode / final_report。
原 assess_query、Reactive 工具循环和回答提取节点已删除。
报告内部工具、节点、提示和重试行为保持不变，C1–C7 不变。

完整接口与演进见 [工作流演进规格](workflow-evolution.md) 第 8–16 节。
历史阶段描述若与本文冲突，以当前规格及演进规格第 16 节为准。

## 公共入口与会话

- `create_invest_agent()` 返回 `create_parent_graph()`，不设置 checkpointer。
- `run_invest_agent(user_query, *, conversation_context="", report_parameters=None, config=None)`
  返回 ParentState；不再接受 thread_id 或全局 research_topic / industry_focus / time_horizon。
- report_parameters 可按已知报告 task_id 指定参数；尚无任务 ID 时应将主题、行业和时间写入问题。
- config 供追踪 callbacks / tags 使用，传入 thread_id 不会创建自动记忆。
- Streamlit 只在本会话内保存历史，每次传入最近三轮的用户问题及回答摘要。
  每轮问题截取800字符、回答截取1200字符；不是模型生成的长期摘要，也不是持久化。
- 刷新或服务重启后可能丢失会话；「新对话」清空本地摘要与结果。

## 展示与流式事件

页面展示任务分类、依赖、终止状态、数据证据与回答。
任务完成即可展示，模型汇总随后返回；不把 partial 或 unsupported 冒充完全成功。
报告四字段 perception_data / world_model / reasoning_plans / selected_plan 按报告任务分别显示。
最终报告正文、下载与评估继续隐藏，后端仍生成和校验报告。
Supervisor 发出 task_started 自定义事件标识 task_id/category，供顺序执行时关联内部节点事件。
子图消息不写入父状态，UI 不使用 get_state() 或 MemorySaver。

## 工具与数据边界

Market Data 首版复用 src/tools.py 的五个工具（行业、指数、宏观、新闻、个股）。
AKShare 访问只在工具层，异常必须 fallback；模拟模式必须明确标记。
历史价格、财务与量化扩展仍以演进规格为准，不因 UI 迁移自动新增。

---

## Deliberative 路径输出格式

Deliberative 路径的最终输出必须严格遵循以下 JSON 结构：

```json
{
  "research_topic": "新能源行业",
  "industry_focus": "光伏",
  "time_horizon": "中期",
  "report_date": "2026-07-07",
  "dimensions": {
    "fundamental": {
      "summary": "不少于100字的基本面分析...",
      "confidence": 0.85
    },
    "market": {
      "summary": "不少于100字的市场面分析...",
      "confidence": 0.78
    },
    "news": {
      "summary": "不少于100字的消息面分析...",
      "confidence": 0.72
    },
    "analyst": {
      "summary": "不少于100字的分析师观点...",
      "confidence": 0.80
    }
  },
  "investment_thesis": "经过多方案推理后选定的核心投资逻辑，不少于50字...",
  "supporting_evidence": ["支撑证据1", "支撑证据2", "支撑证据3"],
  "overall_rating": "buy",
  "risk_factors": ["风险因素1", "风险因素2"],
  "sources": ["https://...", "https://...", "https://..."]
}
```

---

## 约束条件（Constraints）

以下约束条件将直接转化为测试用例和 linter 规则。

### 适用于 Deliberative 路径（`validate_report()` 执行）

#### C1：维度完整性
- 报告必须包含全部4个维度：`fundamental`、`market`、`news`、`analyst`
- 缺少任何一个维度视为报告不合格

#### C2：摘要最小长度
- 每个维度的 `summary` 字段不少于 **100 个字符**
- 空摘要或过短摘要说明数据采集或推理不充分

#### C3：置信度范围
- 每个维度的 `confidence` 必须在 **[0.0, 1.0]** 闭区间内
- 超出范围说明评分逻辑有误

#### C4：评级有效值
- `overall_rating` 只能取 **`buy`**、**`hold`**、**`sell`** 三个值之一
- 其他值（如 `strong_buy`、`neutral`）不被接受

#### C5：来源数量
- `sources` 列表必须包含至少 **3 个**来源
- 来源过少说明研究深度不够

#### C6：风险因素
- `risk_factors` 列表不能为空
- 任何投资都有风险，空列表说明分析不完整

#### C7：投资论点（Deliberative 路径核心产出）
- `investment_thesis` 不少于 **50 个字符**
- 这是深思熟虑型 Agent 经过多方案推理后的核心产出
- 过短说明 decision 阶段未进行有效推理

---

### 适用于父图的任务与响应约束

#### C8：任务类别与计划有效性

- category 只能为 market_data / analytics / investment_strategy / report。
- TaskPlan 拒绝重复 ID、未知/重复/自依赖、有向环与状态矛盾；失败计划不得执行。
- 旧 processing_mode 合法性约束退出公共接口，仅报告局部 State 保留兼容字段。

#### C9：用户响应完整性

- 对公共入口可处理的请求（包括规划失败、澄清、能力未接入和局部失败），
  final_response 必须为非空字符串。
- 回答不隐瞒失败、缺失信息或 unsupported；模型汇总失败时保留确定性结果。
- 此要求不代表进程中断、调用方主动取消等外部故障也能保证生成响应。

---

## 约束常量（代码中必须定义）

`src/stages/reporter.py` 必须定义以下常量，供 `validate_report()` 和 linter 使用：

```python
REQUIRED_DIMENSIONS = ["fundamental", "market", "news", "analyst"]
VALID_RATINGS = {"buy", "hold", "sell"}
MIN_SUMMARY_LENGTH = 100
MIN_SOURCES = 3
MIN_THESIS_LENGTH = 50
```

`src/planner_schemas.py` 定义四类 `TaskCategory` Literal；
`src/state.py` 的 MAX_VALIDATOR_RETRIES=2 只属于报告子图。

---

## validate_report() 接口规范

`src/stages/reporter.py` 中的 `validate_report()` 是**唯一的报告校验入口**：

```python
def validate_report(report: dict) -> list[dict]:
    """
    校验报告是否满足 C1–C7。

    返回错误列表，空列表表示校验通过。
    每个错误包含：
      - type: 错误类型（字符串标识符）
      - detail: 错误详情（人类可读）
      - fix: 修复指令（AI Agent 可直接执行）
    """
```

错误类型标识符：

| type | 对应约束 |
|---|---|
| `missing_dimension` | C1 |
| `summary_too_short` | C2 |
| `confidence_out_of_range` | C3 |
| `missing_confidence` | C3 |
| `invalid_rating` | C4 |
| `insufficient_sources` | C5 |
| `empty_risk_factors` | C6 |
| `thesis_too_short` | C7 |

---

## Pydantic 阶段输出模型

报告阶段模型定义如下。历史阶段链仍按原实现使用 JSON 解析，并未全部调用这些模型；
本轮不修改报告内部验证路径。新 Planner / Market Data / TaskResult / Composer 已在各自边界使用 Pydantic：

| 阶段 | 模型类 | 关键字段 |
|---|---|---|
| perception | `PerceptionOutput` | `market_overview`, `key_indicators`, `recent_news`, `industry_trends` |
| modeling | `ModelingOutput` | `market_state`, `economic_cycle`, `risk_factors`, `opportunity_areas`, `market_sentiment` |
| reasoning | `List[ReasoningPlan]` | `plan_id`, `hypothesis`, `confidence_level`, `pros`, `cons` |
| decision | `DecisionOutput` | `selected_plan_id`, `investment_thesis`, `supporting_evidence`, `recommendation` |
| report | `FinalReport` | 完整 JSON 报告结构（见上方输出格式）|

---

## 开发约定

1. **TDD 强制**：所有新功能必须先写失败的测试，再写实现
2. **Spec 同步**：修改报告结构或约束时必须同步更新本文档
3. **测试隔离**：单元测试禁止调用真实 API（`DASHSCOPE_API_KEY` 和 AKShare 均须 mock）
4. **结构对称**：`src/stages/` 下每个模块对应 `tests/` 下的测试
5. **单一校验入口**：报告校验只通过 `validate_report()`，不在其他地方散落校验逻辑
6. **Fallback 必须**：所有 AKShare 调用必须有 `try/except`，网络异常不得导致 Agent 崩溃

---

## 测试命令

```bash
pytest tests/ -q                              # 全部单元测试
pytest tests/test_reporter.py -v              # C1–C7 约束测试
pytest tests/test_agent.py -v                 # C8–C9 路由测试
pytest tests/ -m integration                  # 集成测试（需 DASHSCOPE_API_KEY）
python linters/check_agent_structure.py       # 结构 lint 检查
```


## Analytics 建设进展（2026-11-12）

已完成数据契约、请求内存储、结构化价格/估值快照采集、四个V1计算工具和独立Analytics子图。
analytics-methodology运行时skill已创建并固定加载；Supervisor调度/引用交接及父图双Store注入已完成；Planner数据依赖首版与Composer分析汇总已完成；Plotly 分析看板首版已完成（当前会话最近请求快照）。
父图analytics已启用；未执行真实模型/API端到端评估。
完整状态、无风险利率适用范围、样本不足及协方差产物边界见 [Analytics实施规格](analytics-agent.md)。

Planner计划现在检查Analytics的直接数据依赖，并支持可选analytics_parameters；Composer展示分析指标、假设和限制，见Analytics规格步骤7a。


## Planner 校验可观测性与输出约束计划（2026-11-13）

已确认、待实现：统一字段级Pydantic诊断和逐次重试UI展示；减少模型生成的固定假设字段，
代码补齐默认策略；验证当前模型提供方支持后再迁移结构化输出，并评估前后失败率。
不改变报告C1–C9或取消运行时业务校验。详见[演进规格中的问题与修复计划](workflow-evolution.md#planner-校验问题识别与改进计划2026-11-13)。


Planner诊断交付状态（2026-11-13）：阶段一首版完成，Planner字段级错误及逐次尝试事件已接UI。
仅保留安全类型/约束元信息，输入值预览省略；阶段二输出简化及阶段三结构化迁移仍为计划。


Planner阶段二、三首版状态（2026-11-13）：固定missing_data不再要求模型输出，代码补齐；
已核实ChatTongyi使用function calling并迁移默认模式，保留PLANNER_OUTPUT_MODE=json。
真实小样本各3/3首次校验通过，不等于稳定性改善或端到端语义验收。运行时契约/C1–C9不变。


## Investment Strategy/Risk 后续范围（2026-11-13）

已确认、尚未实现：V1先做风险约束检查与简单价格冲击压力测试；估值情景须先补盈利数据契约。
V2评估组合优化、风险预算/风险平价、HRP与Black-Litterman。保持数据采集与Analytics职责分离，
不变更报告C1–C9。详见[Strategy/Risk专题规格](investment-strategy-agent.md)。


Strategy/Risk State方案（2026-11-13，已确认/待实现）：独立StrategyState，授权引用输入，
可选持仓与显式用户约束/情景，规范结果经TaskResult交接；不继承父图完整状态，不信任LLM数值。
详细字段及状态语义见[Strategy/Risk专题规格](investment-strategy-agent.md)。报告C1–C9保持不变。


## Strategy/Risk V1 实施交付（2026-11-13）

原先unsupported状态由本节覆盖：独立StrategyState/StrategyStore、两个确定性工具及有界ToolNode子图已接入。
Planner strategy_parameters保留显式持仓/用户限制/情景，Supervisor仅交接直接数据依赖，
父图与response_graph注入请求级策略存储，Composer/Streamlit展示规范结果和执行记录。
数值从任务作用域内产物重建；报告C1–C9与内部节点未改。
实施步骤与边界见[开发规格](strategy-agent-development.md)，契约见[专题规格](investment-strategy-agent.md)。


Strategy回撤检查失败保护（2026-11-13）：有规范计算产物时解释失败降为partial并保留计算结果；
无产物的技术失败仍failed。具体安全错误码与字段诊断进入执行记录。Strategy任务失败时Composer不代做约束判断，
直接展示已有任务结果。详见Strategy专题的回撤约束链路失败保护记录，报告C1–C9不变。


Strategy工具适用性（2026-11-13）：无约束/无情景的解释不绑定工具；V1已有工具由显式输入确定并经ToolNode执行。
意外工具请求记录诊断、拒绝执行并使用既有有界输出修正，不取消授权检查。报告C1–C9不变。


Strategy解释模型输出简化（2026-11-13）：模型schema移除artifact_ids，执行产物由代码选取；
上游analysis引用仍经evidence_ids授权校验。引用错误提供字段诊断与分类可用ID清单，不放宽范围检查。
详见Strategy专题的引用字段混淆复现记录，报告C1–C9不变。

策略产品场景与工具扩展讨论归档（2026-11-13）：见[Strategy用户问题与扩展参考](strategy-user-questions-and-expansion.md)，
包含六类问题、当前覆盖、基本面/公告/估值情景的建议优先级及未来验收样例；非新增实现承诺。

Strategy已知缺陷状态更正（2026-11-13）：用户复测纯策略解释invalid_output仍存在，未解决，按用户要求暂缓。
本地测试/模型抽样不替代该真实链路验收。已有修正保留，后续再处理；见[专题问题记录](investment-strategy-agent.md#未解决问题纯策略解释-invalid_output2026-11-13)。


## 报告阅读与下载首版（2026-11-13）

用户确认先做生成后立即阅读/下载：Streamlit新增报告阅读页签与Markdown/HTML下载，
节点输出保持。覆盖此前“最终报告正文及下载隐藏”的当前UI策略，报告生成与C1–C9不变。
会话最近结果复用，不重跑LLM，不提供长期链接或持久化。
分享链接、外部存储、权限、PDF与云端部署作为后续扩展，详见[报告交付规格](report-delivery.md)。


明确报告意图规则（2026-11-13）：当前原文明确生成投研报告的ready计划须包含report；
明确拒绝报告不得生成report。有限措辞校验错误进入Planner有界修正，修正失败不执行错误计划。
不要求额外的“完整”关键词，不改变报告C1–C9或报告内部流程，详见工作流演进的报告意图记录。
