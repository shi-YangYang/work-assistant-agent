"""Existing action authorization/receipts apply to batched checklist edits."""
import pytest
from app.agent.actions.operations import execute
from app.modules.work.content.checklist import checklist_items
from _support.agent.execution_permissions import mode_runtime
from _support.agent.business_actions import read_work
from _support.agent.work_execution_history import WorkJudge
from _support.work.work_records import create, key

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('mode', ['ask', 'auto', 'full'])
async def test_batch_creation_and_approval_are_stable_and_write_once(setup, mode):
    *_, clients = setup
    context, _ = await mode_runtime(setup, mode, '创建今日待办：收周报、打印简历、下午开会；备注打印机待检修')
    context.intent_model = WorkJudge()
    changes = {'title': '今日待办', 'bodyEdits': [
        {'action': 'append_checklist', 'items': [{'text': '收周报'}, {'text': '打印简历'}, {'text': '下午开会'}]},
        {'action': 'append', 'blocks': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': '备注打印机待检修'}]}]},
    ]}
    args = {'step': 1, 'action': 'create_work', 'changes': changes}
    first = await execute(context, **args)
    assert first['state'] == ('pending' if mode == 'ask' else 'succeeded'), first
    assert len(context.intent_model.inputs) == 1
    replay = await execute(context, **args)
    assert replay['id'] == first['id'] and replay['state'] == first['state']
    if mode == 'ask':
        approved = await clients['employee'].post('/api/v1/business-actions/' + first['id'] + '/confirm', json={'expectedRevision': first['revision']})
        assert approved.status_code == 200, approved.text
        first = approved.json()
        assert first['state'] == 'succeeded'
    work = (await clients['employee'].get('/api/v1/work-items/' + first['objectId'])).json()
    assert work['revision'] == 1 and work['summary'] == '' and work['status'] == 'in_progress'
    assert len(checklist_items(work['body'])) == 3
    assert work['bodyText'] == '☐ 收周报\n☐ 打印简历\n☐ 下午开会\n备注打印机待检修'
    assert work['history'][0]['origin'] == ('assistant_confirmed' if mode == 'ask' else 'assistant')


@pytest.mark.parametrize('mode', ['ask', 'auto', 'full'])
async def test_check_authorization_and_preview_see_item_text_and_real_state(setup, mode):
    *_, clients = setup
    response = await clients['employee'].post('/api/v1/work-items', json={'title': '今日待办', 'bodyEdits': [{'action': 'append_checklist', 'items': [{'text': '打印简历'}, {'text': '审核后交负责人确认'}]}]}, headers=key())
    assert response.status_code == 201, response.text
    work = response.json()
    context, _ = await mode_runtime(setup, mode, '把今日待办里的打印简历标记为完成，别的不要改')
    context.intent_model = WorkJudge()
    read = await read_work(context, work['id'])
    item = next(iter(checklist_items(read['body'])))
    args = {'step': 1, 'action': 'update_work', 'target_id': work['id'], 'expected_revision': 1, 'changes': {'bodyEdits': [{'action': 'set_checked', 'itemId': item, 'checked': True, 'blockId': read['body']['content'][0]['attrs']['id']}]}}
    result = await execute(context, **args)
    assert result['state'] == ('pending' if mode == 'ask' else 'succeeded'), result
    assert context.intent_model.inputs[0]['proposedOperation']['workContentChanges'] == [{**args['changes']['bodyEdits'][0], 'text': '打印简历', 'beforeChecked': False}]
    if mode == 'ask':
        assert result['preview']['changes']['bodyEdits'][0]['text'] == '打印简历'
        response = await clients['employee'].post('/api/v1/business-actions/' + result['id'] + '/confirm', json={'expectedRevision': result['revision']})
        assert response.status_code == 200, response.text
    else:
        assert (await execute(context, **args))['id'] == result['id']
    saved = (await clients['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert saved['revision'] == 2 and saved['status'] == 'in_progress'
    assert list(checklist_items(saved['body'])) == list(checklist_items(work['body']))
    assert [n['attrs']['checked'] for n in checklist_items(saved['body']).values()] == [True, False]
    assert len(context.intent_model.inputs) == 1


@pytest.mark.parametrize('mode', ['ask', 'auto', 'full'])
async def test_append_to_read_list_preserves_status_and_uses_one_authorization(setup, mode):
    *_, clients = setup
    response = await clients['employee'].post('/api/v1/work-items', json={'title': '待办', 'bodyEdits': [{'action': 'append_checklist', 'items': [{'text': '已办事项', 'checked': True}]}]}, headers=key())
    work = response.json()
    context, _ = await mode_runtime(setup, mode, '给待办的现有清单补充两项：确认后下单、16:30 寄出')
    context.intent_model = WorkJudge()
    read = await read_work(context, work['id'])
    edits = [{'action': 'append_checklist', 'blockId': read['body']['content'][0]['attrs']['id'], 'items': [{'text': '确认后下单'}, {'text': '16:30 寄出'}]}]
    args = {'step': 1, 'action': 'update_work', 'target_id': work['id'], 'expected_revision': 1, 'changes': {'bodyEdits': edits}}
    result = await execute(context, **args)
    assert result['state'] == ('pending' if mode == 'ask' else 'succeeded'), result
    assert (await execute(context, **args))['id'] == result['id']
    if mode == 'ask':
        preview = result['preview']['changes']['bodyEdits'][0]
        assert len(preview['blocks'][0]['content']) == 2
        assert preview['before'] == read['body']['content']
        response = await clients['employee'].post('/api/v1/business-actions/' + result['id'] + '/confirm', json={'expectedRevision': result['revision']})
        assert response.status_code == 200, response.text
    saved = (await clients['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert saved['revision'] == 2 and saved['status'] == work['status']
    assert len(saved['body']['content']) == 1
    assert saved['body']['content'][0]['content'][0] == work['body']['content'][0]['content'][0]
    assert saved['bodyText'] == '☑ 已办事项\n☐ 确认后下单\n☐ 16:30 寄出'
    assert len(context.intent_model.inputs) == 1


async def test_waiting_approval_never_overwrites_new_work_version(setup):
    *_, clients = setup
    response = await clients['employee'].post('/api/v1/work-items', json={'title': '待办', 'bodyEdits': [{'action': 'append_checklist', 'items': [{'text': '寄合同'}]}]}, headers=key())
    work = response.json()
    context, _ = await mode_runtime(setup, 'ask', '把寄合同标记完成，先让我确认')
    context.intent_model = WorkJudge()
    await read_work(context, work['id'])
    item = next(iter(checklist_items(work['body'])))
    pending = await execute(context, step=1, action='update_work', target_id=work['id'], expected_revision=1, changes={'bodyEdits': [{'action': 'set_checked', 'itemId': item, 'checked': True}]})
    assert pending['state'] == 'pending'
    changed = await clients['employee'].patch('/api/v1/work-items/' + work['id'], json={'expectedRevision': 1, 'bodyEdits': [{'action': 'append_checklist', 'items': [{'text': '另一项'}]}]}, headers=key())
    assert changed.status_code == 200
    confirmation = await clients['employee'].post('/api/v1/business-actions/' + pending['id'] + '/confirm', json={'expectedRevision': pending['revision']})
    assert confirmation.status_code == 409, confirmation.text
    latest = (await clients['employee'].get('/api/v1/work-items/' + work['id'])).json()
    assert latest['revision'] == 2
    assert not checklist_items(latest['body'])[item]['attrs']['checked']
