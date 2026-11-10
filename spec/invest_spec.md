# InvestAgent — 规格文档 (Specification)

> 本文档是项目的"一等公民"。所有实现代码都是本规格的可执行表达。
> 修改本文档时必须同步更新对应的测试和实现。

---

## 当前运行架构（2026-11-10）

公共入口和 Streamlit 已切换为请求级父图：

```text
用户输入 + 显式会话摘要
  → initialize → Planner → Supervisor → Composer → final_response
                     │        ├─ market_data 子图（LLM / ToolNode 循环）
                     │        ├─ report 子图（原六节点保持不变）
                     │        └─ analytics / investment_strategy：unsupported
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
