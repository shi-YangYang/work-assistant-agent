"""Shared controlled fixtures extracted from test_work_records."""
from uuid import uuid4


def key():
    return {'Idempotency-Key': str(uuid4())}


def body(text='目标与方案'):
    return {'schemaVersion': 1, 'content': [{'type': 'paragraph', 'attrs': {'id': 'first'}, 'content': [{'type': 'text', 'text': text}]}]}


async def create(client, **extra):
    response = await client.post('/api/v1/work-items', json={'title': '客户官网', 'body': body(), **extra}, headers=key())
    assert response.status_code == 201, response.text
    return response.json()
