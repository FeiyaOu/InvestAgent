"""Session-local report reading and portable exports; no execution or persistence."""
from copy import deepcopy
from html import escape
import json
import math
import re
from urllib.parse import urlsplit

import streamlit as st
from src.stages.reporter import validate_report

_DIMENSIONS = {'fundamental':'基本面', 'market':'市场', 'news':'新闻', 'analyst':'分析师'}
_RATINGS = {'buy':'买入', 'hold':'持有', 'sell':'卖出'}


def prepare_report(raw):
    """Parse defensively; all report business checks remain in validate_report."""
    try:
        report = json.loads(raw) if isinstance(raw, str) else deepcopy(raw)
        if not isinstance(report, dict):
            raise ValueError('report must be an object')
        errors = validate_report(report)
    except (ValueError, TypeError, AttributeError):
        raise ValueError('报告内容不是可读取的结构化报告，请查看节点结果。') from None
    return report, errors


def _text(value):
    return '' if value is None else str(value)


def _md(value):
    # Generated prose is text, not trusted HTML/Markdown instructions.
    return re.sub(r'([\\`*_{}\[\]()#+.!|>~\-])', r'\\\1', escape(_text(value)))


def _url(value):
    value = _text(value)
    try:
        parsed = urlsplit(value)
        if (parsed.scheme in {'https','http'} and parsed.netloc and not parsed.username
                and not parsed.password and not any(c.isspace() or c in '<>"' for c in value)):
            return value
    except ValueError:
        pass
    return None


def _list(report, field):
    value = report.get(field, [])
    return value if isinstance(value, list) else []


def _dimensions(report):
    value = report.get('dimensions', {})
    return value if isinstance(value, dict) else {}


def report_markdown(report, errors):
    lines = [f"# {_md(report.get('research_topic', '投研报告'))}", '']
    if errors:
        lines += ['> 草稿：未通过报告校验，请结合节点结果查看缺失内容。', '']
    lines += [f"行业：{_md(report.get('industry_focus', '未提供'))}  ",
              f"研究期限：{_md(report.get('time_horizon', '未提供'))}  ",
              f"报告日期：{_md(report.get('report_date', '未提供'))}  ",
              f"模型生成评级：{_md(_RATINGS.get(report.get('overall_rating'), '未提供'))}",
              '', '## 核心投资论点', '', _md(report.get('investment_thesis', '未提供')), '']
    for name, label in _DIMENSIONS.items():
        item = _dimensions(report).get(name, {})
        if not isinstance(item, dict):
            continue
        confidence = item.get('confidence')
        lines += [f'## {label}', '', _md(item.get('summary', '未提供')), '']
        if isinstance(confidence, (float, int)) and not isinstance(confidence, bool) and math.isfinite(confidence):
            lines += [f'模型分析置信度：{confidence:.0%}（非收益或事件发生概率）', '']
    for field, title in [('supporting_evidence','支撑证据'),('risk_factors','风险因素')]:
        lines += [f'## {title}', '']
        lines += [f'- {_md(text)}' for text in _list(report, field)]
        lines.append('')
    lines += ['## 数据来源', '']
    for index, source in enumerate(_list(report, 'sources'), 1):
        url = _url(source)
        lines.append(f'{index}. [{_md(source)}](<{url}>)' if url else f'{index}. {_md(source)}')
    return '\n'.join(lines) + '\n'


def report_html(report, errors):
    def paragraph(value):
        return '<p>' + escape(_text(value)).replace('\n','<br>') + '</p>'
    title = escape(_text(report.get('research_topic', '投研报告')))
    body = f'<header><h1>{title}</h1>'
    for key, label in [('industry_focus','行业'),('time_horizon','研究期限'),('report_date','报告日期')]:
        body += paragraph(f"{label}：{report.get(key, '未提供')}")
    body += paragraph('模型生成评级：' + _RATINGS.get(report.get('overall_rating'), '未提供')) + '</header>'
    if errors:
        body += '<aside>草稿：未通过报告校验，请结合节点结果查看缺失内容。</aside>'
    body += '<section><h2>核心投资论点</h2>' + paragraph(report.get('investment_thesis', '未提供')) + '</section>'
    for name, label in _DIMENSIONS.items():
        item = _dimensions(report).get(name, {})
        if not isinstance(item, dict):
            continue
        body += f'<section><h2>{label}</h2>' + paragraph(item.get('summary', '未提供'))
        confidence = item.get('confidence')
        if isinstance(confidence, (float, int)) and not isinstance(confidence, bool) and math.isfinite(confidence):
            body += paragraph(f'模型分析置信度：{confidence:.0%}（非收益或事件发生概率）')
        body += '</section>'
    for field, label in [('supporting_evidence','支撑证据'),('risk_factors','风险因素')]:
        body += f'<section><h2>{label}</h2><ul>'
        body += ''.join('<li>' + escape(_text(v)) + '</li>' for v in _list(report, field))
        body += '</ul></section>'
    body += '<section><h2>数据来源</h2><ol>'
    for source in _list(report, 'sources'):
        url = _url(source)
        text = escape(_text(source))
        body += '<li>' + (f'<a href="{escape(url, quote=True)}" rel="noopener noreferrer">{text}</a>' if url else text) + '</li>'
    body += '</ol></section>'
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
body{{font-family:system-ui,"PingFang SC","Microsoft YaHei",sans-serif;background:#f2f5f8;color:#182333;line-height:1.8;margin:0}}
main{{max-width:960px;margin:32px auto;background:white;padding:40px;border-radius:16px}}
header{{border-bottom:3px solid #245d86;padding-bottom:20px}}h1{{line-height:1.3}}h2{{color:#245d86}}
section{{margin:28px 0}}li{{margin:8px 0}}a{{color:#245d86;overflow-wrap:anywhere}}
aside{{background:#fff3cd;padding:16px;margin-top:20px}}@media(max-width:600px){{main{{margin:0;padding:20px;border-radius:0}}}}
@media print{{body{{background:white}}main{{margin:0;max-width:none;padding:0}}}}
</style></head><body><main>{body}</main></body></html>'''


def render_report(task_id, record, render_id='final'):
    st.subheader(f'报告 · {task_id}')
    if record.get('status') in {'running','pending'}:
        st.info('报告任务正在排队或生成中，完成后可在这里阅读和下载。')
        return
    if record.get('status') not in {'completed','partial'}:
        st.info('报告尚未成功完成，暂无可下载的成品。请查看节点结果。')
        return
    raw = (record.get('result') or {}).get('final_report')
    if not raw:
        st.info('暂无最终报告，已保留节点输出。')
        return
    try:
        report, errors = prepare_report(raw)
    except ValueError as exc:
        st.warning(str(exc))
        return
    if record['status'] == 'partial' or errors:
        st.warning('这是部分完成的报告／草稿，请检查限制和节点结果。')
    if errors:
        with st.expander(f'报告校验提示 · {task_id}'):
            st.json(errors)
    # Preserve a draft label in exports even for non-validation partial outcomes.
    export_errors = errors or ([{'type':'partial_report'}] if record['status']=='partial' else [])
    markdown = report_markdown(report, export_errors)
    html = report_html(report, export_errors)
    suffix = '-draft' if export_errors else ''
    stem = re.sub(r'[^\w-]', '_', task_id)[:80] or 'report'
    st.caption('报告仅保留在当前会话的最近一轮结果中；新请求或新对话会替换/清空。下载可保留本地副本。')
    left, right = st.columns(2)
    left.download_button('下载 Markdown', markdown, file_name=f'{stem}{suffix}.md', mime='text/markdown',
                         key=f'report_md_{render_id}_{task_id}', on_click='ignore', width='stretch')
    right.download_button('下载 HTML', html, file_name=f'{stem}{suffix}.html', mime='text/html',
                          key=f'report_html_{render_id}_{task_id}', on_click='ignore', width='stretch')
    st.markdown(markdown, unsafe_allow_html=False)
