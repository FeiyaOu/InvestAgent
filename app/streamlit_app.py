# -*- coding: utf-8 -*-
"""
InvestAgent — Streamlit UI

混合型智能投研助手演示界面。
- Reactive 路径：简单市场查询 → 工具调用 → 快速回答
- Deliberative 路径：复杂研究请求 → 5阶段分析 → 结构化投研报告
"""

from __future__ import annotations

import json
import os
from datetime import datetime

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
    st.markdown("**关于本项目**")
    st.markdown("""
InvestAgent 演示了 LangGraph 混合型 Agent 架构：

- **有向环①**：Reactive 工具调用循环
- **有向环②**：Validator 重试路由
- **条件边**：assess 节点动态路由
- **共享 State**：10个节点共享 TypedDict
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
st.caption("LangGraph Hybrid Agent · Reactive + Deliberative · AKShare 市场数据")

# ---- 示例查询 ----
st.markdown("**快速示例：**")
col1, col2, col3 = st.columns(3)

example_reactive = "今天新能源板块行情如何？"
example_deliberative = "请深度分析新能源行业的中期投资机会"

with col1:
    if st.button("⚡ 简单查询（Reactive）", use_container_width=True):
        st.session_state["query_input"] = example_reactive

with col2:
    if st.button("🔬 深度研究（Deliberative）", use_container_width=True):
        st.session_state["query_input"] = "请深度分析新能源行业的中期投资机会"

with col3:
    if st.button("📈 行业分析", use_container_width=True):
        st.session_state["query_input"] = "光伏行业当前是否具备投资价值？请给出详细分析"

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
# 运行 Agent
# ============================================================

if run_btn and user_query.strip():
    from src.agent import run_invest_agent
    from src.stages.reporter import validate_report

    st.divider()

    with st.status("InvestAgent 运行中...", expanded=True) as status:
        st.write("📍 正在初始化 LangGraph StateGraph...")

        try:
            final_state = run_invest_agent(
                user_query=user_query.strip(),
                research_topic=research_topic or "",
                industry_focus=industry_focus or "",
                time_horizon=time_horizon,
            )
            status.update(label="✅ 运行完成", state="complete", expanded=False)
        except Exception as e:
            status.update(label=f"❌ 运行出错: {e}", state="error")
            st.error(f"Agent 运行失败：{e}")
            st.stop()

    # ---- 展示结果 ----
    processing_mode = final_state.get("processing_mode", "unknown")
    st.markdown(f"**路由模式：** `{processing_mode}`")

    if processing_mode == "reactive":
        # ---- Reactive 路径结果 ----
        st.subheader("⚡ 快速回答（Reactive 路径）")
        final_response = final_state.get("final_response", "")
        if final_response:
            st.success(final_response)
        else:
            st.warning("未能获取回答，请重试。")

        with st.expander("🔍 消息历史"):
            messages = final_state.get("messages", [])
            for msg in messages:
                role = type(msg).__name__
                content = getattr(msg, "content", str(msg))
                st.markdown(f"**{role}:** {content}")

    else:
        # ---- Deliberative 路径结果 ----
        st.subheader("🔬 深度研究报告（Deliberative 路径）")

        error = final_state.get("error")
        if error:
            st.warning(f"⚠️ 运行中出现警告：{error}")

        # 5阶段进度展示
        st.markdown("**分析阶段进度：**")
        stages_col = st.columns(5)
        stage_names = ["感知", "建模", "推理", "决策", "报告"]
        stage_keys = ["perception_data", "world_model", "reasoning_plans", "selected_plan", "final_report"]

        for i, (col, name, key) in enumerate(zip(stages_col, stage_names, stage_keys)):
            with col:
                if final_state.get(key):
                    st.success(f"✓ {name}")
                else:
                    st.error(f"✗ {name}")

        st.divider()

        # 感知数据
        if final_state.get("perception_data"):
            with st.expander("📡 阶段1：感知数据（市场数据分析师）"):
                st.json(final_state["perception_data"])

        # 世界模型
        if final_state.get("world_model"):
            with st.expander("🌍 阶段2：市场内部模型（宏观经济学家）"):
                wm = final_state["world_model"]
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**市场状态：** {wm.get('market_state', 'N/A')}")
                    st.markdown(f"**经济周期：** {wm.get('economic_cycle', 'N/A')}")
                    st.markdown(f"**市场情绪：** {wm.get('market_sentiment', 'N/A')}")
                with col2:
                    if wm.get("risk_factors"):
                        st.markdown("**风险因素：**")
                        for r in wm["risk_factors"]:
                            st.markdown(f"- {r}")

        # 推理方案
        if final_state.get("reasoning_plans"):
            with st.expander("💡 阶段3：候选投资方案（策略研究员）"):
                plans = final_state["reasoning_plans"]
                if isinstance(plans, list):
                    for plan in plans:
                        st.markdown(f"**方案 {plan.get('plan_id', 'N/A')}** — 置信度：{plan.get('confidence_level', 'N/A')}")
                        st.markdown(f"> {plan.get('hypothesis', '')}")

        # 决策结果
        if final_state.get("selected_plan"):
            with st.expander("🎯 阶段4：投资决策（投资委员会主席）"):
                sp = final_state["selected_plan"]
                st.markdown(f"**选定方案：** `{sp.get('selected_plan_id', 'N/A')}`")
                st.markdown(f"**投资论点：**")
                st.info(sp.get("investment_thesis", ""))
                st.markdown(f"**建议：** {sp.get('recommendation', 'N/A')}")
                st.markdown(f"**时间框架：** {sp.get('timeframe', 'N/A')}")

        # 最终报告
        if final_state.get("final_report"):
            st.subheader("📄 最终投研报告")
            try:
                report = json.loads(final_state["final_report"])

                # 校验结果
                errors = validate_report(report)
                if errors:
                    st.warning(f"⚠️ 报告存在 {len(errors)} 个约束问题：{[e['type'] for e in errors]}")
                else:
                    st.success("✅ 报告通过 C1–C7 全部约束校验")

                # 整体评级
                rating_color = {"buy": "🟢", "hold": "🟡", "sell": "🔴"}.get(
                    report.get("overall_rating", ""), "⚪"
                )
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("整体评级", f"{rating_color} {report.get('overall_rating', 'N/A').upper()}")
                with col2:
                    st.metric("研究主题", report.get("research_topic", "N/A"))
                with col3:
                    st.metric("时间范围", report.get("time_horizon", "N/A"))

                # 四个维度
                st.markdown("**分析维度：**")
                dims = report.get("dimensions", {})
                for dim_name, dim_data in dims.items():
                    dim_label = {"fundamental": "基本面", "market": "市场面",
                                 "news": "消息面", "analyst": "分析师"}.get(dim_name, dim_name)
                    confidence = dim_data.get("confidence", 0)
                    with st.expander(f"{dim_label}（置信度 {confidence:.0%}）"):
                        st.write(dim_data.get("summary", ""))

                # 风险因素
                if report.get("risk_factors"):
                    st.markdown("**⚠️ 风险因素：**")
                    for r in report["risk_factors"]:
                        st.markdown(f"- {r}")

                # 来源
                if report.get("sources"):
                    with st.expander("📚 数据来源"):
                        for s in report["sources"]:
                            st.markdown(f"- {s}")

                # 原始 JSON
                with st.expander("🔧 原始 JSON 报告"):
                    st.json(report)

            except json.JSONDecodeError:
                st.code(final_state["final_report"])

        # Validator 结果
        validation_errors = final_state.get("validation_errors")
        retry_count = final_state.get("retry_count", 0)
        if retry_count > 0:
            st.info(f"ℹ️ Validator 触发了 {retry_count} 次重试")

elif run_btn and not user_query.strip():
    st.warning("请输入查询内容后再运行。")
