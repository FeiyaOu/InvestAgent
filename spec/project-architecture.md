# InvestAgent — 项目架构文档

> 本文档是项目的架构权威来源。所有实现决策、技术选型、功能边界均以此为准。
> 修改架构前必须先更新本文档。

---

## 1. 项目定位

**项目名称：** InvestAgent — 混合型智能投研助手

**一句话描述：**

> 输入研究主题（如"新能源行业"），Agent 自动判断查询复杂度：简单问题走 Reactive 路径调用 AKShare 工具快速回答；复杂研究走 Deliberative 路径，由5个专家角色依次完成感知→建模→推理→决策→报告，最终生成结构化投研报告，全程由 Pydantic 约束保护，LangFuse 追踪每个阶段的 LLM 调用。

**与 PolicyPilot-RAG 的关系：**

- PolicyPilot-RAG = 解决「RAG 检索质量」问题（文档 → 召回 → 生成）
- InvestAgent = 解决「Agent 自主规划」问题（感知 → 推理 → 决策）
- 两个项目互补，PolicyPilot 的 hybrid retrieval 可以被封装成 InvestAgent 的一个 `@tool`

---

## 2. 核心架构

### 2.1 LangGraph Graph 结构

```
用户输入（研究主题 / 简单问题）
        ↓
   [assess] ── LLM 判断 processing_mode
        ↓
   ┌────┴────┐
reactive   deliberative
   ↓              ↓
[reactive_agent]  [perception]  ← AKShare 工具调用
    ↕ 有向环①         ↓
[tools(AKShare)]  [modeling]
    ↓              ↓
[extract_resp]  [reasoning]    ← 生成3个候选方案
    ↓              ↓
   END          [decision]     ← 选择最优方案
                   ↓
                [report]       ← 生成结构化报告
                   ↓
               [validator]     ← 校验 C1–C8
                ↕ 有向环②
                   ↓（不合格 → 回到 decision，最多重试2次）
                  END
```

### 2.2 两个有向环

| 有向环 | 节点路径 | 实现机制 | LangChain LCEL 能做吗 |
|---|---|---|---|
| 环① | `reactive_agent → tools → reactive_agent` | `add_messages` reducer + `should_continue_tools` 条件路由 | ❌ LCEL 是 DAG |
| 环② | `validator → decision → report → validator` | state 中 `validation_passed` 字段 + 条件边，`retry_count` 防无限循环 | ❌ LCEL 是 DAG |

### 2.3 为什么必须用 LangGraph（不是 LangChain）

| 需求 | LangChain LCEL | LangGraph |
|---|---|---|
| 有向环（工具调用循环、validator 重试）| ❌ DAG，禁止环路 | ✅ 原生支持 |
| `add_messages` 追加语义 | ❌ 总是覆盖赋值 | ✅ Reducer 声明在 TypedDict 里 |
| 图结构级别条件路由（可视化、可追踪）| ❌ `RunnableBranch` 是代码 if-else | ✅ `add_conditional_edges`，Mermaid 可画 |
| 两条异构路径共享同一 State | ❌ 需要手动传参 | ✅ 所有节点共享 `InvestAgentState` |

---

## 3. State 设计

```python
class InvestAgentState(TypedDict):
    # 输入
    user_query: str
    research_topic: str
    industry_focus: str
    time_horizon: str

    # Reactive 路径
    query_type: Optional[Literal["simple", "analytical"]]
    processing_mode: Optional[Literal["reactive", "deliberative"]]
    messages: Annotated[List[BaseMessage], add_messages]   # 工具调用历史，追加语义

    # Deliberative 路径 — 5阶段累积
    perception_data: Optional[dict]     # 阶段1写入
    world_model: Optional[dict]         # 阶段2写入，读阶段1
    reasoning_plans: Optional[list]     # 阶段3写入（3个候选方案），读阶段1+2
    selected_plan: Optional[dict]       # 阶段4写入，读阶段1+2+3
    final_report: Optional[str]         # 阶段5写入，读全部

    # 质量控制
    validation_errors: Optional[list]   # validator 节点写入
    retry_count: int                    # 防止无限循环，最多重试2次

    # 控制流
    current_phase: str
    error: Optional[str]
```

**关键设计说明：**
- `messages` 使用 `add_messages` reducer，是 LangGraph 专有语义，每次节点更新都追加而非覆盖，这是工具调用环路能工作的基础
- `perception_data` 等字段是普通赋值（每阶段只写一次），`messages` 是例外
- `retry_count` 防止 validator 环②无限循环，上限为2次

---

## 4. 角色 Persona 设计（Hat System）

每个 Deliberative 阶段节点都有明确的专家角色，通过 system prompt 传入：

| 节点 | 角色 | System Prompt 要点 |
|---|---|---|
| `perception` | 市场数据分析师 | 专注多维度数据收集，调用工具获取真实数据，不做主观判断 |
| `modeling` | 宏观经济学家 | 从感知数据构建市场内部模型，识别周期位置和结构性变化 |
| `reasoning` | 策略研究员 | 生成3个有明显差异的投资假设，每个标注置信度和优缺点 |
| `decision` | 投资委员会主席 | 评估3个方案，选择最优，给出可追溯的 investment_thesis |
| `report` | 资深研究报告撰写专家 | 生成结构化 JSON 报告，语言专业，有数据支撑，格式严格遵循 Spec |
| `validator` | 独立合规审查员 | 不知道其他节点的决策过程，独立校验报告是否满足 C1–C8 |

---

## 5. Spec 约束 C1–C9

`spec/invest_spec.md` 是项目的"一等公民"。每条约束直接映射到一个测试类。

混合型架构有两条路径，约束按适用范围分组：

**Deliberative 路径专属（校验最终 JSON 报告，在 `validate_report()` 中执行）：**

| 编号 | 约束内容 | 对应测试类 |
|---|---|---|
| C1 | 报告必须包含全部4个 dimensions：fundamental / market / news / analyst | `TestC1DimensionCompleteness` |
| C2 | 每个 `dimension.summary` 不少于100字符 | `TestC2SummaryLength` |
| C3 | 每个 `dimension.confidence` 在 [0.0, 1.0] 闭区间内 | `TestC3ConfidenceRange` |
| C4 | `overall_rating` 只能是 `buy` / `hold` / `sell` 之一 | `TestC4RatingValidValue` |
| C5 | `sources` 列表不少于3项 | `TestC5SourceCount` |
| C6 | `risk_factors` 列表不能为空 | `TestC6RiskFactors` |
| C7 | `investment_thesis` 不少于50字符（深思熟虑型的核心产出）| `TestC7InvestmentThesis` |

**两条路径均适用（校验路由行为和各路径输出完整性）：**

| 编号 | 约束内容 | 适用路径 | 对应测试类 |
|---|---|---|---|
| C8 | `processing_mode` 必须是 `reactive` 或 `deliberative`，不允许其他值 | 两条路径 | `TestC8RoutingValidValue` |
| C9 | `processing_mode == reactive` 时，`final_response` 必须是非空字符串 | Reactive only | `TestC9ReactiveResponse` |

**测试类分布：**
- `tests/test_reporter.py`：C1–C7（deliberative 路径的 `validate_report()` 逐条校验）
- `tests/test_agent.py`：C8–C9（路由行为和 reactive 输出完整性）

**最终报告 JSON 格式：**

```json
{
  "research_topic": "新能源行业",
  "industry_focus": "光伏",
  "time_horizon": "中期",
  "report_date": "2026-07-07",
  "dimensions": {
    "fundamental": { "summary": "...(>=100字)", "confidence": 0.85 },
    "market":      { "summary": "...(>=100字)", "confidence": 0.78 },
    "news":        { "summary": "...(>=100字)", "confidence": 0.72 },
    "analyst":     { "summary": "...(>=100字)", "confidence": 0.80 }
  },
  "investment_thesis": "选定的核心投资逻辑...(>=50字)",
  "supporting_evidence": ["证据1", "证据2", "证据3"],
  "overall_rating": "buy",
  "risk_factors": ["风险1", "风险2"],
  "sources": ["url1", "url2", "url3"]
}
```

---

## 6. 数据层设计

### 6.1 AKShare 使用范围

AKShare 是免费、无需 API key 的 A 股数据库，**只放在 Tools 层**：

```
AKShare 调用范围：
  ✅ reactive 路径的 @tool 函数（工具调用环路内）
  ✅ deliberative 路径的 perception 阶段（调用同一套工具）
  ❌ modeling / reasoning / decision / report（纯 LLM 推理，不需要外部数据）
```

数据收集与分析推理分离，是正确的分层设计。如需替换数据源（如接入 Wind、Tushare），只需修改 `src/tools.py`，Agent 架构不变。

### 6.2 工具函数清单

| 函数 | AKShare 接口 | 返回数据 |
|---|---|---|
| `get_sector_performance(sector)` | `stock_board_industry_summary_ths()` | 行业涨跌幅、成交额、主力净流入 |
| `get_index_performance()` | `index_zh_a_hist()` | 主要指数近期行情 |
| `get_macro_indicators()` | `macro_china_pmi_yearly()` | PMI、GDP 等宏观数据 |
| `search_stock_news(keyword)` | `stock_news_em()` | 相关市场新闻 |

### 6.3 Fallback 与开关策略

```python
USE_REAL_DATA = os.getenv("USE_REAL_DATA", "true").lower() == "true"

@tool
def get_sector_performance(sector: str) -> str:
    if not USE_REAL_DATA:
        return f"{sector} 板块模拟数据：涨跌幅 +2.3%，成交额 1200亿"
    try:
        # 真实 AKShare 调用
        ...
    except Exception as e:
        # 网络异常时不崩溃，让 Agent 继续基于已有信息推理
        return f"{sector} 数据暂时无法获取（{type(e).__name__}），请基于已有信息分析。"
```

**三种运行模式：**
- `USE_REAL_DATA=true`（默认）：调用真实 AKShare
- `USE_REAL_DATA=false`：返回预设 mock 数据（面试现场网络不稳时备用）
- 测试层：`monkeypatch` mock AKShare，保持单元测试零网络依赖

---

## 7. 外部依赖清单

| 依赖 | 用途 | 是否必须 | 费用 | 获取方式 |
|---|---|---|---|---|
| `DASHSCOPE_API_KEY` | Qwen LLM，驱动全部节点 | ✅ 必须 | 按 token 计费 | DashScope 控制台 |
| AKShare | 真实市场数据 | ⚠️ 可选（有 fallback）| 免费 | `pip install akshare`，无需 key |
| `LANGFUSE_*` | LLM 调用追踪 | ⚠️ 可选 | 免费 hobby tier | cloud.langfuse.com |
| `LANGSMITH_API_KEY` | 评估数据集管理 | ⚠️ 可选 | 免费 tier | smith.langchain.com |

**零数据库依赖：** 报告存为 `runtime/reports/YYYY-MM-DD_topic.json`，无需 RDS 或任何持久化服务。

---

## 8. 项目文件结构

```
InvestAgent/
├── AGENTS.md                           # ~50行，AI agent 导航入口（给 AI 和开发者看的地图）
├── pyproject.toml                      # pytest + ruff 配置
├── requirements.txt                    # langgraph, langchain, akshare, pydantic, dashscope
├── requirements-dev.txt                # pytest, pytest-mock, ruff
├── .env.example                        # 环境变量模板
├── .github/
│   └── workflows/
│       └── quality_gate.yml            # 三道门 CI：structure-lint → unit → integration
├── linters/
│   └── check_agent_structure.py        # ast检查：validate_report存在、REQUIRED_DIMENSIONS常量、stage节点
├── spec/
│   ├── project-architecture.md         # 本文档
│   └── invest_spec.md                  # 一等公民，C1–C8 完整约束 + 报告格式定义
├── src/
│   ├── __init__.py
│   ├── schemas.py                      # Pydantic models（5阶段输出 + FinalReport）
│   ├── tools.py                        # @tool 函数（AKShare 封装 + fallback + USE_REAL_DATA 开关）
│   ├── stages/
│   │   ├── __init__.py
│   │   ├── perception.py               # 阶段1：市场数据分析师角色
│   │   ├── modeling.py                 # 阶段2：宏观经济学家角色
│   │   ├── reasoning.py                # 阶段3：策略研究员角色（生成3个候选方案）
│   │   ├── decision.py                 # 阶段4：投资委员会主席角色
│   │   ├── reporter.py                 # 阶段5：报告撰写 + validate_report()（唯一校验入口）
│   │   └── validator.py                # 环②触发节点：校验不合格时路由回 decision
│   └── agent.py                        # LangGraph StateGraph 连线（全部节点 + 路由函数）
├── app/
│   └── streamlit_app.py                # Streamlit UI（输入 + 实时阶段进度 + 报告展示）
├── runtime/
│   └── reports/                        # 生成的 JSON 报告（无需数据库）
└── tests/
    ├── __init__.py
    ├── conftest.py                     # make_valid_report工厂、AKShare mock、API key 隔离 fixture
    ├── test_schemas.py                 # Pydantic 模型边界测试
    ├── test_reporter.py                # TestC1–TestC8，每个测试类对应一条 spec 约束
    ├── test_tools.py                   # 工具函数测试（mock AKShare，零网络依赖）
    ├── test_stages.py                  # 每个阶段函数单元测试（mock LLM 返回）
    ├── test_agent.py                   # graph 路由测试（reactive/deliberative 路径选择正确性）
    └── test_integration.py             # @pytest.mark.integration，需真实 DASHSCOPE_API_KEY
```

---

## 9. 测试策略

| 测试层 | 覆盖内容 | 隔离方式 |
|---|---|---|
| 单元测试 | `validate_report` C1–C8 逐条、Pydantic 模型边界、工具函数 fallback | `monkeypatch` 删除 API key env，mock AKShare |
| 路由测试 | `assess` 节点正确路由 reactive/deliberative，`validator` 节点正确触发重试 | mock LLM 返回固定 `processing_mode` 和固定报告 |
| 集成测试 | 完整5阶段流程 + 报告通过 C1–C8 校验 | `@pytest.mark.integration`，需真实 `DASHSCOPE_API_KEY` |

**测试命令：**
```bash
pytest tests/ -q                          # 全部单元测试
pytest tests/test_reporter.py -v          # 只跑 spec 约束测试
pytest tests/ -m integration              # 集成测试（需 API Key）
python linters/check_agent_structure.py   # 结构 lint 检查
```

---

## 10. 质量门（CI 三道门）

```
门1: structure-lint    python linters/check_agent_structure.py
        ↓ 通过
门2: unit-tests        pytest tests/ -m "not integration"
        ↓ 通过（仅 main 分支）
门3: integration-tests pytest tests/ -m integration
```

参考 `AI赋能的智能测试与质量保证/stock-research/.github/workflows/quality_gate.yml`。

---

## 11. 评估层（Phase 9，主体功能完成后加入）

| 工具 | 用途 | 评估目标 |
|---|---|---|
| **LangFuse** `@observe` | 追踪每阶段 LLM 调用延迟、token 消耗、输入输出 | 全部5个阶段节点 |
| **LangSmith** | 管理测试数据集、批量运行、不同版本对比 | 端到端 |
| **OpenEvals** `ANSWER_RELEVANCE` | 报告是否切题 | `final_report` |
| **OpenEvals** `HALLUCINATION` | 报告是否超出感知数据的信息边界 | `context=perception_data, output=final_report` |
| **DeepEval** `GEval` | 自定义指标评估 `investment_thesis` 质量（对应 C7）| `selected_plan.investment_thesis` |

**注意：** RAG 专属 OpenEvals（`RAG_GROUNDEDNESS`, `RAG_RETRIEVAL_RELEVANCE`）不适用于 InvestAgent，留给 PolicyPilot-RAG 使用。

---

## 12. 部署方案

| 方案 | 场景 | 成本 |
|---|---|---|
| 本地 `streamlit run app/streamlit_app.py` | 面试现场演示 | 0 |
| Streamlit Community Cloud | 分享公开链接给面试官 | 0（免费 tier）|
| ECS / RDS | **不需要** | — |

---

## 13. 实施顺序

| 阶段 | 任务 | 核心输出文件 | 主要复用来源 |
|---|---|---|---|
| 1 | SDD：写 spec 约束文档 | `spec/invest_spec.md` | stock-research/spec/research_spec.md 结构 |
| 2 | 脚手架：目录、配置文件 | `AGENTS.md`, `pyproject.toml`, `requirements*.txt`, `.env.example` | stock-research 同名文件 |
| 3 | Pydantic schemas | `src/schemas.py` | deliberative_research_langgraph.py 里5个 BaseModel |
| 4 | **TDD 锚点**：validate_report + C1–C8 测试 | `src/stages/reporter.py`, `tests/test_reporter.py`, `tests/conftest.py` | stock-research/src/reporter.py + tests/conftest.py |
| 5 | AKShare 工具层 + 测试 | `src/tools.py`, `tests/test_tools.py` | hybrid_wealth_advisor_langgraph.py @tool 结构 |
| 6 | 5个阶段函数 + 角色 persona | `src/stages/perception.py` … `reporter.py` | deliberative_research_langgraph.py 5个函数 + prompt 模板 |
| 7 | LangGraph 连线 + validator 节点 + 路由测试 | `src/agent.py`, `src/stages/validator.py`, `tests/test_agent.py` | hybrid_wealth_advisor_langgraph.py StateGraph 结构 |
| 8 | Linter + CI + Streamlit UI | `linters/`, `.github/workflows/`, `app/streamlit_app.py` | stock-research linter + CI 文件 |
| 9 | 评估层（LangFuse + OpenEvals）| 新增 eval 模块 | CASE-langfuse + CASE-openevals |

---

## 14. 面试叙事

> "InvestAgent 演示了三件 LangChain 做不到、需要 LangGraph 的事：有向环（工具调用循环）、`add_messages` reducer 追加语义、图结构级别的条件路由。架构上我把 Reactive 和 Deliberative 两条路径合并在一个 StateGraph 里，所有节点共享同一个 State，整个执行过程可以用 Mermaid 可视化，被 LangFuse 端到端追踪。Deliberative 路径的5个阶段每个都有专家角色 persona，感知阶段调用 AKShare 获取真实市场数据，后续4个阶段是纯 LLM 推理，最后由独立 Validator 节点校验报告是否满足8条 Spec 约束，不合格时通过第二个有向环路由回决策阶段重新生成。"
