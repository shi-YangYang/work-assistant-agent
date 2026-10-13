"""Checklist structure, exact edits and REST persistence stay in one work record."""
import copy
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from app.modules.work.content.checklist import compatible_body, checklist_items, edit_previews
from app.modules.work.content.document import WorkDocument, edit_document, plain_text
from app.modules.work.models import WorkItem, WorkRevision
from app.modules.reports.generation.sources import report_plan_contexts
from app.modules.team.sources import bounded_content
from _support.work.work_records import create, body, key


def checklist(*texts):
    return {'schemaVersion': 1, 'content': [{'type': 'taskList', 'content': [
        {'type': 'taskItem', 'attrs': {'checked': False}, 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': text}]}]}
        for text in texts
    ]}]}


def test_generation_and_atomic_edits_preserve_structure_and_identity():
    initial = WorkDocument.model_validate(body('备注：打印机待检修')).model_dump()
    first = edit_document(initial, [{'action': 'append_checklist', 'items': [{'text': '打印简历'}, {'text': '审核后交负责人确认', 'checked': True}]}])
    items = list(checklist_items(first))
    second = edit_document(first, [{'action': 'append_checklist', 'items': [{'text': '寄送合同'}]}, {'action': 'set_checked', 'itemId': items[0], 'checked': True}])
    assert second['content'][0] == first['content'][0]
    assert list(checklist_items(second))[:2] == items
    assert plain_text(second) == '备注：打印机待检修\n☑ 打印简历\n☑ 审核后交负责人确认\n☐ 寄送合同'
    before = copy.deepcopy(second)
    with pytest.raises(ValueError):
        edit_document(second, [{'action': 'set_checked', 'itemId': items[0], 'checked': False}, {'action': 'set_checked', 'itemId': 'missing', 'checked': True}])
    assert second == before
    converted = edit_document(initial, [{'action': 'replace_checklist', 'blockId': 'first', 'items': [{'text': '检查打印机'}]}])
    assert converted['content'][0]['attrs']['id'] == 'first'
    assert plain_text(converted) == '☐ 检查打印机'
    with pytest.raises(ValueError, match='已有清单'):
        edit_document(first, [{'action': 'replace_checklist', 'blockId': first['content'][1]['attrs']['id'], 'items': [{'text': '不能重置状态'}]}])


def test_append_to_selected_checklist_preserves_existing_items_and_precise_preview():
    original = edit_document(body('备注保留'), [{'action': 'append_checklist', 'items': [{'text': '已完成', 'checked': True}, {'text': '待完成'}]}])
    target = original['content'][1]['attrs']['id']
    edits = [{'action': 'append_checklist', 'blockId': target, 'items': [{'text': '确认后下单'}, {'text': '16:30 寄出'}]}]
    updated = edit_document(original, edits)
    assert updated['content'][0] == original['content'][0]
    assert len(updated['content']) == 2 and updated['content'][1]['attrs']['id'] == target
    assert updated['content'][1]['content'][:2] == original['content'][1]['content']
    assert len(checklist_items(updated)) == 4
    previews = edit_previews(original, edits)
    assert previews == edit_previews(original, edits)
    assert previews[0]['before'] == [original['content'][1]]
    assert plain_text({'content': previews[0]['blocks']}) == '☐ 确认后下单\n☐ 16:30 寄出'
    for block in ('missing', 'first', next(iter(checklist_items(original)))):
        with pytest.raises(ValueError, match='目标清单'):
            edit_document(original, [{**edits[0], 'blockId': block}])
    for conflicting in (
        edits[0],
        {'action': 'remove', 'blockId': target},
    ):
        with pytest.raises(ValueError):
            edit_document(original, [*edits, conflicting])
    existing = next(iter(checklist_items(original)))
    toggled = edit_document(original, [*edits, {'action': 'set_checked', 'itemId': existing, 'checked': False}])
    assert len(checklist_items(toggled)) == 4 and not checklist_items(toggled)[existing]['attrs']['checked']


def test_checked_block_constraint_accepts_nested_items_and_disjoint_batch_edits():
    raw = checklist('第一项', '第二项')
    nested = checklist('嵌套事项')['content'][0]
    nested['attrs'] = {'id': 'nested-list'}
    raw['content'][0]['content'][0]['content'].append(nested)
    original = WorkDocument.model_validate(raw).model_dump()
    target = original['content'][0]['attrs']['id']
    first, child, _ = checklist_items(original)
    edits = [
        {'action': 'append_checklist', 'blockId': target, 'items': [{'text': '新增'}]},
        {'action': 'set_checked', 'blockId': target, 'itemId': first, 'checked': True},
        {'action': 'set_checked', 'blockId': target, 'itemId': child, 'checked': True},
    ]
    for batch in (edits, edits[::-1]):
        updated = edit_document(original, batch)
        assert len(checklist_items(updated)) == 4
        assert [item['attrs']['checked'] for item in checklist_items(updated).values()] == [True, True, False, False]
        assert edit_previews(original, batch) == edit_previews(original, batch)
    assert not any(item['attrs']['checked'] for item in checklist_items(original).values())
    for action in ('remove', 'replace', 'replace_checklist'):
        conflicting = {'action': action, 'blockId': target}
        if action == 'replace':
            conflicting['blocks'] = body('替换')['content']
        elif action == 'replace_checklist':
            conflicting['items'] = [{'text': '替换'}]
        for batch in ([edits[2], conflicting], [conflicting, edits[2]]):
            with pytest.raises(ValueError, match='重叠'):
                edit_document(original, batch)
    with pytest.raises(ValueError, match='指定清单'):
        edit_document(original, [{**edits[2], 'blockId': 'nested-list'}])


def test_checked_block_constraint_rejects_wrong_stale_and_non_list_targets():
    raw = body('备注')
    raw['content'].extend(checklist('第一组')['content'] + checklist('第二组')['content'])
    original = WorkDocument.model_validate(raw).model_dump()
    first, _ = checklist_items(original)
    for target in ('missing', 'first', original['content'][2]['attrs']['id'], first):
        with pytest.raises(ValueError, match='指定清单'):
            edit_document(original, [{'action': 'set_checked', 'blockId': target, 'itemId': first, 'checked': True}])


@pytest.mark.parametrize('edit', [
    {'action': 'append_checklist', 'items': []},
    {'action': 'append_checklist', 'items': [{'text': '   '}]},
    {'action': 'append_checklist', 'items': [{'text': 'x', 'checked': 'false'}]},
    {'action': 'append_checklist', 'items': [{'text': 'x', 'checked': 1}]},
    {'action': 'append_checklist', 'items': [{'text': 'x', 'id': 'foreign'}]},
    {'action': 'append_checklist', 'items': [{'text': 'x' * 12001}]},
    {'action': 'append_checklist', 'items': [{'text': 'x'}], 'blocks': []},
    {'action': 'append_checklist', 'items': [{'text': 'x'}], 'blockId': None},
    {'action': 'append_checklist', 'items': [{'text': 'x'}], 'blockId': ''},
    {'action': 'set_checked', 'itemId': 'a', 'checked': None},
    {'action': 'set_checked', 'itemId': 'a', 'checked': True, 'text': 'x'},
    {'action': 'set_checked', 'itemId': 'a', 'checked': True, 'blockId': None},
    {'action': 'set_checked', 'itemId': 'a', 'checked': True, 'blockId': ''},
    {'action': 'remove', 'blockId': 'first', 'checked': False},
])
def test_invalid_edit_schema_is_rejected(edit):
    with pytest.raises(ValueError):
        edit_document(body(), [edit])


def test_duplicate_overlapping_and_duplicate_document_ids_rejected():
    doc = WorkDocument.model_validate(checklist('甲', '乙')).model_dump()
    first, second = list(checklist_items(doc))
    for edits in (
        [{'action': 'set_checked', 'itemId': first, 'checked': value} for value in (True, False)],
        [{'action': 'remove', 'blockId': doc['content'][0]['attrs']['id']}, {'action': 'set_checked', 'itemId': first, 'checked': True}],
    ):
        with pytest.raises(ValueError):
            edit_document(doc, edits)
    duplicate = copy.deepcopy(doc)
    checklist_items(duplicate)[second]['attrs']['id'] = first
    with pytest.raises(ValueError, match='重复'):
        WorkDocument.model_validate(duplicate)


def test_legacy_identity_and_preview_are_repeatable_without_mutating_input():
    raw = checklist('同名', '同名')
    original = copy.deepcopy(raw)
    first = compatible_body(raw, 'work-one')
    assert first == compatible_body(raw, 'work-one') and raw == original
    assert set(checklist_items(first)).isdisjoint(checklist_items(compatible_body(raw, 'work-two')))
    edits = [{'action': 'append_checklist', 'items': [{'text': '新事项'}]}]
    assert edit_previews(first, edits) == edit_previews(first, edits)
    assert '☐ 同名\n☐ 同名' == bounded_content({'body': raw})['bodyText']
    source = SimpleNamespace(id='source', work_id='work', revision=1, content={'body': raw, 'bodyText': '旧无状态缓存'})
    assert report_plan_contexts([source])[0]['bodyText'] == '☐ 同名\n☐ 同名'


@pytest.mark.asyncio
async def test_checklist_writes_replay_conflict_noop_and_owned_permissions(setup):
    _, sessions, _, clients = setup
    client = clients['employee']
    initial = await create(client, body=checklist('打印简历', '审核后交负责人确认'), status='blocked', blocker='打印机故障', nextStep='下午开会', dueDate='2026-10-12')
    path = '/api/v1/work-items/' + initial['id']
    identifiers = list(checklist_items(initial['body']))
    payload = {'expectedRevision': 1, 'bodyEdits': [{'action': 'set_checked', 'itemId': identifiers[0], 'checked': True}]}
    headers = key()
    first = await client.patch(path, json=payload, headers=headers)
    assert first.status_code == 200, first.text
    updated = first.json()['work']
    assert updated['revision'] == 2
    assert (await client.patch(path, json=payload, headers=headers)).json() == first.json()
    assert (await client.patch(path, json=payload, headers=key())).status_code == 409
    payload['expectedRevision'] = 2
    noop = await client.patch(path, json=payload, headers=key())
    assert noop.json()['work']['revision'] == 2, noop.text
    for role in ('peer', 'outsider', 'admin'):
        assert (await clients[role].patch(path, json=payload, headers=key())).status_code == 404
    payload['bodyEdits'].append({'action': 'set_checked', 'itemId': identifiers[1], 'checked': True})
    completed = (await client.patch(path, json=payload, headers=key())).json()['work']
    for name in ('status', 'blocker', 'nextStep', 'dueDate', 'summary'):
        assert completed[name] == initial[name]
    current = (await client.get(path)).json()
    historical = (await client.get(path + '?revision=1')).json()
    assert all(node['attrs']['checked'] for node in checklist_items(current['body']).values())
    assert not any(node['attrs']['checked'] for node in checklist_items(historical['body']).values())
    assert current['history'][0]['origin'] == 'manual'
    async with sessions() as db:
        assert len((await db.scalars(select(WorkRevision).where(WorkRevision.work_id == initial['id']))).all()) == 3


@pytest.mark.asyncio
async def test_append_existing_list_replays_once_and_rejects_foreign_block_atomically(setup):
    *_, clients = setup
    client = clients['employee']
    original = await create(client, body=checklist('保持已选', '待完成'))
    path = '/api/v1/work-items/' + original['id']
    foreign = await create(client, title='其他工作', body=checklist('其他清单'))
    payload = {'expectedRevision': 1, 'bodyEdits': [
        {'action': 'set_checked', 'itemId': next(iter(checklist_items(original['body']))), 'checked': True},
        {'action': 'append_checklist', 'blockId': foreign['body']['content'][0]['attrs']['id'], 'items': [{'text': '未授权追加'}]},
    ]}
    rejected = await client.patch(path, json=payload, headers=key())
    assert rejected.status_code == 422, rejected.text
    assert (await client.get(path)).json()['revision'] == 1
    headers = key()
    payload['bodyEdits'] = [{'action': 'append_checklist', 'blockId': original['body']['content'][0]['attrs']['id'], 'items': [{'text': '新增事项'}]}]
    added = await client.patch(path, json=payload, headers=headers)
    assert added.status_code == 200, added.text
    assert (await client.patch(path, json=payload, headers=headers)).json() == added.json()
    current = added.json()['work']
    assert current['revision'] == 2 and len(current['body']['content']) == 1
    assert current['body']['content'][0]['content'][:2] == original['body']['content'][0]['content']
    assert len(checklist_items(current['body'])) == 3


@pytest.mark.asyncio
async def test_checked_block_constraint_rejects_foreign_or_deleted_blocks_without_partial_write(setup):
    *_, clients = setup
    client = clients['employee']
    raw = checklist('第一项', '第二项')
    raw['content'].extend(checklist('另一组')['content'])
    original = await create(client, body=raw)
    foreign = await create(client, title='其他工作', body=checklist('其他事项'))
    path = '/api/v1/work-items/' + original['id']
    first, second, _ = checklist_items(original['body'])
    block = original['body']['content'][0]['attrs']['id']
    first_edit = {'action': 'set_checked', 'itemId': first, 'checked': True, 'blockId': block}
    for wrong in ('deleted-block', original['body']['content'][1]['attrs']['id'], foreign['body']['content'][0]['attrs']['id']):
        payload = {'expectedRevision': 1, 'bodyEdits': [first_edit, {'action': 'set_checked', 'itemId': second, 'checked': True, 'blockId': wrong}]}
        rejected = await client.patch(path, json=payload, headers=key())
        assert rejected.status_code == 422, rejected.text
        current = (await client.get(path)).json()
        assert current['revision'] == 1 and current['body'] == original['body']
    payload['bodyEdits'][1]['blockId'] = block
    accepted = await client.patch(path, json=payload, headers=key())
    assert accepted.status_code == 200, accepted.text
    current = accepted.json()['work']
    assert current['revision'] == 2
    assert [item['attrs']['checked'] for item in checklist_items(current['body']).values()] == [True, True, False]


@pytest.mark.asyncio
async def test_read_legacy_does_not_write_and_bad_batch_does_not_partially_save(setup):
    _, sessions, _, clients = setup
    client = clients['employee']
    initial = await create(client)
    path = '/api/v1/work-items/' + initial['id']
    raw = checklist('旧事项', '保留事项')
    async with sessions.begin() as db:
        row = await db.get(WorkItem, initial['id'])
        row.content = {**row.content, 'body': raw, 'bodyText': '旧事项保留事项'}
    current = (await client.get(path)).json()
    assert current == (await client.get(path)).json()
    async with sessions() as db:
        assert (await db.get(WorkItem, initial['id'])).content['body'] == raw
    ids = list(checklist_items(current['body']))
    other = await create(client, title='另一项工作', body=checklist('其他事项'))
    foreign = next(iter(checklist_items(other['body'])))
    for target in ('missing', foreign):
        response = await client.patch(path, json={'expectedRevision': 1, 'bodyEdits': [{'action': 'set_checked', 'itemId': ids[0], 'checked': True}, {'action': 'set_checked', 'itemId': target, 'checked': True}]}, headers=key())
        assert response.status_code == 422, response.text
    assert (await client.get(path)).json()['revision'] == 1
    noop = await client.patch(path, json={'expectedRevision': 1, 'bodyEdits': [{'action': 'set_checked', 'itemId': ids[0], 'checked': False}]}, headers=key())
    assert noop.json()['work']['revision'] == 1, noop.text
    saved = await client.patch(path, json={'expectedRevision': 1, 'bodyEdits': [{'action': 'set_checked', 'itemId': ids[0], 'checked': True}]}, headers=key())
    assert saved.status_code == 200, saved.text
    assert list(checklist_items(saved.json()['work']['body'])) == ids
    async with sessions() as db:
        assert list(checklist_items((await db.get(WorkItem, initial['id'])).content['body'])) == ids


@pytest.mark.asyncio
async def test_reorder_edit_copy_and_recreate_preserve_live_identity_only(setup):
    *_, clients = setup
    client = clients['employee']
    initial = await create(client, body=checklist('甲', '乙'))
    path = '/api/v1/work-items/' + initial['id']
    ids = list(checklist_items(initial['body']))
    edited = copy.deepcopy(initial['body'])
    edited['content'][0]['content'].reverse()
    edited['content'][0]['content'][0]['content'][0]['content'][0]['text'] = '乙改名'
    response = await client.patch(path, json={'expectedRevision': 1, 'body': edited}, headers=key())
    assert response.status_code == 200, response.text
    current = response.json()['work']
    assert list(checklist_items(current['body'])) == ids[::-1]
    copy_item = copy.deepcopy(current['body']['content'][0]['content'][0])
    copy_item['attrs']['id'] = 'new-editor-id'
    current['body']['content'][0]['content'].append(copy_item)
    headers = key()
    payload = {'expectedRevision': 2, 'body': current['body']}
    added = await client.patch(path, json=payload, headers=headers)
    assert added.status_code == 200, added.text
    assert (await client.patch(path, json=payload, headers=headers)).json() == added.json()
    copied_id = list(checklist_items(added.json()['work']['body']))[-1]
    assert copied_id not in [*ids, 'new-editor-id']
    without = copy.deepcopy(added.json()['work']['body'])
    removed = without['content'][0]['content'].pop(0)
    deleted = await client.patch(path, json={'expectedRevision': 3, 'body': without}, headers=key())
    assert deleted.status_code == 200
    without['content'][0]['content'].append(removed)
    recreated = await client.patch(path, json={'expectedRevision': 4, 'body': without}, headers=key())
    assert recreated.status_code == 200
    assert ids[1] not in checklist_items(recreated.json()['work']['body'])
    invalid = await client.patch(path, json={'expectedRevision': 5, 'bodyEdits': [{'action': 'set_checked', 'itemId': ids[1], 'checked': True}]}, headers=key())
    assert invalid.status_code == 422
