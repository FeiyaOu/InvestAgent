# -*- coding: utf-8 -*-
"""
InvestAgent — Streamlit UI（多轮对话版）

混合型智能投研助手演示界面，支持多轮对话。
- 每个浏览器会话自动分配唯一 thread_id（MemorySaver 状态隔离）
- 对话历史面板展示历轮摘要
- "🔄 新对话"按钮重置 thread_id，开启全新会话
"""

from __future__ import annotations

import json
import os
import uuid

from dotenv import load_dotenv
import streamlit as st

# 自动加载项目根目录的 .env 文件
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

# ============================================================
# 页面配置
# ============================================================

st.set_page_config(
    page_title="InvestAgent — 混合型智能投研助手",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# 会话状态初始化（多轮对话核心）
# ============================================================

if "thread_id" not in st.session_state:
    st.session_state["thread_id"] = str(uuid.uuid4())

if "conversation_history" not in st.session_state:
    st.session_state["conversation_history"] = []

if "turn_count" not in st.session_state:
    st.session_state["turn_count"] = 0

if "last_result" not in st.session_state:   # ← 新增：持久化最新运行结果
    st.session_state["last_result"] = None

if "last_eval_results" not in st.session_state:
    st.session_state["last_eval_results"] = None

# ============================================================
# 侧边栏：设置
# ============================================================

with st.sidebar:
    st.title("⚙️ 设置")

    use_real_data = st.toggle(
        "使用真实 AKShare 数据",
        value=False,
        help="关闭时使用 mock 数据（适合演示或网络不稳定时）",
    )
    os.environ["USE_REAL_DATA"] = "true" if use_real_data else "false"

    st.divider()

    # ---- 多轮对话控制 ----
    st.markdown("**💬 当前会话**")
    thread_short = st.session_state["thread_id"][:8]
    st.caption(f"Thread: `{thread_short}...`")
    st.caption(f"第 {st.session_state['turn_count']} 轮")

    if st.button("🔄 新对话", use_container_width=True, help="重置会话，清除对话历史"):
        st.session_state["thread_id"] = str(uuid.uuid4())
        st.session_state["conversation_history"] = []
        st.session_state["turn_count"] = 0
        st.session_state["last_result"] = None
        st.session_state["last_query"] = ""
        st.session_state["last_eval_results"] = None
        st.rerun()

    st.divider()
    st.markdown("**关于本项目**")
    st.markdown("""
InvestAgent 演示 LangGraph 混合型 Agent：

- **有向环①**：Reactive 工具调用循环
- **有向环②**：Validator 重试路由
- **MemorySaver**：多轮对话状态持久化
- **条件边**：assess 节点动态路由
- **AKShare**：真实 A 股市场数据

**技术栈：** LangGraph · LangChain · Pydantic · AKShare
    """)

    st.divider()
    with st.expander("📋 C1–C9 Spec 约束"):
        st.markdown("""
| 约束 | 内容 |
|---|---|
| C1 | 4个分析维度完整 |
| C2 | 摘要 ≥ 100 字 |
| C3 | 置信度 ∈ [0,1] |
| C4 | 评级为 buy/hold/sell |
| C5 | 来源 ≥ 3 个 |
| C6 | 风险因素非空 |
| C7 | 投资论点 ≥ 50 字 |
| C8 | 路由模式合法 |
| C9 | Reactive 回答非空 |
        """)

# ============================================================
# 主页面
# ============================================================

st.title("📊 InvestAgent — 混合型智能投研助手")
st.caption("LangGraph Hybrid Agent · Reactive + Deliberative · MemorySaver 多轮对话 · AKShare 市场数据")

# ---- 对话历史面板 ----
if st.session_state["conversation_history"]:
    with st.expander(f"💬 对话历史（{len(st.session_state['conversation_history'])} 轮）", expanded=False):
        for i, turn in enumerate(st.session_state["conversation_history"], 1):
            mode_icon = "⚡" if turn["mode"] == "reactive" else "🔬"
            rating = turn.get("rating", "")
            rating_str = f" → {rating.upper()}" if rating else ""
            st.markdown(f"**第{i}轮** {mode_icon} `{turn['mode']}`{rating_str}")
            st.caption(f"Q: {turn['query'][:60]}{'...' if len(turn['query']) > 60 else ''}")
            if turn.get("response_preview"):
                st.caption(f"A: {turn['response_preview'][:80]}...")
            st.divider()

# ---- 示例查询 ----
st.markdown("**快速示例：**")
col1, col2, col3, col4 = st.columns(4)

with col1:
    if st.button("⚡ 简单查询", use_container_width=True):
        st.session_state["query_input"] = "今天新能源板块行情如何？"

with col2:
    if st.button("🔬 深度研究", use_container_width=True):
        st.session_state["query_input"] = "请深度分析新能源行业的中期投资机会"

with col3:
    if st.button("📈 行业分析", use_container_width=True):
        st.session_state["query_input"] = "光伏行业当前是否具备投资价值？请给出详细分析"

with col4:
    # 追问按钮：只有在有历史时才有意义
    followup_disabled = len(st.session_state["conversation_history"]) == 0
    if st.button("↩️ 追问", use_container_width=True, disabled=followup_disabled,
                 help="针对上一轮分析结果提问"):
        st.session_state["query_input"] = "上述分析中，哪个风险因素最值得关注？请展开说明。"

st.divider()

# ---- 输入区 ----
user_query = st.text_area(
    "输入您的查询",
    value=st.session_state.get("query_input", ""),
    height=80,
    placeholder="例如：请分析新能源行业的中期投资机会，重点关注光伏板块...",
    key="query_input",
)

with st.expander("⚙️ 高级选项（可选）"):
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        research_topic = st.text_input("研究主题", placeholder="新能源行业")
    with col_b:
        industry_focus = st.text_input("行业焦点", placeholder="光伏")
    with col_c:
        time_horizon = st.selectbox("时间范围", ["中期", "短期", "长期"])

run_btn = st.button("🚀 运行 InvestAgent", type="primary", use_container_width=True)

# ============================================================
# 运行 Agent — 使用 LangGraph stream() 实时展示每个节点进度
# ============================================================

# 节点名称 → UI 标签映射
_NODE_LABELS = {
    "assess":           "📍 [评估] 判断查询类型与复杂度",
    "perception":       "📡 [感知] 市场数据分析师收集市场数据",
    "modeling":         "🌍 [建模] 宏观经济学家构建市场模型",
    "reasoning":        "💡 [推理] 策略研究员生成候选投资方案",
    "decision":         "🎯 [决策] 投资委员会主席选择最优方案",
    "report":           "📄 [报告] 撰写专家生成投研报告",
    "validator":        "✅ [校验] 独立合规审查员检查报告",
    "reactive_agent":   "⚡ [反应] 处理简单查询",
    "tools":            "🔧 [工具] 调用 AKShare 市场数据",
    "extract_response": "💬 [提取] 整理最终回答",
}


if run_btn and user_query.strip():
    from src.agent import create_invest_agent

    turn_num = st.session_state["turn_count"] + 1
    thread_id = st.session_state["thread_id"]

    # 构建初始 state（与 run_invest_agent 保持一致）
    initial_state = {
        "user_query": user_query.strip(),
        "research_topic": research_topic or user_query.strip(),
        "industry_focus": industry_focus or "",
        "time_horizon": time_horizon,
        "processing_mode": None,
        "query_type": None,
        "messages": [],
        "final_response": None,
        "perception_data": None,
        "world_model": None,
        "reasoning_plans": None,
        "selected_plan": None,
        "final_report": None,
        "validation_errors": None,
        "retry_count": 0,
        "current_phase": "assess",
        "error": None,
    }
    config = {"configurable": {"thread_id": thread_id}}

    with st.status(f"InvestAgent 运行中（第{turn_num}轮）...", expanded=True) as status:
        try:
            agent = create_invest_agent()
            accumulated_state = dict(initial_state)

            for chunk in agent.stream(initial_state, config=config):
                node_name = list(chunk.keys())[0]
                state_update = chunk[node_name]
                accumulated_state.update(state_update)

                label = _NODE_LABELS.get(node_name, f"执行节点: {node_name}")

                # 为关键节点附加额外上下文
                if node_name == "assess":
                    mode = state_update.get("processing_mode", "")
                    topic = state_update.get("research_topic", "")
                    st.write(f"{label} → `{mode}` | 主题: {topic[:30]}")

                elif node_name == "reasoning":
                    plans = state_update.get("reasoning_plans", [])
                    count = len(plans) if isinstance(plans, list) else "?"
                    st.write(f"{label} → 生成 {count} 个候选方案")

                elif node_name == "validator":
                    errors = state_update.get("validation_errors", [])
                    phase = state_update.get("current_phase", "")
                    if not errors:
                        st.write(f"{label} ✓ 全部通过")
                    elif phase == "completed":
                        warn_types = [e["type"] for e in errors]
                        st.write(f"{label} ⚠️ 带质量警告完成: {warn_types}")
                    else:
                        retry = state_update.get("retry_count", 1)
                        st.write(f"{label} 🔄 触发重试 #{retry}")

                else:
                    st.write(label)

            final_state = accumulated_state
            status.update(label="✅ 运行完成", state="complete", expanded=False)

        except Exception as e:
            status.update(label=f"❌ 运行出错: {e}", state="error")
            st.error(f"Agent 运行失败：{e}")
            st.stop()

    # 计算对话历史摘要
    processing_mode = final_state.get("processing_mode", "unknown")
    turn_record = {"query": user_query.strip(), "mode": processing_mode, "rating": "", "response_preview": ""}

    if processing_mode == "reactive":
        turn_record["response_preview"] = (final_state.get("final_response") or "")[:120]
    elif final_state.get("final_report"):
        try:
            r = json.loads(final_state["final_report"])
            turn_record["rating"] = r.get("overall_rating", "")
            turn_record["response_preview"] = r.get("investment_thesis", "")[:120]
        except Exception:
            pass

    # 持久化 → rerun（rerun 后展示块从 session_state 读取结果）
    st.session_state["last_result"] = final_state
    st.session_state["last_query"] = user_query.strip()
    st.session_state["last_eval_results"] = None   # 新一轮运行清除旧评估
    st.session_state["turn_count"] = turn_num
    st.session_state["conversation_history"].append(turn_record)
    st.rerun()

elif run_btn and not user_query.strip():
    st.warning("请输入查询内容后再运行。")

# ============================================================
# 展示最新结果（从 session_state 读取，rerun 后依然可见）
# ============================================================

if st.session_state.get("last_result"):
    from src.stages.reporter import validate_report

    final_state = st.session_state["last_result"]
    processing_mode = final_state.get("processing_mode", "unknown")

    st.divider()
    st.markdown(
        f"**第 {st.session_state['turn_count']} 轮结果** · "
        f"路由模式：`{processing_mode}` · "
        f"Q: *{st.session_state.get('last_query', '')[:50]}*"
    )

    if processing_mode == "reactive":
        st.subheader("⚡ 快速回答（Reactive 路径）")
        final_response = final_state.get("final_response", "")
        if final_response:
            st.success(final_response)
        else:
            st.warning("未能获取回答，请重试。")

        with st.expander("🔍 消息历史"):
            for msg in final_state.get("messages", []):
                role = type(msg).__name__
                content = getattr(msg, "content", str(msg))
                st.markdown(f"**{role}:** {content}")

    else:
        st.subheader("🔬 深度研究报告（Deliberative 路径）")

        if final_state.get("error"):
            st.warning(f"⚠️ {final_state['error']}")

        # 5阶段进度
        stage_names = ["感知", "建模", "推理", "决策", "报告"]
        stage_keys = ["perception_data", "world_model", "reasoning_plans", "selected_plan", "final_report"]
        cols = st.columns(5)
        for col, name, key in zip(cols, stage_names, stage_keys):
            with col:
                (st.success if final_state.get(key) else st.error)(f"{'✓' if final_state.get(key) else '✗'} {name}")

        st.divider()

        if final_state.get("perception_data"):
            with st.expander("📡 阶段1：感知数据"):
                st.json(final_state["perception_data"])

        if final_state.get("world_model"):
            with st.expander("🌍 阶段2：市场内部模型"):
                wm = final_state["world_model"]
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**市场状态：** {wm.get('market_state','N/A')}")
                    st.markdown(f"**经济周期：** {wm.get('economic_cycle','N/A')}")
                    st.markdown(f"**市场情绪：** {wm.get('market_sentiment','N/A')}")
                with c2:
                    for r in wm.get("risk_factors", []):
                        st.markdown(f"- {r}")

        if final_state.get("reasoning_plans"):
            with st.expander("💡 阶段3：候选投资方案"):
                for plan in (final_state["reasoning_plans"] if isinstance(final_state["reasoning_plans"], list) else []):
                    st.markdown(f"**方案 {plan.get('plan_id','N/A')}** — 置信度：{plan.get('confidence_level','N/A')}")
                    st.markdown(f"> {plan.get('hypothesis','')}")

        if final_state.get("selected_plan"):
            with st.expander("🎯 阶段4：投资决策"):
                sp = final_state["selected_plan"]
                st.markdown(f"**选定方案：** `{sp.get('selected_plan_id','N/A')}`")
                st.info(sp.get("investment_thesis", ""))
                st.markdown(f"**建议：** {sp.get('recommendation','N/A')} · **时间框架：** {sp.get('timeframe','N/A')}")

        if final_state.get("final_report"):
            st.subheader("📄 最终投研报告")
            try:
                report = json.loads(final_state["final_report"])
                errors = validate_report(report)
                if errors:
                    st.warning(f"⚠️ {len(errors)} 个质量问题：{[e['type'] for e in errors]}")
                else:
                    st.success("✅ 报告通过 C1–C7 全部约束校验")

                rating_color = {"buy": "🟢", "hold": "🟡", "sell": "🔴"}.get(report.get("overall_rating",""), "⚪")
                c1, c2, c3 = st.columns(3)
                c1.metric("整体评级", f"{rating_color} {report.get('overall_rating','N/A').upper()}")
                c2.metric("研究主题", report.get("research_topic","N/A"))
                c3.metric("时间范围", report.get("time_horizon","N/A"))

                for dim_name, dim_data in report.get("dimensions", {}).items():
                    label = {"fundamental":"基本面","market":"市场面","news":"消息面","analyst":"分析师"}.get(dim_name, dim_name)
                    conf = dim_data.get("confidence", 0)
                    with st.expander(f"{label}（置信度 {conf:.0%}）"):
                        st.write(dim_data.get("summary",""))

                if report.get("risk_factors"):
                    st.markdown("**⚠️ 风险因素：**")
                    for r in report["risk_factors"]:
                        st.markdown(f"- {r}")

                if report.get("sources"):
                    with st.expander("📚 数据来源"):
                        for s in report["sources"]:
                            st.markdown(f"- {s}")

                with st.expander("🔧 原始 JSON 报告"):
                    st.json(report)

            except json.JSONDecodeError:
                st.code(final_state["final_report"])

        retry_count = final_state.get("retry_count", 0)
        if retry_count > 0:
            st.info(f"ℹ️ Validator 触发了 {retry_count} 次重试")

    # ============================================================
    # 评估面板（OpenEvals，点击后按需运行）
    # ============================================================
    if final_state.get("final_report"):
        st.divider()
        st.subheader("📊 质量评估（OpenEvals）")
        st.caption("使用 Qwen 作为评判 LLM，评估报告的相关性、幻觉程度和投资论点质量")

        eval_col1, eval_col2 = st.columns([1, 3])
        with eval_col1:
            run_eval_btn = st.button("▶ 运行评估", use_container_width=True,
                                     help="需要 DASHSCOPE_API_KEY（约需10-20秒）")
        with eval_col2:
            if not os.getenv("DASHSCOPE_API_KEY"):
                st.warning("需要 DASHSCOPE_API_KEY 才能运行评估")

        if run_eval_btn:
            from src.evaluation.openevals_eval import run_openevals

            with st.spinner("OpenEvals 评估中（Qwen-as-judge）..."):
                eval_results = run_openevals(final_state)
                st.session_state["last_eval_results"] = eval_results

        # 显示评估结果
        if st.session_state.get("last_eval_results"):
            er = st.session_state["last_eval_results"]
            ec1, ec2, ec3 = st.columns(3)

            def _score_display(result: dict, label: str, col):
                score = result.get("score")
                with col:
                    if score is None:
                        st.metric(label, "N/A")
                        st.caption(result.get("reasoning", "")[:100])
                    else:
                        score_pct = f"{score:.0%}" if isinstance(score, float) else str(score)
                        color = "🟢" if isinstance(score, float) and score >= 0.7 else (
                            "🟡" if isinstance(score, float) and score >= 0.4 else "🔴"
                        )
                        st.metric(label, f"{color} {score_pct}")
                        with st.expander("评审理由"):
                            st.write(result.get("reasoning", ""))

            _score_display(er.get("answer_relevance", {}), "回答相关性", ec1)
            _score_display(er.get("hallucination", {}),    "幻觉程度↓", ec2)
            _score_display(er.get("thesis_quality", {}),   "投资论点质量", ec3)

            st.caption("注：幻觉程度分数越低越好（0=无幻觉，1=大量虚构）")
