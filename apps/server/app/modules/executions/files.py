"""Authorized source copies and immutable private generated files."""
import base64
import hashlib
import re
from pathlib import Path
from app.core.errors import problem
from app.modules.attachments.models import Attachment
from app.modules.messages.service import active_message
from app.modules.deliverables.queries import get_deliverable, remember_source
from app.security.access import require
from app.modules.executions.sources import check_sources

MAX_INPUT = 40 * 1024 * 1024
MIMES = {'.txt': 'text/plain', '.md': 'text/markdown', '.json': 'application/json', '.csv': 'text/csv', '.png': 'image/png', '.pdf': 'application/pdf',
         '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
         '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
         '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'}


def file_path(settings, key):
    if not re.fullmatch(r'[a-f0-9]{64}', key):
        problem(404, '文件不可用')
    return settings.media_dir / 'generated' / key


async def resolve_input(db, actor, job, message, ref):
    """Authorize reference metadata without copying or parsing file bytes."""
    from app.modules.attachments.documents import agent_attachment
    from app.security.access import inherit
    if not isinstance(ref, dict) or set(ref) - {'attachment_id', 'deliverable_id', 'revision', 'file_id'}:
        problem(422, '文件引用参数无效')
    if any(not isinstance(ref[key], str) or len(ref[key]) > 80 for key in ('attachment_id', 'deliverable_id', 'file_id') if key in ref):
        problem(422, '文件引用参数无效')
    if ref.get('attachment_id') and not ref.get('deliverable_id'):
        item = await db.get(Attachment, ref['attachment_id'])
        if not item or item.deleted:
            problem(404, '文件不存在')
        from app.modules.work.materials.queries import work_for_material
        work = await work_for_material(db, actor, item.id)
        if work:
            from app.modules.work.materials.queries import require_agent_work
            await require_agent_work(db, actor, job, work)
        elif item.owner_id == actor.id and item.company_id == actor.company_id:
            parent = await active_message(db, item.message_id, actor)
            if parent.conversation_id != message.conversation_id:
                problem(403, '只能处理当前会话的附件')
            await require(db, actor, parent.access)
            inherit(actor, job, parent)
        else:
            item = await agent_attachment(db, item.id, actor, job)
        if 'revision' in ref and (type(ref['revision']) is not int or ref['revision'] != item.extraction_revision):
            problem(409, '源文件版本已变化，请重新读取文件引用')
        source = {'kind': 'attachment', 'id': item.id, 'sha256': item.sha256, 'revision': item.extraction_revision, 'access': job.access}
        return {'reference': {'attachment_id': item.id, 'revision': item.extraction_revision},
                'name': item.name, 'sha256': item.sha256, 'sources': [source]}
    if ref.get('deliverable_id') and not ref.get('attachment_id'):
        if type(ref.get('revision')) is not int or ref['revision'] < 1:
            problem(422, '请指定已读取的成果版本')
        owner, record = await get_deliverable(db, actor, ref['deliverable_id'], ref['revision'], conversation_id=message.conversation_id)
        item = next((entry for entry in record.files if entry['id'] == ref.get('file_id')), None)
        if not item:
            problem(404, '成果文件不存在')
        await check_sources(db, actor, item.get('sources', []))
        remember_source(job, actor, owner, record)
        return {'reference': {'deliverable_id': owner.id, 'revision': record.revision, 'file_id': item['id']},
                'name': item['name'], 'sha256': item['sha256'], 'storageKey': item['storageKey'], 'sources': item.get('sources', [])}
    problem(422, '请选择附件或成果文件')


def input_path(settings, resolved):
    return (file_path(settings, resolved['storageKey']) if 'storageKey' in resolved
            else settings.media_dir / resolved['reference']['attachment_id'])


async def prepare_inputs(db, actor, job, message, settings, references):
    files, sources, total = [], [], 0
    for ref in references:
        resolved = await resolve_input(db, actor, job, message, ref)
        path, name = input_path(settings, resolved), resolved['name']
        sources.extend(resolved['sources'])
        if not path.is_file() or path.is_symlink():
            problem(404, '源文件已不可用')
        total += path.stat().st_size
        if total > MAX_INPUT:
            problem(422, '本次执行输入超过 40 MB，请减少文件')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != resolved['sha256']:
            problem(409, '源文件校验失败，请重新上传或生成')
        used_names = {entry['name'] for entry in files}
        if name in used_names:
            suffix = Path(name).suffix
            stem = name[:-len(suffix)] if suffix else name
            number = len(files) + 1
            while name in used_names:
                prefix = f'{number}-'
                name = prefix + stem[:180 - len(prefix) - len(suffix)] + suffix
                number += 1
        files.append({'name': name, 'data': base64.b64encode(data).decode()})
    return files, list({item['id']: item for item in sources}.values())


def validate_metadata(value):
    name = value.get('name', '')
    suffix = Path(name).suffix.lower()
    if not name or len(name) > 180 or any(c in name for c in '/\\\x00') or any(ord(c) < 32 for c in name) or suffix not in MIMES:
        raise ValueError('生成文件名或格式无效')
    if value.get('mimeType') != MIMES[suffix] or not isinstance(value.get('size'), int) or not 0 < value['size'] <= 32 * 1024 * 1024:
        raise ValueError('生成文件类型或大小无效')
    if not re.fullmatch(r'[a-f0-9]{64}', value.get('id', '')) or value['id'] != value.get('sha256'):
        raise ValueError('生成文件摘要无效')
    return value


def persist_file(settings, execution_key, metadata, data, sources):
    validate_metadata(metadata)
    if hashlib.sha256(data).hexdigest() != metadata['sha256']:
        raise ValueError('生成文件摘要不匹配')
    key = hashlib.sha256((execution_key + ':' + metadata['name'] + ':' + metadata['sha256']).encode()).hexdigest()
    path = file_path(settings, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_bytes(data)
    temp.replace(path)
    return {**metadata, 'id': key, 'storageKey': key, 'sources': sources}
