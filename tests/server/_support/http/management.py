"""Shared controlled fixtures extracted from test_management."""
from _support.http.company import keyed


async def conversation(client, title='新会话'):
    response = await client.post('/api/v1/conversations', json={'title': title})
    assert response.status_code == 201
    return response.json()


async def message(client, conv, value='方案初稿完成', attachments=None, **extra):
    response = await client.post('/api/v1/messages', json={'conversationId':conv['id'], 'text':value, 'attachmentIds': attachments or [], **extra}, headers=keyed())
    assert response.status_code == 202, response.text
    return response.json()


async def remove(client, kind, item):
    return await client.request('DELETE', f"/api/v1/{kind}/{item['id']}", json={'expectedRevision': item.get('managementRevision', item['revision'])})
