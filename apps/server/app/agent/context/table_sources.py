"""Bind actual table observations to sources after a successful model delivery."""
import json

from app.modules.attachments.documents import agent_attachment
from app.modules.executions.queries import authorize, execution_query
from app.modules.executions.models import SandboxExecution
from app.modules.messages.models import Message
from app.security.ownership import owned
from app.tasks.context import InputChanged


def table_receipts(messages):
    calls = {call.get('id') for message in messages for call in (message.get('tool_calls') or [])
             if call.get('function', {}).get('name') == 'inspect_table'}
    receipts = {}
    for message in messages:
        if (message.get('role') != 'tool' or not isinstance(message.get('content'), str)
                or not (message.get('name') == 'inspect_table' or message.get('tool_call_id') in calls)):
            continue
        try:
            value = json.loads(message['content'])
        except ValueError:
            continue
        if (isinstance(value, dict) and value.get('state') == 'succeeded' and value.get('tool') == 'inspect_table'
                and isinstance(value.get('executionId'), str) and isinstance(value.get('data'), dict)):
            receipts[value['executionId']] = value
    return receipts


async def delivered_tables(db, context, job, actor, receipts):
    if not receipts:
        return {}
    current = await owned(db, Message, job.target_id, actor)
    records = (await db.execute(execution_query(actor, current).where(SandboxExecution.id.in_(receipts)))).all()
    delivered = {}
    for row, message, origin in records:
        receipt = receipts[row.id]
        if (row.state != 'succeeded' or not row.request or row.request.get('name') != 'inspect_table'
                or any(receipt.get(field) != row.result.get(field) for field in ('state', 'tool', 'data', 'warnings', 'inputRefs'))):
            continue
        source = row.request['arguments']['source']
        identifier = source.get('input_ref', {}).get('attachment_id')
        # A derived workbook is a deliverable source, not the original attachment.
        # Do not attribute its computed cells to every indirect source of the run.
        if not identifier:
            continue
        await authorize(db, actor, job, row, message, origin)
        item = await agent_attachment(db, identifier, actor, job)
        reference = next((ref for ref in row.sources if ref.get('kind') == 'attachment' and ref.get('id') == identifier), None)
        if not reference or item.kind != 'document':
            continue
        if item.extraction_revision != reference['revision'] or item.sha256 != reference['sha256']:
            raise InputChanged(document=True)
        data = receipt['data']
        sheet = source.get('sheet', '')
        location = (f'工作表「{sheet}」· ' if sheet else '') + '表格统计与返回样本'
        samples = data.get('sample', [])
        sample_start = data.get('sampleStartRow')
        sample_rows = list(range(sample_start, sample_start + len(samples))) if type(sample_start) is int else []
        sample_rows.extend(sample['rowNumber'] for sample in data.get('contentSamples', [])
                           if isinstance(sample, dict) and type(sample.get('rowNumber')) is int)
        delivered[row.id] = {'attachmentId': identifier, 'revision': reference['revision'], 'sha256': reference['sha256'],
                             'executionId': row.id, 'location': location, 'sheet': sheet,
                             'sampleRows': sorted(set(sample_rows)), 'rowCount': data.get('rowCount'),
                             'sampleTruncated': data.get('sampleTruncated'), 'tool': 'inspect_table'}
    return delivered
