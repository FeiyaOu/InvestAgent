# InvestAgent — 规格文档 (Specification)

> 本文档是项目的"一等公民"。所有实现代码都是本规格的可执行表达。
> 修改本文档时必须同步更新对应的测试和实现。

---

## 功能目标

输入一个研究主题（如"新能源行业"）和行业焦点（如"光伏"），
InvestAgent 自动判断查询复杂度并选择执行路径：

- **Reactive 路径**：简单市场查询，调用 AKShare 工具快速回答
- **Deliberative 路径**：复杂研究请求，经过5个专家角色依次处理，生成结构化投研报告

---

## 系统架构

```
用户输入（研究主题 / 简单问题）
        ↓
   [assess]          -- 协调层：判断 processing_mode
        ↓
   ┌────┴────┐
reactive   deliberative
   ↓              ↓
[reactive_agent]  [perception]    -- 市场数据分析师：AKShare 数据收集
  ↕ 环①              ↓
[tools]           [modeling]      -- 宏观经济学家：构建市场内部模型
   ↓                  ↓
[extract_resp]    [reasoning]     -- 策略研究员：生成3个候选投资方案
   ↓                  ↓
  END            [decision]       -- 投资委员会主席：选择最优方案
                      ↓
                  [report]        -- 报告撰写专家：生成结构化 JSON 报告
                      ↓
                  [validator]     -- 合规审查员：校验 C1–C7
                   ↕ 环②
                      ↓（合格 → END，不合格 → decision，最多重试2次）
                     END
```

**依赖方向：** `tools ← perception ← modeling ← reasoning ← decision ← reporter ← validator`

禁止反向依赖（validator 不能 import perception）。

---

## Reactive 路径工具清单

| 工具函数 | 数据来源 | 描述 |
|---|---|---|
| `get_sector_performance(sector)` | AKShare `stock_board_industry_summary_ths()` | 查询指定行业板块涨跌幅、成交额、主力净流入 |
| `get_index_performance()` | AKShare `index_zh_a_hist()` | 查询主要指数（上证、创业板）近期行情 |
| `get_macro_indicators()` | AKShare `macro_china_pmi_yearly()` | 查询 PMI、GDP 等宏观经济指标 |
| `search_stock_news(keyword)` | AKShare `stock_news_em()` | 查询与关键词相关的市场新闻 |

所有工具必须包含 `try/except` fallback，网络异常时返回提示文本而非抛出异常。
环境变量 `USE_REAL_DATA=false` 时返回预设 mock 数据，用于测试和离线演示。

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

### 适用于两条路径（路由行为约束）

#### C8：路由有效值
- `processing_mode` 只能是 `reactive` 或 `deliberative`
- `assess` 节点输出其他值视为路由错误
- 默认回退值为 `reactive`

#### C9：Reactive 路径响应完整性
- 当 `processing_mode == reactive` 时，`final_response` 必须是**非空字符串**
- 空字符串或 `None` 说明 reactive 路径未成功生成回答

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

`src/agent.py` 必须定义以下常量：

```python
VALID_PROCESSING_MODES = {"reactive", "deliberative"}
MAX_VALIDATOR_RETRIES = 2
```

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

每个 Deliberative 阶段的 LLM 输出必须通过对应的 Pydantic 模型验证：

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
