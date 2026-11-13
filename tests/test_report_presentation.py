import json
import pytest
from app.report_viewer import prepare_report, report_markdown, report_html


def test_exports_include_all_report_sections(valid_report):
    report,errors=prepare_report(json.dumps(valid_report,ensure_ascii=False))
    assert errors==[]
    md=report_markdown(report,errors)
    html=report_html(report,errors)
    for content in (md,html):
        assert valid_report['research_topic'] in content
        assert '核心投资论点' in content and '风险因素' in content
        assert '基本面' in content and '市场' in content and '新闻' in content and '分析师' in content
    assert '<html lang="zh-CN">' in html


def test_html_escapes_generated_content_and_unsafe_sources(valid_report):
    valid_report['research_topic']='<script>alert(1)</script>'
    valid_report['sources']=['javascript:alert(1)','https://example.com/?a=1&b=2','plain source']
    report,errors=prepare_report(valid_report)
    html=report_html(report,errors)
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
    assert 'href="javascript:' not in html
    assert 'a=1&amp;b=2' in html


def test_invalid_json_is_rejected_and_partial_report_is_labeled_draft(valid_report):
    with pytest.raises(ValueError): prepare_report('bad json')
    with pytest.raises(ValueError): prepare_report('[]')
    valid_report['sources']=[]
    report,errors=prepare_report(valid_report)
    assert errors and '草稿' in report_markdown(report,errors) and '草稿' in report_html(report,errors)


def test_malformed_dimensions_can_be_shown_as_draft_without_crashing(valid_report):
    valid_report['dimensions']=[]
    report,errors=prepare_report(valid_report)
    assert errors
    assert '草稿' in report_markdown(report,errors)
    assert '草稿' in report_html(report,errors)
