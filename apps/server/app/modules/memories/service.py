"""Current-account memory transactions, shared by HTTP and agent adapters."""
from dataclasses import asdict
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.core.digests import digest
from app.core.errors import problem
from app.db.base import now
from app.modules.members.models import Member
from app.modules.messages.models import Message
from app.modules.messages.input_text import request_text
from app.tasks.context import MemorySnapshot
from .models import AssistantMemory
from .document import annotations_after, patch, validate
from .limits import MAX_CHARACTERS


async def read(db, actor):
    return await db.scalar(select(AssistantMemory).where(AssistantMemory.company_id == actor.company_id,
        AssistantMemory.owner_id == actor.id).execution_options(populate_existing=True))


async def locked(db, actor):
    member = await db.scalar(select(Member).where(Member.id == actor.id, Member.company_id == actor.company_id).with_for_update().execution_options(populate_existing=True))
    if not member or not member.active or member.deleted:
        problem(403, '账号已不可用')
    await db.execute(insert(AssistantMemory).values(company_id=actor.company_id, owner_id=actor.id,
        enabled=True, revision=0, generation=0, document={'schemaVersion': 1, 'markdown': '', 'annotations': []})
        .on_conflict_do_nothing(index_elements=['company_id', 'owner_id']))
    return await db.scalar(select(AssistantMemory).where(AssistantMemory.company_id == actor.company_id,
        AssistantMemory.owner_id == actor.id).with_for_update().execution_options(populate_existing=True))


def dto(row):
    return {'enabled': row.enabled if row else True, 'revision': row.revision if row else 0,
            'markdown': row.document['markdown'] if row else '',
            'updatedAt': row.updated_at.isoformat() if row and row.revision else None,
            'maxCharacters': MAX_CHARACTERS}


def expected(row, revision):
    if row.revision != revision:
        problem(409, '记忆已被更新，请查看最新内容并合并；你的草稿仍保留', 'memory_conflict')


def advance(row, *, barrier=False):
    row.revision += 1
    row.updated_at = now()
    if barrier:
        row.generation += 1
        row.document = {**row.document, 'barrierAt': row.updated_at.isoformat()}


async def settings(db, actor, revision, enabled):
    row = await locked(db, actor)
    expected(row, revision)
    if row.enabled != enabled:
        row.enabled = enabled
        advance(row, barrier=True)
    return dto(row)


async def save_document(db, actor, revision, markdown):
    validate(markdown)
    row = await locked(db, actor)
    expected(row, revision)
    row.document = annotations_after(row.document, markdown, 'manual')
    # Even saving/clearing an empty document revokes already running jobs.
    advance(row, barrier=True)
    return dto(row)


async def bind(db, actor, job, source_revision):
    """Freeze once per task/input; retries never obtain fresh writing authority."""
    if job.kind != 'message':
        return None
    prior = job.result.get('memorySnapshot')
    if prior is not None:
        return MemorySnapshot(**prior) if prior else None
    message = await db.get(Message, job.target_id)
    if not message or message.owner_id != actor.id or message.company_id != actor.company_id or message.deleted:
        return None
    row = await read(db, actor)
    barrier = row.document.get('barrierAt') if row else None
    allowed = not barrier or message.created_at > datetime.fromisoformat(barrier)
    snapshot = MemorySnapshot(revision=row.revision if row else 0, generation=row.generation if row else 0,
        source_revision=source_revision, message_id=message.id, input_hash=digest(request_text(message, job)), writable=allowed)
    job.result = {**job.result, 'memorySnapshot': asdict(snapshot)}
    return snapshot


def stale_result():
    return {'state': 'conflict', 'message': '记忆已变化，旧操作结果不再代表当前状态；本次未重新写入'}


async def restore(db, actor, receipt, *, job=None):
    row = await read(db, actor)
    if receipt.get('state') == 'succeeded' and (not row or row.revision != receipt.get('revision') or row.generation != receipt.get('generation')):
        snapshot = (job.result.get('memorySnapshot') or {}) if job else {}
        if (row and snapshot.get('revision') == row.revision
                and snapshot.get('generation') == row.generation == receipt.get('generation')
                and receipt in job.result.get('memoryOperations', {}).values()):
            return {**receipt, 'superseded': True,
                    'message': '此操作已成功，随后本轮又更新了记忆；以最新文档为准，不要重复保存旧内容。'}
        return stale_result()
    return receipt


async def change(db, actor, job, snapshot, *, call_id, evidence, old='', new='', explicit=False, forget=False, all_memories=False, expires=None):
    row = await locked(db, actor)
    message = await db.get(Message, job.target_id) if job.kind == 'message' else None
    if not snapshot or not message or message.id != snapshot.message_id or message.owner_id != actor.id or message.company_id != actor.company_id or message.deleted or message.transcript_revision != snapshot.source_revision:
        problem(409, '记忆来源已变化，本次未保存', 'memory_source_changed')
    text = request_text(message, job)
    if digest(text) != snapshot.input_hash or not evidence.strip() or evidence not in text:
        problem(422, '记忆依据必须逐字来自本轮用户文字或直接录音指令', 'memory_source_invalid')
    key = digest({'job': job.id, 'input': snapshot.input_hash, 'revision': snapshot.source_revision, 'call': call_id})
    operations = job.result.get('memoryOperations', {})
    if key in operations:
        return await restore(db, actor, operations[key], job=job)
    if not snapshot.writable or row.generation != snapshot.generation:
        problem(409, '记忆设置或文档已变化，旧输入不能重新写入，请重新说明要求', 'memory_stale_input')
    expected(row, snapshot.revision)
    if not row.enabled and not forget:
        return {'state': 'unavailable', 'message': '跨会话记忆已关闭，本次没有保存；可在设置中开启'}
    if expires:
        try:
            expiry = datetime.fromisoformat(expires.replace('Z', '+00:00'))
            if expiry.tzinfo is None or expiry <= now():
                raise ValueError()
            expires = expiry.astimezone(timezone.utc).isoformat()
        except (ValueError, TypeError):
            problem(422, '记忆有效期必须是未来带时区的时间')
    if forget:
        if not explicit:
            problem(422, '忘记操作必须依据本轮明确删除要求')
        if all_memories:
            document = {**row.document, 'markdown': '', 'annotations': []}
        else:
            if not old.strip():
                problem(422, '请明确要忘记的内容，未清空其它记忆')
            from .document import forget_fragment
            old = forget_fragment(row.document['markdown'], old)
            document = patch(row.document, old, '', explicit=True, source=message.id)
    else:
        if not new.strip():
            problem(422, '删除记忆请使用明确的忘记操作，本次未修改')
        document = patch(row.document, old, new, explicit=explicit, source=message.id, expires=expires)
    changed = document != row.document
    if changed or forget:
        row.document = document
        advance(row, barrier=forget)
    result = {'state': 'succeeded', 'operation': 'forgotten' if forget else 'saved',
              'changed': changed,
              'message': ('记忆已更新。' if changed else '记忆已是目标内容，本次无需修改。') + '本项已完成，不要重复调用；继续回答用户或处理其它独立事项。',
              'revision': row.revision, 'generation': row.generation, 'characters': len(row.document['markdown'])}
    snapshot.revision, snapshot.generation = row.revision, row.generation
    job.result = {**job.result, 'memorySnapshot': asdict(snapshot), 'memoryOperations': {**operations, key: result}}
    return result


async def validate_job(db, actor, job):
    operations = job.result.get('memoryOperations', {})
    if operations:
        latest = max(operations.values(), key=lambda value: value['revision'])
        if (await restore(db, actor, latest, job=job)).get('state') != 'succeeded':
            raise ValueError('记忆已被修改或删除，旧任务结果已失效；请重新说明要求')


async def conflict_context(db, actor, snapshot, fragment):
    """Only expose exact matching lines already visible in this task's memory."""
    row = await read(db, actor)
    if (not row or not row.enabled or not snapshot or not snapshot.writable
            or row.generation != snapshot.generation or row.revision != snapshot.revision or not fragment.strip()):
        return {}
    lines = [line for line in row.document['markdown'].splitlines() if fragment.strip() in line]
    return {'matchingFragments': lines[:3], 'nextStep': '使用匹配行中的完整事实精确定位，保留其他内容；不能扩大删除范围。'} if lines and sum(map(len, lines[:3])) <= 1200 else {}
