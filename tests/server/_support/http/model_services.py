"""Shared controlled fixtures extracted from test_model_services."""



SECRET='controlled-key-not-real'


def payload(name='服务甲', url='https://example.com/v1'):
    return {'name': name, 'baseUrl': url, 'apiKey': SECRET, 'models': [{'id': 'chat', 'model': 'controlled-chat', 'protocol': 'chat'}, {'id': 'audio', 'model': 'controlled-asr', 'protocol': 'transcriptions'}], 'expectedRevision': 0}


async def create(c, body=None):
    response = await c.post('/api/v1/settings/model-services', json=body or payload())
    assert response.status_code == 201, response.text
    return response.json()


def route(saved, revision=0):
    choice = {'serviceId': saved['id'], 'modelId': 'chat'}
    return {'expectedRevision': revision, 'assistant': choice, 'report': 'follow', 'asr': {**choice, 'modelId':'audio'}}
