# InvestAgent — 基于 LangGraph 的混合路径 AI 投研 Agent

> 输入研究主题，Agent 自动判断查询复杂度并选择执行路径：简单问题走 Reactive 路径调用 AKShare 快速回答；复杂研究走 Deliberative 路径，由5个专家角色依次完成感知→建模→推理→决策→报告，最终生成结构化 JSON 投研报告。全程 Pydantic 约束输出结构，LangFuse 追踪每个 LLM 调用，OpenEvals 量化评估报告质量。

---

## 核心亮点

- **智能双路径路由**：`assess` 节点通过 LLM 自动区分简单查询与深度研究，多轮对话中支持跟进问题识别，无需用户手动切换
- **5阶段深度投研流水线**：Deliberative 路径由市场数据分析师、宏观经济学家、策略研究员、投委会主席、报告撰写专家5个专家角色协作，输出符合 C1–C7 规范的 JSON 投研报告
- **内置质检与自动重试**：Validator 节点对报告执行 C1–C7 合规约束校验，不合格自动回退至 decision 节点重试（最多2次）
- **Production-ready 工程化**：LangFuse 链路追踪 + OpenEvals LLM-as-judge 评估 + 5组 pytest 测试文件 + `USE_REAL_DATA=false` 离线 mock 模式

---

## 技术栈

| 层次 | 技术 |
|---|---|
| Agent 编排 | LangGraph `StateGraph`，条件边，双有向环 |
| LLM | 通义千问（Qwen）via DashScope `ChatTongyi` |
| 市场数据 | AKShare（A 股行情、指数、PMI、市场新闻） |
| 输出验证 | Pydantic v2（每个 Stage 输出 Schema） |
| 可观测性 | LangFuse（延迟、Token、prompt/response 追踪） |
| 效果评估 | OpenEvals LLM-as-judge（相关性、幻觉率、投资逻辑质量） |
| UI | Streamlit |
| 测试 | pytest（单元 + 集成，mock LLM 解耦） |

---

## 系统架构

```
用户输入（研究主题 / 简单问题）
        ↓
   [assess]          ── LLM 判断 processing_mode
        ↓
   ┌────┴────┐
reactive   deliberative
   ↓              ↓
[reactive_agent]  [perception]    ← 市场数据分析师：AKShare 数据收集
    ↕ 环①              ↓
[tools(AKShare)]  [modeling]      ← 宏观经济学家：构建市场内部模型
    ↓                  ↓
[extract_resp]    [reasoning]     ← 策略研究员：生成3个候选投资方案
    ↓                  ↓
   END            [decision]      ← 投委会主席：选择最优方案
                       ↓
                   [report]       ← 报告撰写专家：生成结构化 JSON 报告
                       ↓
                  [validator]     ← 合规审查员：校验 C1–C7
                   ↕ 环②（不合格 → decision，最多重试2次）
                       ↓
                      END
```

**两个有向环说明：**
- **环①** `reactive_agent → tools → reactive_agent`：工具调用循环，直到 LLM 不再发出 tool call
- **环②** `validator → decision → report → validator`：报告质检重试，`retry_count` 防止无限循环

---

## 项目结构

```
InvestAgent/
├── spec/
│   ├── invest_spec.md          # 规格文档（项目"一等公民"）
│   └── project-architecture.md # 架构决策记录
├── src/
│   ├── agent.py                # LangGraph 图编排（节点连线、路由函数）
│   ├── state.py                # InvestAgentState TypedDict
│   ├── tools.py                # AKShare 工具函数（@tool 装饰器）
│   ├── schemas.py              # Pydantic 输出 Schema
│   ├── stages/
│   │   ├── perception.py       # 阶段1：市场数据分析师
│   │   ├── modeling.py         # 阶段2：宏观经济学家
│   │   ├── reasoning.py        # 阶段3：策略研究员
│   │   ├── decision.py         # 阶段4：投委会主席
│   │   ├── reporter.py         # 阶段5：报告撰写专家
│   │   └── validator.py        # 合规审查员（C1–C7）
│   └── evaluation/
│       ├── langfuse_tracing.py # LangFuse 链路追踪
│       └── openevals_eval.py   # LLM-as-judge 效果评估
├── tests/
│   ├── conftest.py
│   ├── test_agent.py           # C8–C9：路由行为测试
│   ├── test_stages.py          # Stage 函数单元测试（mock LLM）
│   ├── test_reporter.py        # C1–C7：报告结构合规测试
│   ├── test_tools.py           # AKShare 工具测试
│   └── test_integration.py     # 端到端集成测试
├── app/
│   └── streamlit_app.py        # Streamlit UI
├── Makefile
├── requirements.txt
└── requirements-dev.txt
```

---

## 快速开始

### 1. 环境准备

```bash
# 创建虚拟环境（推荐 Python 3.11+）
python -m venv .venv
source .venv/bin/activate

# 安装依赖
make install       # 运行时依赖
make install-dev   # 含测试/lint 工具
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`：

```env
# 必填：通义千问 API Key
DASHSCOPE_API_KEY=your_key_here

# 可选：LangFuse 链路追踪
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com

# 可选：false 时使用 mock 数据（离线测试/演示）
USE_REAL_DATA=true
```

### 3. 启动 UI

```bash
make run
# 或直接：streamlit run app/streamlit_app.py
```

---

## 测试

```bash
make test                 # 运行全部测试
make test-reporter        # 仅报告结构合规测试（C1–C7）
make test-agent           # 仅路由行为测试（C8–C9）
make test-integration     # 端到端集成测试（需 DASHSCOPE_API_KEY）
```

测试设计原则：
- **单元测试** mock LLM，Stage 函数与 LLM 完全解耦，可在无网络环境运行
- **集成测试** 使用 `USE_REAL_DATA=false` + 真实 LLM，验证完整流程
- 每条 Spec 约束（C1–C9）都有对应测试类，约束变更必须同步更新测试

---

## 报告输出格式

Deliberative 路径最终输出标准 JSON 报告：

```json
{
  "research_topic": "新能源行业",
  "industry_focus": "光伏",
  "time_horizon": "中期",
  "report_date": "2026-07-08",
  "dimensions": {
    "fundamental": { "summary": "≥100字的基本面分析", "confidence": 0.85 },
    "market":      { "summary": "≥100字的市场行情分析", "confidence": 0.78 },
    "news":        { "summary": "≥100字的新闻舆情分析", "confidence": 0.72 },
    "analyst":     { "summary": "≥100字的分析师观点", "confidence": 0.80 }
  },
  "investment_thesis": "≥50字的核心投资逻辑",
  "supporting_evidence": ["证据1", "证据2", "证据3"],
  "overall_rating": "buy",
  "risk_factors": ["风险1", "风险2"],
  "sources": ["来源1", "来源2", "来源3"]
}
```

---

## Spec 约束速查

| 编号 | 约束 | 校验位置 |
|---|---|---|
| C1 | 报告包含全部4个 dimensions | `validator` 节点 |
| C2 | 每个 `dimension.summary` ≥ 100字符 | `validator` 节点 |
| C3 | 每个 `dimension.confidence` ∈ [0.0, 1.0] | `validator` 节点 |
| C4 | `overall_rating` ∈ {buy, hold, sell} | `validator` 节点 |
| C5 | `sources` ≥ 3项 | `validator` 节点 |
| C6 | `risk_factors` 非空 | `validator` 节点 |
| C7 | `investment_thesis` ≥ 50字符 | `validator` 节点 |
| C8 | `processing_mode` ∈ {reactive, deliberative} | `test_agent.py` |
| C9 | reactive 路径 `final_response` 非空 | `test_agent.py` |

---

## Lint

```bash
make lint
# ruff check src/ tests/ + 自定义架构依赖检查（禁止反向依赖）
```

---

## 许可

MIT
