"""Authorized source copies and immutable private generated files."""
import base64
import hashlib
import re
from pathlib import Path
from app.core.errors import problem
from app.modules.attachments.models import Attachment
from app.modules.messages.models import Message
from app.modules.messages.service import active_message
from app.modules.deliverables.queries import get_deliverable
from app.security.ownership import owned
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


async def prepare_inputs(db, actor, job, message, settings, references):
    from app.modules.attachments.documents import agent_attachment
    from app.security.access import inherit
    files, sources, total = [], [], 0
    for ref in references:
        if not isinstance(ref, dict) or set(ref) - {'attachment_id', 'deliverable_id', 'revision', 'file_id'}:
            problem(422, '文件引用参数无效')
        if ref.get('attachment_id') and not ref.get('deliverable_id'):
            item = await db.get(Attachment, ref['attachment_id'])
            if not item or item.deleted:
                problem(404, '文件不存在')
            if item.owner_id == actor.id and item.company_id == actor.company_id:
                parent = await active_message(db, item.message_id, actor)
                if parent.conversation_id != message.conversation_id:
                    problem(403, '只能处理当前会话的附件')
                await require(db, actor, parent.access)
                inherit(actor, job, parent)
            else:
                item = await agent_attachment(db, item.id, actor, job)
            path, name = settings.media_dir / item.id, item.name
            source = {'kind': 'attachment', 'id': item.id, 'sha256': item.sha256, 'revision': item.extraction_revision, 'access': job.access}
            sources.append(source)
        elif ref.get('deliverable_id') and not ref.get('attachment_id'):
            if not isinstance(ref.get('revision'), int) or ref['revision'] < 1:
                problem(422, '请指定已读取的成果版本')
            owner, record = await get_deliverable(db, actor, ref['deliverable_id'], ref['revision'], conversation_id=message.conversation_id)
            item = next((entry for entry in record.files if entry['id'] == ref.get('file_id')), None)
            if not item:
                problem(404, '成果文件不存在')
            await check_sources(db, actor, item.get('sources', []))
            inherit(actor, job, owner)
            sources.extend(item.get('sources', []))
            path, name = file_path(settings, item['storageKey']), item['name']
        else:
            problem(422, '请选择附件或成果文件')
        if not path.is_file() or path.is_symlink():
            problem(404, '源文件已不可用')
        total += path.stat().st_size
        if total > MAX_INPUT:
            problem(422, '本次执行输入超过 40 MiB，请减少文件')
        data = path.read_bytes()
        expected = source['sha256'] if ref.get('attachment_id') else item['sha256']
        if hashlib.sha256(data).hexdigest() != expected:
            problem(409, '源文件校验失败，请重新上传或生成')
        if any(entry['name'] == name for entry in files):
            name = f'{len(files) + 1}-{name}'
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
