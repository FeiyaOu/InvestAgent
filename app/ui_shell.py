"""Static page shell following the frontend/ design: styles, top bar, home hero and capability cards.

Only presentation lives here. Markup uses our own `zh-*` classes; Streamlit internals are
targeted only through stable `st-key-*` container classes, so upgrades break as little as possible.
"""
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import streamlit as st

_CSS = """
<style>
.block-container { max-width: 1080px; padding-top: 2.2rem; }
.zh-topbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.6rem; }
.zh-status { display: inline-flex; align-items: center; gap: 8px; color: #60776c; font-size: 12px; }
.zh-status i { width: 7px; height: 7px; border-radius: 50%; background: #4c9270; display: inline-block; }
.zh-status.mock i { background: #c9a227; }
.zh-pill { border: 1px solid #e0e6e1; border-radius: 20px; background: #fff; color: #64726b;
           font-size: 12px; padding: 4px 12px; }
.zh-hero { text-align: center; margin: 1.5rem 0 1.4rem; }
.zh-eyebrow { display: inline-flex; align-items: center; gap: 8px; color: #527363; font-size: 12px;
              font-weight: 600; letter-spacing: .04em; border: 1px solid #dfe7e1; border-radius: 20px;
              padding: 4px 12px; background: rgba(255,255,255,.7); }
.zh-eyebrow span { width: 6px; height: 6px; border-radius: 50%; background: #4c9270; display: inline-block; }
.zh-hero h1 { color: #152b22; font-size: clamp(30px, 4vw, 42px); font-weight: 700; margin: .8rem 0 .4rem; }
.zh-hero p { color: #5f6f67; font-size: 15px; margin: 0; }
.zh-section-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px;
                   margin: 2.2rem 0 .9rem; }
.zh-section-head span { color: #668377; font-size: 12px; font-weight: 600; letter-spacing: .06em; }
.zh-section-head h2 { color: #152b22; font-size: 20px; margin: .2rem 0 0; padding: 0; }
.zh-section-head p { color: #6b7a72; font-size: 13px; max-width: 360px; margin: 0; }
.zh-cap-grid { display: grid; grid-template-columns: repeat(5, 1fr); border: 1px solid #e1e6e2;
               border-radius: 14px; background: #fff; overflow: hidden; }
.zh-cap { padding: 18px 16px; border-right: 1px solid #e7ebe7; }
.zh-cap:last-child { border-right: 0; }
.zh-cap-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.zh-cap-top b { font-size: 20px; }
.zh-cap-top span { color: #4c7a62; background: #edf5ef; border-radius: 10px; font-size: 11px; padding: 2px 8px; }
.zh-cap h3 { font-size: 14px; color: #18251f; margin: 0 0 6px; padding: 0; }
.zh-cap p { font-size: 12px; color: #6b7a72; line-height: 1.6; margin: 0; }
.zh-footer { display: flex; justify-content: space-between; color: #8a978f; font-size: 12px;
             border-top: 1px solid #e3e8e4; margin-top: 2.4rem; padding-top: 1rem; }
.zh-question { border: 1px solid #e1e6e2; border-radius: 12px; background: #fff; padding: 16px 20px;
               margin-bottom: 1rem; }
.zh-question span { color: #668377; font-size: 12px; font-weight: 600; }
.zh-question h1 { font-size: 18px; color: #152b22; margin: .3rem 0 0; padding: 0; line-height: 1.5; }
.zh-brand { display: flex; align-items: center; gap: 10px; color: #fff; font-size: 17px; font-weight: 700;
            margin: 0 0 1.2rem; }
.zh-brand i { width: 30px; height: 30px; border-radius: 9px; background: #b9efb7; color: #10261f;
              display: inline-flex; align-items: center; justify-content: center; font-style: normal; }
.zh-brand small { font-size: 10px; color: #b9efb7; border: 1px solid #3c6b58; border-radius: 6px; padding: 1px 6px; }
.zh-recent-label { color: #8fb3a2; font-size: 11px; font-weight: 600; letter-spacing: .06em; margin: 1.2rem 0 .4rem; }
.zh-recent { color: #d9e4de; font-size: 13px; padding: 6px 4px; white-space: nowrap; overflow: hidden;
             text-overflow: ellipsis; }
/* Sidebar buttons keep one text colour in every state; hover only shifts the background. */
.st-key-new_chat button, .st-key-new_chat button:hover, .st-key-new_chat button:focus,
.st-key-new_chat button:active { background: #b9efb7; color: #10261f; border: 0; font-weight: 600; }
.st-key-new_chat button:hover { background: #a6e4a4; }
.st-key-new_chat button * { color: inherit; }
[class*="st-key-nav_"] button, [class*="st-key-nav_"] button:hover, [class*="st-key-nav_"] button:focus,
[class*="st-key-nav_"] button:active { justify-content: flex-start; border: 0; color: #d9e4de;
                                       background: transparent; box-shadow: none; }
[class*="st-key-nav_"] button:hover { background: rgba(255, 255, 255, .06); }
[class*="st-key-nav_"] button[data-testid="stBaseButton-primary"],
[class*="st-key-nav_"] button[data-testid="stBaseButton-primary"]:hover { background: #1d3a30; color: #f5fff9; }
[class*="st-key-nav_"] button * { color: inherit; }
.zh-progress { border: 1px solid #e1e6e2; border-radius: 14px; background: #fff; padding: 22px 24px; margin-bottom: 1rem; }
.zh-progress-head { display: flex; align-items: center; gap: 16px; margin-bottom: 14px; }
.zh-progress-head h2 { font-size: 17px; color: #152b22; margin: 0; padding: 0; }
.zh-progress-head p { font-size: 13px; color: #6b7a72; margin: 2px 0 0; }
.zh-orbit { width: 34px; height: 34px; border-radius: 50%; border: 3px solid #dcebe2; border-top-color: #2f6b52;
            animation: zh-spin 1s linear infinite; flex: none; }
@keyframes zh-spin { to { transform: rotate(360deg); } }
.zh-step { display: grid; grid-template-columns: 28px 1fr auto; align-items: center; gap: 12px;
           padding: 10px 0; border-top: 1px solid #eef1ee; }
.zh-step-dot { width: 24px; height: 24px; border-radius: 50%; display: inline-flex; align-items: center;
               justify-content: center; font-size: 12px; background: #eef2ef; color: #7a8a82; }
.zh-step b { display: block; font-size: 14px; color: #18251f; font-weight: 600; }
.zh-step small { display: block; font-size: 12px; color: #6b7a72; margin-top: 2px; }
.zh-step em { font-style: normal; font-size: 12px; color: #8a978f; }
.zh-step.active .zh-step-dot { background: #163d30; color: #fff; }
.zh-step.active em { color: #2f6b52; font-weight: 600; }
.zh-step.done .zh-step-dot { background: #dff1e4; color: #2f6b52; }
.zh-step.partial .zh-step-dot, .zh-step.partial em { background: #fbf1d6; color: #9a7413; }
.zh-step.partial em { background: transparent; }
.zh-step.failed .zh-step-dot { background: #f8e1df; color: #a33a32; }
.zh-step.failed em { color: #a33a32; }
.zh-answer-head { display: flex; align-items: center; gap: 12px; margin: .4rem 0 1rem; }
.zh-answer-head i { width: 34px; height: 34px; border-radius: 10px; background: #163d30; color: #b9efb7;
                    display: inline-flex; align-items: center; justify-content: center; font-style: normal; }
.zh-answer-head b { display: block; font-size: 15px; color: #18251f; }
.zh-answer-head span { display: block; font-size: 12px; color: #6b7a72; margin-top: 2px; }
.zh-summary-label { color: #2f6b52; font-size: 12px; font-weight: 700; letter-spacing: .06em; }
.zh-result-title { display: flex; align-items: center; gap: 14px; margin: 1.8rem 0 .8rem; }
.zh-result-title > span { color: #9aa9a1; font-size: 13px; font-weight: 700; font-family: "DM Sans", sans-serif; }
.zh-result-title h2 { font-size: 17px; color: #152b22; margin: 0; padding: 0; }
.zh-result-title p { font-size: 12px; color: #6b7a72; margin: 2px 0 0; }
@media (max-width: 760px) {
  .zh-cap-grid { grid-template-columns: 1fr; }
  .zh-cap { border-right: 0; border-bottom: 1px solid #e7ebe7; }
  .zh-section-head { flex-direction: column; align-items: flex-start; }
}
</style>
"""

# Only abilities the agent actually has today (spec/analysis-strategy-upgrade.md, phase 1).
CAPABILITIES = [
    ("📈", "数据", "行情与估值查询", "个股、指数、板块行情，以及 PE TTM、PB、PS 估值快照"),
    ("🧭", "分析", "历史表现与基准", "收益、波动率、最大回撤，相对指数的超额收益与 Beta"),
    ("⚖️", "对比", "同行相对位置", "技术面与估值因子的样本内 z-score 和百分位"),
    ("🛡️", "风控", "组合风险与情景", "组合 VaR/CVaR、约束检查、压力测试与历史情景重演"),
    ("📄", "报告", "行业研究报告", "四维度研究报告，可阅读并下载 Markdown / HTML"),
]


def greeting(now=None) -> str:
    hour = (now or datetime.now(ZoneInfo("Asia/Shanghai"))).astimezone(ZoneInfo("Asia/Shanghai")).hour
    return "早上好" if hour < 12 else "下午好" if hour < 18 else "晚上好"


def inject_styles():
    st.html(_CSS)


def render_brand():
    st.html('<div class="zh-brand"><i>✦</i>InvestAgent<small>BETA</small></div>')


def render_recent(history):
    st.html('<div class="zh-recent-label">最近对话</div>')
    if not history:
        st.caption("暂无，本会话的提问会显示在这里。")
    for turn in reversed(history[-5:]):
        st.html(f'<div class="zh-recent">{escape(turn["query"])}</div>')


def render_topbar(real_data: bool):
    status = ('<span class="zh-status"><i></i>真实数据模式 · AKShare</span>' if real_data
              else '<span class="zh-status mock"><i></i>模拟数据模式</span>')
    st.html(f'<div class="zh-topbar">{status}<span class="zh-pill">上下文保留最近 3 轮</span></div>')


def render_hero():
    st.html(f"""<section class="zh-hero">
      <div class="zh-eyebrow"><span></span>AI 驱动的投研工作台</div>
      <h1>{greeting()}，想研究什么？</h1>
      <p>查询行情、比较公司、分析历史表现与组合风险，或生成一份行业研究报告。</p>
    </section>""")


def render_capabilities():
    cards = "".join(f"""<article class="zh-cap"><div class="zh-cap-top"><b>{icon}</b><span>{tag}</span></div>
        <h3>{title}</h3><p>{text}</p></article>""" for icon, tag, title, text in CAPABILITIES)
    st.html(f"""<div class="zh-section-head"><div><span>研究能力</span><h2>从数据到结论，一站完成</h2></div>
      <p>回答和图表在结果页呈现，完整报告可前往「报告中心」阅读与下载。</p></div>
      <div class="zh-cap-grid">{cards}</div>""")


def render_footer():
    st.html('<div class="zh-footer"><span>AI 生成内容仅供研究参考，不构成任何投资建议</span>'
            '<span>数据来自 AKShare 公开接口，可能存在延迟或缺失</span></div>')


def render_question(question: str):
    st.html(f'<div class="zh-question"><span>你的问题</span><h1>{escape(question)}</h1></div>')


def render_answer_head(meta: str):
    st.html(f'<div class="zh-answer-head"><i>✦</i><div><b>InvestAgent 研究助手</b><span>{escape(meta)}</span></div></div>')


def render_summary(text: str):
    """Model-written conclusion only; Markdown is kept because the composer may use lists."""
    with st.container(border=True):
        st.html('<span class="zh-summary-label">核心结论</span>')
        st.markdown(text)


def render_section_title(number: int, title: str, subtitle: str):
    st.html(f'<div class="zh-result-title"><span>{number:02d}</span><div><h2>{escape(title)}</h2>'
            f'<p>{escape(subtitle)}</p></div></div>')
