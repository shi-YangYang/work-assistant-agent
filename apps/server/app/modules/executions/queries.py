"""Read persisted observations without replaying code or crossing conversations."""
import json
from fastapi import HTTPException
from sqlalchemy import select
from app.core.errors import problem
from app.modules.conversations.models import Conversation
from app.modules.deliverables.queries import get_deliverable
from app.modules.deliverables.serializers import summary as delivery_summary
from app.modules.executions.models import SandboxExecution
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
            'exitCode': row.result.get('exitCode')}


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
    job.access = merge_access(job.access or scope(actor), item.access)
    # Rebuild references from the authorized immutable revision, never replay saved URLs/body.
    return 'available', json.dumps(delivery_summary(item, record), ensure_ascii=False)


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
        remember_sources(job, context, row.sources)
    delivery_state, delivery = await delivery_reference(db, actor, job, row)
    fields = {'code': row.code, 'stdout': str(row.result.get('stdout', '')),
              'stderr': str(row.result.get('stderr', '')), 'message': str(row.result.get('message', '')),
              'delivery': delivery}
    if row.request is not None:
        fields.update(request=json.dumps(row.request, ensure_ascii=False), resultData=json.dumps(row.result.get('data', {}), ensure_ascii=False),
                      warnings=json.dumps(row.result.get('warnings', []), ensure_ascii=False))
    length = max(map(len, fields.values()))
    if offset and offset >= length:
        problem(422, '执行记录阅读位置已超出范围')
    return {**summary(row), **{name: value[offset:offset + TEXT_WIDTH] for name, value in fields.items()},
            'deliveryState': delivery_state,
            'contentOffset': offset, 'nextOffset': offset + TEXT_WIDTH if offset + TEXT_WIDTH < length else None,
            'contentTruncated': offset > 0 or length > TEXT_WIDTH,
            'evidenceType': 'execution_receipt', 'historical': row.job_id != job.id,
            'coverage': '已保存的实际执行记录；只支持当时输入及输出中明确记录的环境，不代表重新执行或其它版本。'}
