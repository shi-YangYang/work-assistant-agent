"""Shared controlled fixtures extracted from test_conversation_task_state."""
import json
from langchain_core.messages import AIMessage
from app.agent.context.task_context import load
from app.modules.conversations.task.task_state import finish as save_task
from app.modules.messages.models import Message
from app.tasks.feedback.outcomes import derive
from app.tasks.lease import lease


class ScopedJudge:
    def __init__(self, *, source='', quote='', allowed=True, resume=False, append=(), append_values=None, kind='missing_info', interpretation=None, directive_target='', directive_fields=(), preview=False):
        self.source, self.quote, self.allowed, self.resume, self.append, self.kind = source, quote, allowed, resume, append, kind
        self.inputs = []
        self.interpretation = interpretation
        self.directive_target, self.directive_fields = directive_target, directive_fields
        self.append_values = append_values
        self.preview = preview

    async def ainvoke(self, messages):
        payload = json.loads(messages[-1].content)
        self.inputs.append(payload)
        return AIMessage(content=json.dumps({'allowed': self.allowed, 'quote': self.quote or payload['currentUserText'],
            'quoteMessageId': self.source, 'reason': '' if self.allowed else '请说明要更新的对象',
            'requireConfirmation': self.preview, 'resumeTask': self.resume, 'appendFields': list(self.append),
            'appendValues': self.append_values if self.append_values is not None else {name: payload['proposedOperation']['changes'][name] for name in self.append},
            'failureKind': self.kind, 'taskContext': self.interpretation,
            'directiveTargetId': self.directive_target, 'directiveFields': list(self.directive_fields)}))


async def close_task(context, *, quote='', scope='', state='completed', goal='', relation='new', change=None):
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        message = await db.get(Message, job.target_id)
        await load(context, db, actor, job, message)
        value = {'goal': goal or message.text, 'state': state, 'relation': relation,
            'directiveChange': change or ('replace' if quote else 'keep'), 'directiveQuote': quote,
            'directiveScope': scope, 'remaining': ['需要一个明确对象'] if state == 'needs_input' else []}
        job.state = 'awaiting_input' if state == 'needs_input' else 'succeeded'
        job.result = {**job.result, 'taskInterpretation': value}
        from app.modules.operations.receipts import message_actions
        from app.modules.work.drafts.draft_receipts import message_drafts
        outcome = derive(job, await message_actions(db, actor, message), await message_drafts(db, actor, message, job), interpretation=value)
        await save_task(db, actor, job, message, value, outcome)
        job.lease_until = None


async def cancel_running(setup, context):
    response = await setup[3]['employee'].post('/api/v1/jobs/' + context.job_id + '/cancel',
        json={'expectedAttempt': 0, 'expectedFence': context.fence})
    assert response.status_code == 200 and response.json()['state'] == 'cancelled', response.text
