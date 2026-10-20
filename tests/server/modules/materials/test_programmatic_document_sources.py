"""Deterministic transport tests; no claims about real model answer quality."""
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from _support.http.management import conversation, message
from _support.materials.documents import running_context, upload, run
from app.agent.context.document_input import preload_documents, project_document_messages, project_page_markers
from app.agent.runtime.model import BoundedChatModel
from app.agent.tools.resources.documents import read_document_result
from app.modules.attachments.documents import delivered_citations
from app.modules.attachments.models import Attachment
from app.tasks.context import InputChanged
from app.tasks.models import Job
from app.tasks.processing.documents import prepare_document

pytestmark = pytest.mark.asyncio


def table_messages(receipt):
    return [AIMessage(content='', tool_calls=[{'name': 'inspect_table', 'args': {}, 'id': 'table', 'type': 'tool_call'}]),
            ToolMessage(content=receipt, name='inspect_table', tool_call_id='table')]


async def inspected_table(setup, monkeypatch):
    from dataclasses import replace
    from app.agent.tools.sandbox.tables import inspect_table
    from app.modules.executions.builtin.schemas import TableSource
    settings, sessions, users, clients = setup
    item = await upload(clients['employee'], 'expenses.csv', b'department,amount\nAdmin,72\nProject,16\n')
    sent = await message(clients['employee'], await conversation(clients['employee']), 'Summarize table', [item['id']])
    context = await running_context(settings, sessions, users['employee'], sent)
    await prepare_document(context, item['id'])
    context.settings = replace(context.settings, sandbox_url='http://owned-sandbox', sandbox_token='controlled')
    class TableClient:
        def __init__(self, settings):
            pass
        async def read(self, key):
            return None
        async def submit(self, body):
            return {'state': 'succeeded', 'exitCode': 0, 'files': [], 'warnings': [],
                    'data': {'rowCount': 2, 'columns': [{'name': 'department'}, {'name': 'amount'}],
                             'sampleStartRow': 2, 'sample': [['Admin', '72'], ['Project', '16']],
                             'contentSamples': [], 'sampleTruncated': False}}
        async def best_effort(self, *args):
            pass
    monkeypatch.setattr('app.modules.executions.service.SandboxClient', TableClient)
    result = await inspect_table.coroutine(source=TableSource(input_ref={'attachment_id': item['id']}), runtime=SimpleNamespace(context=context))
    assert json.loads(result)['state'] == 'succeeded'
    return context, item, sent, result


async def test_table_source_requires_actual_model_delivery_and_uses_separate_coverage(setup, monkeypatch):
    context, item, sent, receipt = await inspected_table(setup, monkeypatch)
    async with context.sessions() as db:
        assert (await delivered_citations(db, context, 'before delivery'))[1] == []
    captured = []; transport(monkeypatch, captured)
    await model_for(context)._single(table_messages(receipt))
    async with context.sessions() as db:
        job = await db.get(Job, sent['jobId'])
        assert not job.result.get('documentTextProvided')
        assert next(iter(job.result['documentTableProvided'].values()))['sampleRows'] == [2, 3]
        prose, cards = await delivered_citations(db, context, 'Admin: 72')
        assert prose == 'Admin: 72' and len(cards) == 1
        assert cards[0]['sourceKind'] == 'table' and 'ordinal' not in cards[0]
        assert cards[0]['sampleRows'] == [2, 3] and cards[0]['rowCount'] == 2
    assert (await setup[3]['employee'].get(cards[0]['contentUrl'])).status_code == 200
    assert (await setup[3]['peer'].get(cards[0]['contentUrl'])).status_code == 404
    # When actual document text is also supplied, keep a single source card.
    text = await read_document_result(context, item['id'])
    await model_for(context)._single([ToolMessage(content=text, name='read_document', tool_call_id='text')])
    async with context.sessions() as db:
        assert len((await delivered_citations(db, context, 'same file'))[1]) == 1


@pytest.mark.parametrize('change', ['failed_model', 'failed_tool', 'changed_data', 'user_copy', 'foreign_execution'])
async def test_unprovided_or_forged_table_receipts_never_register_sources(setup, monkeypatch, change):
    context, item, sent, receipt = await inspected_table(setup, monkeypatch)
    parsed = json.loads(receipt)
    if change == 'failed_tool':
        parsed['state'] = 'failed'
    elif change == 'changed_data':
        parsed['data']['rowCount'] = 9999
    elif change == 'foreign_execution':
        settings, sessions, users, clients = setup
        sent = await message(clients['peer'], await conversation(clients['peer']), 'Other user')
        context = await running_context(settings, sessions, users['peer'], sent)
    captured = []; transport(monkeypatch, captured, fail=change == 'failed_model')
    content = json.dumps(parsed)
    messages = [HumanMessage(content=content)] if change == 'user_copy' else table_messages(content)
    if change == 'failed_model':
        from app.integrations.models.transport import ProviderError
        with pytest.raises(ProviderError):
            await model_for(context)._single(messages)
    else:
        await model_for(context)._single(messages)
    async with context.sessions() as db:
        assert not (await db.get(Job, sent['jobId'])).result.get('documentTableProvided')
        assert (await delivered_citations(db, context, 'No source'))[1] == []


@pytest.mark.parametrize('change', ['revision', 'deleted'])
async def test_table_source_does_not_survive_source_revocation(setup, monkeypatch, change):
    context, item, _, receipt = await inspected_table(setup, monkeypatch)
    captured = []; transport(monkeypatch, captured)
    await model_for(context)._single(table_messages(receipt))
    async with context.sessions.begin() as db:
        attachment = await db.get(Attachment, item['id'])
        if change == 'revision':
            attachment.extraction_revision += 1
        else:
            attachment.deleted = True
    async with context.sessions() as db:
        with pytest.raises((InputChanged, HTTPException)):
            await delivered_citations(db, context, 'No stale source')


def transport(monkeypatch, captured, *, fail=False, terminal=False):
    async def chat(settings, config, key, messages, **kwargs):
        from _support.agent.fakes import wire_completion
        from app.integrations.models.transport import ProviderError
        captured.append(deepcopy(messages))
        if fail:
            raise ProviderError('network', 'controlled failure', 503)
        reply = wire_completion('结论来自所提供的材料。') if terminal else {'role': 'assistant', 'content': 'Plain answer without any citation markers.'}
        return {'id': 'fixed-transport', 'model': 'controlled', 'choices': [{'index': 0, 'message': reply, 'finish_reason': 'tool_calls' if terminal else 'stop'}], 'usage': {'prompt_tokens': 20, 'completion_tokens': 5, 'total_tokens': 25}}
    monkeypatch.setattr('app.integrations.models.chat.chat', chat)
    monkeypatch.setattr('app.modules.model_services.bindings.resolve_bound', AsyncMock(return_value=({'streaming': False, 'protocol': 'chat'}, 'owned-test-key')))


async def source(setup):
    settings, sessions, users, clients = setup
    conv = await conversation(clients['employee'])
    item = await upload(clients['employee'], 'source.txt', ('first line\n' + 'x' * 6400).encode())
    sent = await message(clients['employee'], conv, 'Summarize', [item['id']])
    context = await running_context(settings, sessions, users['employee'], sent)
    prepared = await prepare_document(context, item['id'])
    return context, item, prepared, sent


def model_for(context):
    model = BoundedChatModel(model='controlled', api_key='test', base_url='http://127.0.0.1:1', max_retries=0)
    model._run_context = context
    return model


async def test_projection_preserves_user_code_and_source_text_and_rejects_directory_tokens():
    token = 'source:1:0'
    context = SimpleNamespace(document_reads={token: ('source', 1, 0)}, document_versions={'source': 1})
    literal = 'Explain `[[file:source:1:0]]` and [[page:example]].'
    receipt = {'attachment': {'id': 'source'}, 'items': [{'ordinal': 0, 'location': '行 1', 'text': literal, 'citation': '[[file:' + token + ']]'}],
               'positionBasis': '原文位置用 location；ordinal 是游标。引用原样复制 citation，不再加脚注括号。'}
    quoted = '```json\n已提供文档正文：' + json.dumps(receipt, ensure_ascii=False) + '\n```'
    payload = [{'role': 'user', 'content': literal}, {'role': 'user', 'content': [{'type': 'text', 'text': quoted}]},
               {'role': 'tool', 'content': json.dumps({'items': [{'id': 'source', 'citation': '[[file:' + token + ']]'}]})},
               {'role': 'tool', 'content': json.dumps(receipt, ensure_ascii=False)}]
    original = deepcopy(payload)
    projected, supplied = project_document_messages(context, payload)
    assert payload == original and projected[:3] == original[:3]
    actual = json.loads(projected[-1]['content'])
    assert actual['items'][0]['text'] == literal and actual['items'][0]['location'] == '行 1'
    assert 'citation' not in actual['items'][0] and '原样复制' not in actual['positionBasis']
    assert supplied == context.document_reads
    assert project_document_messages(context, payload[:3])[1] == {}
    unknown = [{'role': 'user', 'content': [{'type': 'text', 'text': 'NORIA_DOCUMENT_PAGES:["example"]'}]}]
    assert project_page_markers(unknown, {}) == unknown


async def test_document_projection_compacts_only_registered_tool_receipts_without_losing_evidence():
    context = SimpleNamespace(document_reads={}, document_versions={'source': 1})
    receipt = {'attachment': {'id': 'source', 'name': 'notes.doc',
                             'readText': {'tool': 'read_document', 'attachment_id': 'source', 'start': 0},
                             'readPages': {'tool': 'read_document', 'view': 'pages', 'pages': [1]},
                             'extraction': {'revision': 1, 'parserVersion': 'internal', 'schema': 1,
                                            'originalFormat': 'doc', 'convertedFormat': 'docx',
                                            'conversionFidelityVerified': False, 'sourceComplete': False,
                                            'nextExtractCursor': 40, 'warnings': ['图片部分没读到']}},
               'items': [], 'sourceComplete': False, 'nextExtractCursor': 40, 'nextCursor': 40,
               'searchScope': {'fromOrdinal': 0, 'toOrdinal': 40, 'stopReason': 'batch_limit'},
               'scopeWarning': '原文件仍有未提取范围。',
               'readScope': {'returnedChunks': 0, 'extractedChunks': 40, 'allExtractedTextReturned': False,
                             'returnedChunksThisTask': 3, 'unreturnedExtractedChunksThisTask': 37,
                             'providedChunksBeforeThisCall': 2, 'textBasis': 'converted_text',
                             'pageImagesIncluded': False, 'limitations': ['转换不证明原件完整。']}}
    serialized = json.dumps(receipt, ensure_ascii=False)
    payload = [{'role': 'user', 'content': serialized},
               {'role': 'user', 'content': [{'type': 'text', 'text': '\n已提供文档正文：' + serialized}]},
               {'role': 'tool', 'content': serialized, 'name': 'unrelated_tool'},
               {'role': 'assistant', 'tool_calls': [{'id': 'search', 'function': {'name': 'find_documents'}}]},
               {'role': 'tool', 'content': serialized, 'tool_call_id': 'search'},
               {'role': 'tool', 'content': serialized, 'name': 'read_document'}]
    original = deepcopy(payload)
    projected, supplied = project_document_messages(context, payload)
    assert payload == original and projected[:4] == original[:4] and supplied == {}
    expected = deepcopy(receipt)
    expected['attachment'].pop('readText')
    for key in ('parserVersion', 'schema', 'sourceComplete', 'nextExtractCursor'):
        expected['attachment']['extraction'].pop(key)
    for key in ('providedChunksBeforeThisCall', 'unreturnedExtractedChunksThisTask'):
        expected['readScope'].pop(key)
    assert json.loads(projected[-2]['content']) == expected
    assert json.loads(projected[-1]['content']) == expected
    context.document_versions = {}
    assert project_document_messages(context, payload)[0] == original


async def test_registered_spreadsheet_projection_preserves_exact_cells_without_inventing_schema():
    context = SimpleNamespace(document_reads={}, document_versions={'source': 2})
    rows = []
    for ordinal, (cell, value) in enumerate([('A1', '数量'), ('H1', '状态'), ('A3', '0012'), ('H3', '待发货')]):
        token = f'source:2:{ordinal}'
        context.document_reads[token] = ('source', 2, ordinal)
        rows.append({'ordinal': ordinal, 'location': f'工作表「台账」!{cell}', 'text': f'{cell}：{value}', 'citation': f'[[file:{token}]]'})
    receipt = {'attachment': {'id': 'source'}, 'items': rows, 'readScope': {'pageImagesIncluded': False}}
    payload = [{'role': 'tool', 'name': 'read_document', 'content': json.dumps(receipt, ensure_ascii=False)}]
    projected, supplied = project_document_messages(context, payload)
    value = json.loads(projected[0]['content'])
    assert value['tableRows'] == {'cellFields': ['cell', 'ordinal', 'text'], 'rows': [
        {'sheet': '台账', 'row': 1, 'cells': [['A1', 0, '数量'], ['H1', 1, '状态']]},
        {'sheet': '台账', 'row': 3, 'cells': [['A3', 2, '0012'], ['H3', 3, '待发货']]}]}
    assert supplied == context.document_reads and value['readScope'] == receipt['readScope']
    assert 'items' not in value
    # Incomplete/split cells keep the original representation and positions.
    receipt['items'][0]['location'] += ' · 字符 1–3000'
    payload[0]['content'] = json.dumps(receipt, ensure_ascii=False)
    assert 'tableRows' not in json.loads(project_document_messages(context, payload)[0][0]['content'])


@pytest.mark.parametrize('preload', [False, True])
async def test_actual_successful_request_supplies_sources_without_prose_markers(setup, monkeypatch, preload):
    context, item, prepared, sent = await source(setup)
    if preload:
        blocks = [{'type': 'text', 'text': 'Summarize'}]
        await preload_documents(context, [prepared], blocks)
        messages = [HumanMessage(content=blocks)]
    else:
        receipt = await read_document_result(context, item['id'])
        messages = [HumanMessage(content='Summarize'), ToolMessage(content=receipt, tool_call_id='read', name='read_document')]
    captured = []; transport(monkeypatch, captured)
    await model_for(context)._single(messages)
    assert len(captured) == 1 and '[[file:' not in json.dumps(captured[0])
    if preload:
        repeated = [{'type': 'text', 'text': 'Summarize'}]
        await preload_documents(context, [prepared], repeated)
        assert repeated == blocks  # Successful delivery cannot create a new checkpoint identity.
    async with context.sessions() as db:
        job = await db.get(Job, sent['jobId'])
        assert len(job.result['documentTextProvided']) > 1
        prose = 'Plain answer without any citation markers.'
        answer, cards = await delivered_citations(db, context, prose)
        assert answer == prose and len(cards) == 1 and cards[0]['attachmentId'] == item['id']
        tokens = list(job.result['documentTextProvided'])
        answer, repeated = await delivered_citations(db, context, ''.join('[[file:' + token + ']]' for token in tokens))
        assert answer == '〔1〕' * len(tokens) and repeated == cards
    response = await setup[3]['employee'].get(f'/api/v1/uploads/{item["id"]}/extraction')
    assert response.status_code == 200 and response.json()['items']
    assert (await setup[3]['peer'].get(f'/api/v1/uploads/{item["id"]}/extraction')).status_code == 404


async def test_unreceived_failed_and_forged_sources_never_become_cards(setup, monkeypatch):
    context, item, _, sent = await source(setup)
    receipt = await read_document_result(context, item['id'])
    token = json.loads(receipt)['items'][0]['citation']
    async with context.sessions() as db:
        prose, cards = await delivered_citations(db, context, 'Not sent yet. ' + token)
        assert cards == [] and '来源未核实' in prose
    # A copied token in user prose is not a delivered document receipt.
    captured = []; transport(monkeypatch, captured)
    await model_for(context)._single([HumanMessage(content='Discuss this syntax: ' + token)])
    async with context.sessions() as db:
        assert not (await db.get(Job, sent['jobId'])).result.get('documentTextProvided')
    transport(monkeypatch, captured, fail=True)
    from app.integrations.models.transport import ProviderError
    with pytest.raises(ProviderError):
        await model_for(context)._single([ToolMessage(content=receipt, name='read_document', tool_call_id='read')])
    async with context.sessions() as db:
        assert not (await db.get(Job, sent['jobId'])).result.get('documentTextProvided')
        assert (await delivered_citations(db, context, 'Failure.'))[1] == []


@pytest.mark.parametrize('change', ['revision', 'deleted', 'foreign'])
async def test_delivered_sources_keep_current_revision_and_access_checks(setup, monkeypatch, change):
    context, item, _, sent = await source(setup)
    receipt = await read_document_result(context, item['id'])
    captured = []; transport(monkeypatch, captured)
    await model_for(context)._single([ToolMessage(content=receipt, name='read_document', tool_call_id='read')])
    async with context.sessions.begin() as db:
        attachment = await db.get(Attachment, item['id'])
        if change == 'revision':
            attachment.extraction_revision += 1
        elif change == 'deleted':
            attachment.deleted = True
        else:
            foreign = await db.get(Job, sent['jobId'])
            evidence = dict(foreign.result['documentTextProvided'])
    if change == 'foreign':
        settings, sessions, users, clients = setup
        sent = await message(clients['peer'], await conversation(clients['peer']), 'Other task')
        context = await running_context(settings, sessions, users['peer'], sent)
        async with sessions.begin() as db:
            job = await db.get(Job, sent['jobId'])
            job.result = {**job.result, 'documentTextProvided': evidence}
    async with context.sessions() as db:
        with pytest.raises((InputChanged, HTTPException)):
            await delivered_citations(db, context, 'No tokens.')


async def test_api_worker_persists_file_cards_and_keeps_coverage_out_of_prose(setup, monkeypatch):
    settings, sessions, users, clients = setup
    from _support.http.model_services import create, route
    service = await create(clients['admin'])
    assert (await clients['admin'].put('/api/v1/settings/model-routing', json=route(service))).status_code == 200
    item = await upload(clients['employee'], 'brief.txt', b'actual document text')
    sent = await message(clients['employee'], await conversation(clients['employee']), 'Summarize this document', [item['id']])
    captured = []; transport(monkeypatch, captured, terminal=True)
    await run(settings, sessions, users, sent)
    response = await clients['employee'].get('/api/v1/messages/' + sent['messageId'])
    actual = response.json()
    assert actual['reply'] == '结论来自所提供的材料。', actual['job']
    assert len(captured) == 1 and len(actual['citations']) == 1
    assert actual['citations'][0]['attachmentId'] == item['id']
    assert '[[file:' not in json.dumps(captured[0])
    async with sessions() as db:
        job = await db.get(Job, sent['jobId'])
        assert job.result['documentTextProvided'] and job.result['materialCoverage']
