"""Historical input references are explicit, reusable and reauthorized without reading bytes."""
import base64
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.base import uid
from app.modules.attachments.models import Attachment
from app.modules.conversations.models import Conversation
from app.modules.deliverables.models import Deliverable, DeliverableRevision
from app.modules.executions.models import SandboxExecution
from app.modules.messages.models import Message
from app.modules.work.models import WorkItem, WorkMaterial
from _support.agent.builtin_execution import builtin_receipts, invoke, read
from _support.agent.business_actions import finish, runtime
from _support.agent.execution_evidence import followup
from _support.agent.sandbox_execution import run

pytestmark = pytest.mark.asyncio
DATA = b'id,value\n001,3\n002,5\n'


async def attachment(setup, sent, *, name='input.csv', who='employee'):
    settings, sessions, users, _ = setup
    identifier = uid()
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    (settings.media_dir / identifier).write_bytes(DATA)
    async with sessions.begin() as db:
        db.add(Attachment(id=identifier, company_id=users[who].company_id, owner_id=users[who].id,
                          message_id=sent['messageId'], kind='document', mime='text/csv', name=name,
                          size=len(DATA), sha256=hashlib.sha256(DATA).hexdigest(), extraction_revision=1))
    return identifier


async def test_followup_reuses_exact_versioned_inputs_with_names_without_loading_bytes(setup, builtin_receipts, monkeypatch):
    context, sent = await runtime(setup, '检查两份同名文件')
    identifiers = [await attachment(setup, sent) for _ in range(2)]
    original = await run(context, input_refs=[{'attachment_id': identifier} for identifier in identifiers])
    assert original['inputFiles'] == ['input.csv', '2-input.csv']
    await finish(context)
    context = await followup(setup, sent['conversationId'])
    # History metadata must not copy or parse the attachment again.
    with monkeypatch.context() as patch:
        def forbidden(*args, **kwargs):
            raise AssertionError('History must not read file bytes')
        patch.setattr(Path, 'read_bytes', forbidden)
        listing = await read(context)
        assert listing['items'][0]['inputCount'] == 2
        assert 'inputRefs' not in listing['items'][0]
        saved = await read(context, original['executionId'])
    references = [{'attachment_id': identifier, 'revision': 1} for identifier in identifiers]
    assert saved['inputRefs'] == references and saved['inputFiles'] == original['inputFiles']
    assert saved['inputState'] == 'available' and builtin_receipts.count == 1
    assert str(context.settings.media_dir) not in json.dumps(saved)
    rerun = await run(context, input_refs=saved['inputRefs'])
    assert rerun['state'] == 'succeeded' and rerun['inputFiles'] == original['inputFiles']
    assert all(base64.b64decode(item['data']) == DATA for item in builtin_receipts.bodies[-1]['inputs'])
    inspected = await invoke(context, 'inspect_table', source={'input_ref': saved['inputRefs'][0]})
    assert inspected['state'] == 'succeeded', inspected
    assert builtin_receipts.count == 3


async def test_no_input_execution_does_not_inherit_associated_sources_or_guess_old_refs(setup, builtin_receipts):
    context, sent = await runtime(setup, '读取材料后纯计算')
    identifier = await attachment(setup, sent)
    context.document_versions[identifier] = 1
    original = await run(context)
    async with context.sessions() as db:
        row = await db.get(SandboxExecution, original['executionId'])
        assert row.sources[0]['id'] == identifier and row.result['inputRefs'] == []
    await finish(context)
    context = await followup(setup, sent['conversationId'])
    saved = await read(context, original['executionId'])
    assert saved['inputRefs'] == saved['inputFiles'] == [] and saved['inputState'] == 'none'
    async with context.sessions.begin() as db:
        row = await db.get(SandboxExecution, original['executionId'])
        row.result = {key: value for key, value in row.result.items() if key not in ('inputRefs', 'inputFiles')}
    legacy = await read(context, original['executionId'])
    assert legacy['inputState'] == 'unrecorded' and legacy['inputRefs'] == legacy['inputFiles'] == []
    assert builtin_receipts.count == 1


@pytest.mark.parametrize('invalidated', ['deleted', 'revision', 'message', 'access', 'owner'])
async def test_attachment_reference_cannot_survive_source_invalidation(setup, builtin_receipts, invalidated):
    context, sent = await runtime(setup, '检查附件')
    identifier = await attachment(setup, sent)
    original = await run(context, input_refs=[{'attachment_id': identifier}])
    await finish(context)
    context = await followup(setup, sent['conversationId'])
    async with context.sessions.begin() as db:
        item = await db.get(Attachment, identifier)
        message = await db.get(Message, sent['messageId'])
        if invalidated == 'deleted':
            item.deleted = True
        elif invalidated == 'revision':
            item.extraction_revision += 1
        elif invalidated == 'message':
            message.deleted = True
        elif invalidated == 'access':
            message.access = {'team': True, 'actorId': context.owner_id, 'companyId': context.company_id, 'reads': {}}
        else:
            item.owner_id = setup[2]['peer'].id
    saved = await read(context, original['executionId'])
    assert saved.get('inputRefs', []) == []
    assert identifier not in json.dumps(saved) and builtin_receipts.count == 1


async def test_missing_file_is_unavailable_and_version_change_after_read_blocks_reuse(setup, builtin_receipts):
    context, sent = await runtime(setup, '检查附件')
    identifier = await attachment(setup, sent)
    original = await run(context, input_refs=[{'attachment_id': identifier}])
    await finish(context)
    context = await followup(setup, sent['conversationId'])
    saved = await read(context, original['executionId'])
    await finish(context)
    context = await followup(setup, sent['conversationId'])
    async with context.sessions.begin() as db:
        (await db.get(Attachment, identifier)).extraction_revision = 2
    denied = await run(context, input_refs=saved['inputRefs'])
    assert denied['state'] == 'conflict' and denied['httpStatus'] == 409 and '版本' in denied['message'] and builtin_receipts.count == 1
    async with context.sessions.begin() as db:
        (await db.get(Attachment, identifier)).extraction_revision = 1
    (context.settings.media_dir / identifier).unlink()
    missing = await read(context, original['executionId'])
    assert missing['inputState'] == 'unavailable' and missing['inputRefs'] == missing['inputFiles'] == []


@pytest.mark.parametrize('invalidation', ['revision', 'access', 'conversation', 'file'])
async def test_deliverable_input_is_reusable_only_while_exact_revision_remains_accessible(setup, builtin_receipts, invalidation):
    context, sent = await runtime(setup, '生成文件后作为输入')
    builtin_receipts.with_file = True
    output = await run(context)
    delivery = output['delivery']
    reference = {'deliverable_id': delivery['id'], 'revision': 1, 'file_id': delivery['files'][0]['id']}
    builtin_receipts.with_file = False
    original = await run(context, input_refs=[reference], step=2)
    await finish(context)
    context = await followup(setup, sent['conversationId'])
    saved = await read(context, original['executionId'])
    assert saved['inputRefs'] == [reference] and saved['inputState'] == 'available'
    reused = await invoke(context, 'inspect_table', source={'input_ref': saved['inputRefs'][0]})
    assert reused['state'] == 'succeeded'
    async with context.sessions.begin() as db:
        item = await db.get(Deliverable, delivery['id'])
        revision = await db.scalar(select(DeliverableRevision).where(
            DeliverableRevision.deliverable_id == item.id, DeliverableRevision.revision == 1))
        if invalidation == 'revision':
            await db.delete(revision)
        elif invalidation == 'access':
            item.access = {'team': True, 'actorId': context.owner_id, 'companyId': context.company_id, 'reads': {}}
        elif invalidation == 'conversation':
            other = Conversation(company_id=context.company_id, owner_id=context.owner_id)
            db.add(other)
            await db.flush()
            item.conversation_id = other.id
        else:
            revision.files = []
    unavailable = await read(context, original['executionId'])
    assert unavailable['state'] == 'failed' and unavailable['category'] == 'permission_denied' and 'inputRefs' not in unavailable
    assert 'stdout' not in unavailable and 'request' not in unavailable
    assert reference['file_id'] not in json.dumps(unavailable) and builtin_receipts.count == 3


async def test_work_material_uses_existing_work_authorization_and_removed_material_denies(setup, builtin_receipts):
    context, sent = await runtime(setup, '处理自己的工作材料')
    identifier = await attachment(setup, sent)
    async with context.sessions.begin() as db:
        item = await db.get(Attachment, identifier)
        item.message_id = None
        work = WorkItem(company_id=context.company_id, owner_id=context.owner_id, title='工作', content={})
        db.add(work)
        await db.flush()
        material = WorkMaterial(company_id=context.company_id, owner_id=context.owner_id, work_id=work.id, attachment_id=identifier)
        db.add(material)
        await db.flush()
        material_id = material.id
    original = await run(context, input_refs=[{'attachment_id': identifier}])
    assert original['state'] == 'succeeded', original
    await finish(context)
    context = await followup(setup, sent['conversationId'])
    saved = await read(context, original['executionId'])
    assert saved['inputRefs'] == [{'attachment_id': identifier, 'revision': 1}]
    assert (await invoke(context, 'inspect_table', source={'input_ref': saved['inputRefs'][0]}))['state'] == 'succeeded'
    async with context.sessions.begin() as db:
        (await db.get(WorkMaterial, material_id)).removed = True
    denied = await read(context, original['executionId'])
    assert denied['state'] == 'failed' and denied['category'] == 'permission_denied' and identifier not in json.dumps(denied)
    assert builtin_receipts.count == 2


@pytest.mark.parametrize('malformed', ['too_many', 'unknown_ref', 'invalid_name', 'missing_name', 'object_id'])
async def test_history_does_not_echo_malformed_input_metadata(setup, builtin_receipts, malformed):
    context, sent = await runtime(setup, '读取历史输入信息')
    original = await run(context)
    async with context.sessions.begin() as db:
        row = await db.get(SandboxExecution, original['executionId'])
        ref = {'attachment_id': 'not-a-source'}
        refs, names = [ref], ['input.csv']
        if malformed == 'too_many':
            refs, names = [ref] * 13, ['input.csv'] * 13
        elif malformed == 'unknown_ref':
            refs = [{'storageKey': '/private/host-path'}]
        elif malformed == 'invalid_name':
            names = ['/private/host-path']
        elif malformed == 'missing_name':
            names = []
        else:
            refs = [{'attachment_id': {'untrusted': 'object'}}]
        row.result = {**row.result, 'inputRefs': refs, 'inputFiles': names}
    saved = await read(context, original['executionId'])
    assert saved.get('inputState', saved['state']) == 'unavailable' and saved.get('inputRefs', []) == saved.get('inputFiles', []) == []
    assert 'host-path' not in json.dumps(saved) and builtin_receipts.count == 1
