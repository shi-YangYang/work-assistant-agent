"""Accepted upload names remain unique and bounded in execution inputs."""
import base64

import pytest

from app.modules.executions.files import prepare_inputs
from app.modules.messages.models import Message
from app.tasks.models import Job
from _support.http.management import conversation, message
from _support.materials.documents import upload

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('names', [
    ['report.csv', '3-report.csv', 'report.csv', 'report.csv'],
    ['x' * 176 + '.csv'] * 3,
    ['季度汇总.csv', '季度汇总.csv', '3-季度汇总.csv', '季度汇总.csv'],
])
async def test_duplicate_names_preserve_each_file_and_fit_sandbox_protocol(setup, names):
    settings, sessions, users, clients = setup
    client = clients['employee']
    originals = [f'index,value\n{index},sample\n'.encode() for index in range(len(names))]
    attachments = [await upload(client, name, data, 'text/csv') for name, data in zip(names, originals)]
    sent = await message(client, await conversation(client), '合并这些附件', [row['id'] for row in attachments])
    async with sessions() as db:
        job = await db.get(Job, sent['jobId'])
        current = await db.get(Message, sent['messageId'])
        files, sources = await prepare_inputs(db, users['employee'], job, current, settings,
                                              [{'attachment_id': row['id']} for row in attachments])
    assert len(files) == len({file['name'] for file in files}) == len(names)
    assert files[0]['name'] == names[0]
    assert all(len(file['name']) <= 180 and file['name'].endswith('.csv') for file in files)
    assert [base64.b64decode(file['data']) for file in files] == originals
    assert [source['id'] for source in sources] == [row['id'] for row in attachments]
