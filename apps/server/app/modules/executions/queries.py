"""Read persisted observations without replaying code or crossing conversations."""
import json
from fastapi import HTTPException
from sqlalchemy import select
from app.core.errors import problem
from app.modules.conversations.models import Conversation
from app.modules.deliverables.queries import get_deliverable, remember_source
from app.modules.deliverables.serializers import summary as delivery_summary
from app.modules.executions.models import SandboxExecution
from app.modules.executions.files import resolve_input, input_path
from app.modules.executions.sources import check_sources, remember_sources
from app.modules.messages.models import Message
from app.security.access import merge_access, require, scope
from app.security.ownership import owned
from app.tasks.models import Job

PAGE_SIZE = 10
TEXT_WIDTH = 3000


def execution_query(actor, current):
    return select(SandboxExecution, Message, Job).join(Message, Message.id == SandboxExecution.message_id).join(
        Job, Job.id == SandboxExecution.job_id).where(
        SandboxExecution.company_id == actor.company_id, SandboxExecution.owner_id == actor.id,
        SandboxExecution.conversation_id == current.conversation_id,
        Message.company_id == actor.company_id, Message.owner_id == actor.id,
        Message.conversation_id == current.conversation_id, Message.deleted.is_(False),
        Message.created_at <= current.created_at,
        Job.company_id == actor.company_id, Job.owner_id == actor.id)


async def authorize(db, actor, job, row, message, origin):
    await require(db, actor, message.access)
    await require(db, actor, origin.access)
    await check_sources(db, actor, row.sources)
    job.access = merge_access(merge_access(job.access or scope(actor), message.access), origin.access)


def summary(row):
    return {'executionId': row.id, 'messageId': row.message_id, 'createdAt': row.created_at.isoformat(),
            'title': row.result.get('title', '内置工具执行' if row.request else 'Python 执行'), 'state': row.state,
            'kind': 'builtin' if row.request else 'python', 'tool': row.request['name'] if row.request else 'run_python',
            'exitCode': row.result.get('exitCode'),
            'inputCount': len(row.result['inputRefs']) if isinstance(row.result.get('inputRefs'), list) and len(row.result['inputRefs']) <= 12 else None}


async def delivery_reference(db, actor, job, row):
    snapshot = row.result.get('delivery')
    if not snapshot:
        return 'none', ''
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('id'), str) or type(snapshot.get('revision')) is not int or snapshot['revision'] < 1:
        return 'unavailable', ''
    try:
        item, record = await get_deliverable(db, actor, snapshot['id'], snapshot['revision'], conversation_id=row.conversation_id)
    except HTTPException as error:
        if error.status_code not in (403, 404):
            raise
        return 'unavailable', ''
    remember_source(job, actor, item, record)
    # Rebuild references from the authorized immutable revision, never replay saved URLs/body.
    return 'available', json.dumps(delivery_summary(item, record), ensure_ascii=False)


async def input_references(db, actor, job, current, row, context):
    """Expose only explicit, still-authorized inputs; sources also include indirect reads."""
    references = row.result.get('inputRefs')
    files = row.result.get('inputFiles')
    empty = {'inputRefs': [], 'inputFiles': []}
    if references is None:
        return {**empty, 'inputState': 'unrecorded'}
    if not isinstance(references, list) or len(references) > 12 or not isinstance(files, list) or len(files) != len(references):
        return {**empty, 'inputState': 'unavailable'}
    resolved_refs, names = [], []
    for ref, name in zip(references, files, strict=True):
        if (not isinstance(name, str) or not name or len(name) > 180
                or any(char in name for char in '/\\\x00') or any(ord(char) < 32 for char in name)):
            continue
        try:
            resolved = await resolve_input(db, actor, job, current, ref)
            if context is not None:
                path = input_path(context.settings, resolved)
                if not path.is_file() or path.is_symlink():
                    continue
        except HTTPException as error:
            if error.status_code in (403, 404, 409):
                # The receipt's code/stdout/request may embed this input's content.
                # A revoked input must hide those fields, not just its reusable ID.
                problem(404, '执行记录的输入来源已不可用')
            if error.status_code != 422:
                raise
            continue
        resolved_refs.append(resolved['reference'])
        names.append(name)
    state = 'none' if not references else 'available' if len(resolved_refs) == len(references) else 'partial' if resolved_refs else 'unavailable'
    return {'inputRefs': resolved_refs, 'inputFiles': names, 'inputState': state}


async def read_executions(db, actor, job, current, *, identifier='', offset=0, context=None):
    if not isinstance(offset, int) or offset < 0:
        problem(422, '执行记录阅读位置无效')
    if not current.conversation_id:
        if identifier:
            problem(404, '执行记录不存在或无权查看')
        return {'items': [], 'nextOffset': None}
    await owned(db, Conversation, current.conversation_id, actor)
    if current.deleted:
        problem(404, '消息不存在或无权查看')
    query = execution_query(actor, current)
    if not identifier:
        rows = (await db.execute(query.order_by(SandboxExecution.created_at.desc(), SandboxExecution.id.desc())
                                 .offset(offset).limit(PAGE_SIZE + 1))).all()
        items = []
        for row, message, origin in rows[:PAGE_SIZE]:
            try:
                await authorize(db, actor, job, row, message, origin)
            except HTTPException:
                continue
            items.append(summary(row))
        return {'items': items, 'nextOffset': offset + PAGE_SIZE if len(rows) > PAGE_SIZE else None}
    record = (await db.execute(query.where(SandboxExecution.id == identifier))).first()
    if record is None:
        problem(404, '执行记录不存在或无权查看')
    row, message, origin = record
    await authorize(db, actor, job, row, message, origin)
    if context is not None:
        await remember_sources(db, job, context, row.sources)
    delivery_state, delivery = await delivery_reference(db, actor, job, row)
    fields = {'code': row.code, 'stdout': str(row.result.get('stdout', '')),
              'stderr': str(row.result.get('stderr', '')), 'message': str(row.result.get('message', '')),
              'delivery': delivery}
    if delivery_state == 'available' and row.result.get('fileResults'):
        fields['fileResults'] = json.dumps(row.result['fileResults'], ensure_ascii=False)
    if row.request is not None:
        fields.update(request=json.dumps(row.request, ensure_ascii=False), resultData=json.dumps(row.result.get('data', {}), ensure_ascii=False),
                      warnings=json.dumps(row.result.get('warnings', []), ensure_ascii=False))
    length = max(map(len, fields.values()))
    if offset and offset >= length:
        problem(422, '执行记录阅读位置已超出范围')
    return {**summary(row), **await input_references(db, actor, job, current, row, context),
            **{name: value[offset:offset + TEXT_WIDTH] for name, value in fields.items()},
            'deliveryState': delivery_state,
            'contentOffset': offset, 'nextOffset': offset + TEXT_WIDTH if offset + TEXT_WIDTH < length else None,
            'contentTruncated': offset > 0 or length > TEXT_WIDTH,
            'evidenceType': 'execution_receipt', 'historical': row.job_id != job.id,
            'coverage': '已保存的实际执行记录；只支持当时输入及输出中明确记录的环境，不代表重新执行或其它版本。'}
