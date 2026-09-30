"""Display summaries are bounded projections, independent of execution identity."""
import json
from types import SimpleNamespace
import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from app.agent.prompts.policies import ALLOWED_TOOLS, TEAM_TOOL_NAMES
from app.agent.runtime.progress import model_phase, tool_presentation
from app.agent.runtime.progress.tools import LABELS, text
from app.agent.runtime.tool_nodes import REPLAYABLE_TOOLS, tool_node
from app.tasks.nodes.node_state import node_dtos
from test_task_retry import enabled, fast_nodes


def result(value, name='get_work_item'):
    return ToolMessage(content=json.dumps(value, ensure_ascii=False), tool_call_id='call', name=name)


def test_every_current_tool_has_a_controlled_label():
    assert ALLOWED_TOOLS | TEAM_TOOL_NAMES <= LABELS.keys()
    assert tool_presentation('future_tool', {'code': 'never display'}) == ('执行操作', {'type': 'operation'})


@pytest.mark.parametrize('name,args,label,subject', [
    ('find_work_items', {'query': '上线 Web'}, '查找工作', '上线 Web'),
    ('find_work_items', {'query': '', 'status': 'blocked'}, '查找工作', '我的工作 · 有阻碍'),
    ('query_reports', {'kind': 'weekly', 'period': '2026-09-21'}, '查找报告', '周报 · 2026-09-21'),
    ('web_search', {'query': '北京今日新闻'}, '搜索资料', '北京今日新闻'),
    ('web_fetch', {'url': 'https://user:secret@example.com/news?q=secret#private'}, '读取网页', 'example.com'),
    ('export_table', {'filename': '/work/output/工作清单.xlsx'}, '导出表格', '工作清单.xlsx'),
    ('create_document', {'filename': '实施计划.docx'}, '生成文档', '实施计划.docx'),
    ('create_chart', {'title': '销售趋势'}, '生成图表', '销售趋势'),
    ('run_python', {'title': '计算季度同比', 'code': 'super secret'}, '运行代码', '计算季度同比'),
    ('execute_business_action', {'action': 'create_work', 'changes': {'title': '上线 Web'}}, '创建工作', '上线 Web'),
    ('query_team_business', {'kind': 'report', 'employee_name': '张三'}, '查询团队报告', '张三'),
])
def test_safe_input_subjects(name, args, label, subject):
    assert tool_presentation(name, args) == (label, {'type': 'operation', 'subject': subject})


def test_summary_uses_only_authorized_result_metadata():
    assert tool_presentation('get_work_item', {'work_id': 'secret'})[1] == {'type': 'operation'}
    assert tool_presentation('get_work_item', {}, result({'title': '登录页优化', 'content': 'private'}))[1]['subject'] == '登录页优化'
    assert tool_presentation('inspect_table', {}, result({'inputFiles': ['季度销售.xlsx']}))[1]['subject'] == '季度销售.xlsx'
    assert tool_presentation('read_document', {}, result({'attachment': {'name': '需求说明.pdf'}}))[1]['subject'] == '需求说明.pdf'
    assert tool_presentation('web_fetch', {'url': 'https://example.com'}, result({'title': '新闻标题'}))[1]['subject'] == '新闻标题'
    for value in ({'state': 'unavailable', 'title': 'private'}, {'category': 'permission_denied', 'title': 'private'}, {'error': 'bad', 'title': 'private'}):
        assert 'subject' not in tool_presentation('get_work_item', {}, result(value))[1]
    assert tool_presentation('read_file', {'file_path': '/internal/secret/file.txt'})[1] == {'type': 'operation'}
    assert tool_presentation('get_business_actions', {}, result([]))[1] == {'type': 'activity'}


def test_summary_bounds_and_plain_text():
    value = text('你好\u202e\x00\n' + '甲' * 100)
    assert len(value) == 60 and value.endswith('…') and '\u202e' not in value
    assert text('https://name:password@example.com/path?api_key=secret#token') == 'example.com'
    assert text('/home/user/private.txt 67bfd2b8-06ca-4b05-841c-5c8b8d4d12c3') == ''
    assert text({'title': 'not text'}) == ''
    assert text('<script>hello</script>') == '<script>hello</script>'  # React renders plain text, never HTML.


def test_phases_use_the_current_turn_not_historical_tools_or_reasoning():
    tool = result({'title': '工作'})
    assert model_phase([tool, HumanMessage(content='新问题', id='job:j')], 'j') == '理解请求'
    assert model_phase([HumanMessage(content='问题'), tool], 'j') == '整理工具结果'
    assert model_phase([HumanMessage(content='修复', id='delivery-repair:j')], 'j') == '完善答复'
    assert model_phase([], 'j') == '处理请求'


def test_optional_presentation_serializes_without_rewriting_old_records():
    rows = [{'id': 'old', 'kind': 'model', 'label': '思考中', 'state': 'succeeded', 'attempts': 1, 'scope': 's'},
            {'id': 'new', 'kind': 'tool', 'label': '查找工作', 'state': 'succeeded', 'attempts': 1, 'scope': 's',
             'presentation': {'type': 'operation', 'subject': '上线 Web'}}]
    job = SimpleNamespace(id='job', attempt=1, fence=1, state='succeeded', error='', feedback={}, result={'nodeExecution': {'scope': 's', 'nodes': rows}})
    values = node_dtos(job)
    assert 'presentation' not in values[0]
    assert values[1]['presentation'] == rows[1]['presentation']
    assert rows[0]['label'] == '思考中'


@pytest.mark.asyncio
async def test_result_enrichment_and_cached_replay_keep_one_stable_node(setup, fast_nodes):
    context, _ = await enabled(setup)
    request = SimpleNamespace(tool_call={'id': 'call', 'name': 'get_work_item', 'args': {'work_id': 'only-id'}}, state={'messages': []})
    calls = []
    async def operation():
        calls.append(1)
        return result({'title': '授权后的名称'})
    await tool_node(context, request, operation)
    await tool_node(context, request, operation)
    from app.tasks.models import Job
    async with context.sessions() as db:
        job = await db.get(Job, context.job_id)
        rows = node_dtos(job)
    assert calls == [1]
    assert len(rows) == 1 and rows[0]['attempts'] == 1
    assert rows[0]['label'] == '读取工作' and rows[0]['presentation']['subject'] == '授权后的名称'
    client = setup[3]['employee']
    query = await client.get(f'/api/v1/jobs/{context.job_id}')
    feedback = await client.get(f'/api/v1/jobs/{context.job_id}/feedback')
    assert query.status_code == feedback.status_code == 200
    assert query.json()['nodes'] == feedback.json()['nodes'] == rows


def test_display_catalog_does_not_expand_replay_safety(monkeypatch):
    assert 'finish_task' in LABELS and 'finish_task' not in REPLAYABLE_TOOLS
    assert ALLOWED_TOOLS | TEAM_TOOL_NAMES == REPLAYABLE_TOOLS | {'finish_task'}
    monkeypatch.setitem(LABELS, 'future_write', '新增动作')
    assert 'future_write' not in REPLAYABLE_TOOLS
