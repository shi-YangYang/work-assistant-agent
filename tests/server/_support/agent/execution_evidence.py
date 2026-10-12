"""Shared controlled fixtures extracted from test_execution_evidence."""
from app.tasks.context import RunContext
from app.tasks.runtime.queue import claim
from _support.http.company import keyed


async def followup(setup, conversation_id=None, who='employee'):
    settings, sessions, users, clients = setup
    response = await clients[who].post('/api/v1/messages', headers=keyed(), json={
        'text': '刚才实际输出是什么？不要重新运行。',
        **({'conversationId': conversation_id} if conversation_id else {'newConversation': True})})
    assert response.status_code == 202, response.text
    job = await claim(sessions, users[who].id)
    return RunContext(job.owner_id, job.company_id, job.id, job.fence, sessions, settings, source_revision=0)
