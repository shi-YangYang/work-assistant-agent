"""Completion checks work-record receipts against saved update/file identities."""
import json
import hashlib
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage

from app.agent.actions.operations import execute
from app.agent.completion.review.reply_review import check_issues, review_reply
from app.agent.completion.recovery.response_repair import repair_response
from app.agent.completion.evidence.work_receipts import work_record_evidence
from app.modules.operations.receipts import receipt_summary
from _support.agent.business_actions import read_work
from _support.materials.documents import upload
from _support.agent.execution_permissions import mode_runtime
from _support.agent.work_execution_history import WorkJudge
from _support.work.work_records import create, key

pytestmark = pytest.mark.asyncio


async def test_reply_review_and_repair_get_saved_material_mapping_and_independent_progress(setup):
    _, sessions, users, clients = setup
    client = clients['employee']
    work = await create(client)
    attachment = await upload(client, '客户需求.txt', b'controlled requirements', 'text/plain')
    context, _ = await mode_runtime(setup, 'full', '给《客户官网》追加正文“先完成移动端方案”，记录进展“已经收到客户需求”，保存客户需求文件。')
    context.intent_model = WorkJudge()
    await read_work(context, work['id'])
    changes = [
        {'bodyEdits': [{'action': 'append', 'blocks': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': '先完成移动端方案'}]}]}]},
        {'update': {'action': 'create', 'text': '已经收到客户需求'}},
        {'materials': [{'attachmentId': attachment['id']}]},
    ]
    cards = []
    for step, change in enumerate(changes, 1):
        result = await execute(context, step=step, action='update_work', target_id=work['id'], expected_revision=step, changes=change)
        assert result['state'] == 'succeeded', result
        cards.append(result)
    async with sessions() as db:
        evidence = await work_record_evidence(db, users['employee'], cards)
    assert len(evidence) == 3
    progress = evidence[1]['progressUpdate']
    assert progress['id'] == cards[1]['updateId'] and progress['text'] == '已经收到客户需求'
    assert progress['revision'] == 1 and not progress['deleted']
    assert cards[1]['details']['bodyText'] == cards[0]['details']['bodyText']
    material = evidence[2]['materials'][0]
    assert material['source'] == {'attachmentId': attachment['id']}
    assert material['materialId'] == cards[2]['materialIds'][0]
    assert len({material['materialId'], material['savedAttachmentId'], attachment['id']}) == 3
    assert material['name'] == '客户需求.txt' and material['sha256'] == hashlib.sha256(b'controlled requirements').hexdigest()
    answer = '正文已追加，进展已经收到客户需求已保存，客户需求.txt 已保存到工作材料。'
    captured = []

    class Judge:
        async def ainvoke(self, messages):
            payload = json.loads(messages[-1].content)
            captured.append(payload)
            assert payload['workRecordEvidence'] == evidence
            return AIMessage(content='{"issues":[]}' if payload.get('task') else answer)

    reviewed = await review_reply(context, answer, model=Judge())
    assert reviewed.verified and reviewed.text == answer and not reviewed.needs_response
    assert await repair_response(context, answer, '只精简措辞', model=Judge()) == answer
    assert len(captured) == 2
    summary = receipt_summary(cards)
    assert summary == '更新工作正文《客户官网》：已完成；记录工作进展《客户官网》：已完成；保存工作材料《客户官网》：已完成。'

    # Later edits/removal do not substitute current text for a saved receipt.
    path = '/api/v1/work-items/' + work['id']
    corrected = await client.patch(path + '/updates/' + progress['id'], json={'expectedRevision': 4, 'expectedUpdateRevision': 1, 'text': '更正后的进展'}, headers=key())
    assert corrected.status_code == 200, corrected.text
    removed = await client.request('DELETE', path + '/materials/' + material['materialId'], json={'expectedRevision': 5, 'expectedMaterialRevision': 1}, headers=key())
    assert removed.status_code == 200, removed.text
    async with sessions() as db:
        assert await work_record_evidence(db, users['employee'], cards) == evidence
        failed = [{**card, 'state': 'failed'} for card in cards]
        assert await work_record_evidence(db, users['employee'], failed) == []
        assert await work_record_evidence(db, users['peer'], cards) == [
            {key: value for key, value in row.items() if key != 'progressUpdate'} | {'materials': []} for row in evidence]
        wrong = deepcopy(cards[2])
        wrong['objectId'] = 'another-work'
        assert (await work_record_evidence(db, users['employee'], [wrong]))[0]['materials'] == []
        mismatched_object = {**cards[1], 'objectRevision': cards[1]['objectRevision'] + 1}
        assert (await work_record_evidence(db, users['employee'], [mismatched_object]))[0]['progressUpdate'] == progress
        wrong = {**cards[1], 'updateWorkRevision': cards[1]['updateWorkRevision'] + 1}
        assert 'progressUpdate' not in (await work_record_evidence(db, users['employee'], [wrong]))[0]
        legacy_wrong = {key: value for key, value in mismatched_object.items() if key != 'updateWorkRevision'}
        assert 'progressUpdate' not in (await work_record_evidence(db, users['employee'], [legacy_wrong]))[0]


async def test_rejected_list_claim_removes_only_its_empty_bullet_and_keeps_error_visible():
    answer = '- 正文已保存。\n- 错误的文件已保存。\n- 进展已保存。\n\n保留解释。'
    verdict = {'issues': [{'kind': 'fact', 'quote': '错误的文件已保存。', 'reason': '回执对应另一个源文件', 'receipt_ids': ['saved'], 'evidence': []}]}
    reviewed = check_issues(answer, json.dumps(verdict, ensure_ascii=False), [], [{'id': 'saved'}])
    assert reviewed.text == '- 正文已保存。\n- 进展已保存。\n\n保留解释。'
    assert reviewed.needs_response and reviewed.response_reason == '回执对应另一个源文件'
    assert not reviewed.execution_claims
