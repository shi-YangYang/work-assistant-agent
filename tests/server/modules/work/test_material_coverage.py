"""Read media retain authorization without misleading document coverage notes."""
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.db.base import uid
from app.agent.tools.business.work_records import read_work_material
from app.modules.attachments.documents import material_coverage, append_material_coverage
from app.modules.attachments.models import Attachment
from app.tasks.lease import lease
from app.tasks.models import Job
from _support.agent.business_actions import runtime
from _support.work.work_records import create

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('kind', ['audio', 'image'])
async def test_successful_media_read_keeps_source_checks_and_only_documents_have_chunk_counts(setup, monkeypatch, kind):
    settings, sessions, users, clients = setup
    identifier = uid()
    data = b'controlled material source'
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    (settings.media_dir / identifier).write_bytes(data)
    async with sessions.begin() as db:
        db.add(Attachment(id=identifier, company_id=users['employee'].company_id, owner_id=users['employee'].id,
                          kind=kind, name='材料.' + ('wav' if kind == 'audio' else 'png'), mime='audio/wav' if kind == 'audio' else 'image/png',
                          size=len(data), sha256=hashlib.sha256(data).hexdigest(), extraction_status='ready',
                          extraction_info={'transcript': '录音里的验收要求'} if kind == 'audio' else {}))
    work = await create(clients['employee'], materials=[{'attachmentId': identifier}])
    material = (await clients['employee'].get('/api/v1/work-items/' + work['id'] + '/materials')).json()['items'][0]
    context, _ = await runtime(setup, '读取工作中的材料')
    if kind == 'image':
        monkeypatch.setattr('app.integrations.media.image_process', AsyncMock(return_value={'tiles': [], 'complete': True}))
        monkeypatch.setattr('app.agent.runtime.model.BoundedChatModel.ainvoke', AsyncMock(return_value=AIMessage(content='受控图片读取结果')))
    result = json.loads(await read_work_material.coroutine(work['id'], material['id'], SimpleNamespace(context=context)))
    assert result['status'] == 'ready' and result['text']
    async with sessions() as db:
        job = await db.get(Job, context.job_id)
        sources = (await db.scalars(select(Attachment).where(Attachment.id.in_(context.document_versions)))).all()
        assert len(sources) == 1
        coverage, legacy = await material_coverage(db, users['employee'], job, sources, context.document_reads)
        assert append_material_coverage('已经读取材料。', coverage, legacy) == '已经读取材料。'
        document = Attachment(id=uid(), kind='document', name='需求.txt', extraction_status='ready',
                              extraction_revision=1, extraction_info={'chunks': 1}, sha256='a' * 64)
        coverage, legacy = await material_coverage(db, users['employee'], job, [*sources, document], {'read': [document.id, 1, 0]})
        assert coverage == ['需求.txt：文字工具读取 1/1 个分段']
        assert append_material_coverage('已经读取材料。', coverage, legacy).endswith('\n\n材料范围：\n需求.txt：文字工具读取 1/1 个分段')
    async with sessions.begin() as db:
        (await db.get(Attachment, material['attachment']['id'])).deleted = True
    async with sessions() as db:
        with pytest.raises(HTTPException):
            await lease(db, context)
