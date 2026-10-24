"""Retire formal daily reports without deleting their original work or messages.

Stop old API/workers and take a restorable backup before running this migration.
Only caches linked by structured identities are invalidated; chat prose is kept.
"""
from alembic import op
import sqlalchemy as sa
import json

revision = '0034_remove_daily_reports'
down_revision = '0033_report_regeneration'
branch_labels = depends_on = None

NOTICE = '正式日报已取消，原日报记录与操作已失效'
MARKER = {'reportRetired': True, 'state': 'cancelled', 'message': NOTICE}
ACTIVE_JOBS = ('queued', 'running', 'failed', 'awaiting_retry', 'awaiting_input')
WAITING_NODES = ('waiting', 'running', 'retry_wait', 'awaiting_input', 'awaiting_confirmation')
REFERENCE_KEYS = ('id', 'objectId', 'targetId', 'reportId', 'obligationId', 'jobId',
                  'receiptId', 'operationId', 'versionId', 'interactionId', 'waitingInteractionId')


def upgrade():
    db = op.get_bind()
    metadata = sa.MetaData()
    def table(name):
        return sa.Table(name, metadata, autoload_with=db)
    reports, obligations = table('company_report'), table('company_report_obligation')
    actions, jobs = table('company_business_action'), table('company_job')
    report_ids = set(db.scalars(sa.select(reports.c.id).where(reports.c.kind == 'daily')))
    obligation_ids = set(db.scalars(sa.select(obligations.c.id).where(obligations.c.kind == 'daily')))
    job_rows = list(db.execute(sa.select(jobs)).mappings())
    job_ids = {row['id'] for row in job_rows if row['kind'] == 'report' and row['target_id'] in report_ids}
    action_rows = list(db.execute(sa.select(actions)).mappings())
    def daily_request(value):
        return value.get('action', '').endswith('_report') and (value.get('kind') == 'daily' or value.get('report_kind') == 'daily')
    def references(value, identifiers):
        if isinstance(value, dict):
            return any(key in identifiers or (key in REFERENCE_KEYS and isinstance(item, str) and item in identifiers) or references(item, identifiers) for key, item in value.items()) or daily_request(value)
        if isinstance(value, list):
            return any(references(item, identifiers) or isinstance(item, str) and item in identifiers for item in value)
        if isinstance(value, str) and value.lstrip().startswith(('{', '[')):
            try:
                return references(json.loads(value), identifiers)
            except (ValueError, TypeError):
                pass
        return False
    revisions = table('company_report_revision')
    revision_ids = set(db.scalars(sa.select(revisions.c.id).where(revisions.c.report_id.in_(report_ids))))
    ids = report_ids | revision_ids | obligation_ids | job_ids
    action_ids = {row['id'] for row in action_rows if row['action'].endswith('_report') and (row['params'].get('kind') == 'daily' or references(row['params'], ids) or references(row['result'], ids))}
    ids |= action_ids
    interactions = table('company_assistant_interaction')
    interaction_rows = list(db.execute(sa.select(interactions)).mappings())
    interaction_ids = {row['id'] for row in interaction_rows
                       if any(references(row[column], ids) for column in ('questions', 'answers', 'sources', 'access', 'continuation'))}
    ids |= interaction_ids
    affected_messages = {row['message_id'] for row in action_rows if row['id'] in action_ids}
    affected_messages.update(row['message_id'] for row in interaction_rows if row['id'] in interaction_ids)
    affected_conversations = {row['conversation_id'] for row in action_rows if row['id'] in action_ids and row['conversation_id']}
    affected_jobs = set(job_ids)
    cancelled_messages = set()
    def scrub(value):
        if isinstance(value, dict):
            if value.get('type') == 'report' and value.get('id') in report_ids:
                return {key: item for key, item in value.items() if key in ('type', 'id', 'ownerId', 'versionId', 'version')}
            # Node identity/shape is required by message DTOs. Drop the retired
            # request/output while retaining a non-resumable terminal node.
            if {'scope', 'state', 'id', 'kind', 'label', 'attempts'} <= value.keys() and references(value, ids):
                node = {key: item for key, item in value.items()
                        if key in ('id', 'parentId', 'scope', 'kind', 'label', 'attempts', 'maxAttempts', 'totalRetries', 'round')}
                return {**node, 'state': 'cancelled', 'resumable': False,
                        'nextAt': None, 'error': NOTICE, 'errorCode': 'cancelled'}
            direct = any(key in REFERENCE_KEYS and key != 'waitingInteractionId'
                         and isinstance(item, str) and item in ids for key, item in value.items())
            if direct or daily_request(value):
                return dict(MARKER)
            cleaned = {key: ([scrub(entry) for entry in item if not references(entry, ids)]
                             if key in ('toolOutcomes', 'taskItems', 'operationFeedback') and isinstance(item, list)
                             else scrub(item)) for key, item in value.items() if key not in ids}
            return cleaned
        if isinstance(value, list):
            return [scrub(item) for item in value if not isinstance(item, str) or item not in ids]
        if isinstance(value, str) and value.lstrip().startswith(('{', '[')):
            try:
                parsed = json.loads(value)
                if references(parsed, ids):
                    return json.dumps(scrub(parsed), ensure_ascii=False)
            except (ValueError, TypeError):
                pass
        return value
    def finish_wait(result, *, question=None, pending=False):
        result = dict(result)
        # TaskInterpretation has no cancelled state. Match settle()'s terminal
        # interpretation; cancellation belongs to Job and the outcome projection.
        state = 'needs_input' if question else 'needs_confirmation' if pending else 'completed'
        remaining = [item['prompt'] for item in question['questions']] if question else []
        for key in ('taskInterpretation', 'intentTaskInterpretation', 'explicitTaskContext'):
            if key in result or key == 'taskInterpretation':
                result[key] = {**result.get(key, {}), 'state': state, 'remaining': remaining}
        for key in ('waitingInteractionId', 'questionCandidate', 'completionWait', 'continuation',
                    'incompleteTask', 'completionIssue', 'taskBarriers'):
            result.pop(key, None)
        if question:
            result['waitingInteractionId'] = question['id']
        result['taskOutcome'] = {'state': state if question or pending else 'cancelled',
                                 'completed': result.get('taskOutcome', {}).get('completed', []),
                                 'remaining': remaining, 'reason': NOTICE,
                                 'nextAction': 'reply' if question else 'confirm' if pending else 'none'}
        return result
    # Action params are cleared after success; result IDs and child jobs are
    # deliberately included, so old successful snapshots cannot escape cleanup.
    for row in action_rows:
        if row['id'] in action_ids:
            db.execute(actions.update().where(actions.c.id == row['id']).values(state='cancelled', params={}, result=MARKER, continuation={}, revision=row['revision'] + 1))
    for row in job_rows:
        linked = row['id'] in job_ids or references(row['result'], ids) or references(row['access'], ids) or row['kind'] == 'message' and row['target_id'] in affected_messages
        if not linked:
            continue
        affected_jobs.add(row['id'])
        if row['kind'] == 'message':
            affected_messages.add(row['target_id'])
        values = {'result': {} if row['id'] in job_ids else scrub(row['result']), 'access': scrub(row['access']), 'feedback': {} if row['id'] in job_ids else scrub(row['feedback'])}
        if row['id'] in job_ids or row['state'] in ACTIVE_JOBS:
            values.update(state='cancelled', phase='report_retired', error=NOTICE, fence=row['fence'] + 1, lease_until=None)
            if row['kind'] == 'message':
                # An unrelated pending card/question in this same message still
                # owns its wait. Only retired structured references are removed.
                question = next((item for item in interaction_rows if item['job_id'] == row['id']
                                 and item['state'] == 'waiting' and item['id'] not in interaction_ids), None)
                pending = any(item['message_id'] == row['target_id'] and item['state'] == 'pending'
                              and item['id'] not in action_ids for item in action_rows)
                keep_wait = row['state'] == 'awaiting_input' and (question or pending)
                values['result'] = finish_wait(values['result'], question=question if keep_wait else None,
                                              pending=pending if keep_wait else False)
                if keep_wait:
                    values.update(state='awaiting_input', phase='awaiting_answer' if question else 'awaiting_confirmation', error='')
                else:
                    cancelled_messages.add(row['target_id'])
                    for node in values['result'].get('nodeExecution', {}).get('nodes', []):
                        if node.get('state') in WAITING_NODES:
                            node.update(state='cancelled', nextAt=None, resumable=False, error=NOTICE, errorCode='cancelled')
                values['feedback'] = {**values['feedback'], 'seq': values['feedback'].get('seq', 0) + 1,
                                      'stage': 'complete', 'text': '', 'callId': None}
            values['updated_at'] = sa.func.now()
        db.execute(jobs.update().where(jobs.c.id == row['id']).values(**values))
    for row in interaction_rows:
        if row['id'] in interaction_ids or row['message_id'] in cancelled_messages and row['state'] == 'waiting':
            db.execute(interactions.update().where(interactions.c.id == row['id']).values(
                state='cancelled', questions=[], answers=[], sources=scrub(row['sources']),
                access=scrub(row['access']), continuation={}, revision=row['revision'] + 1,
                updated_at=sa.func.now()))
    def retire_previous_tasks(value):
        if isinstance(value, list):
            return [retire_previous_tasks(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: retire_previous_tasks(item) for key, item in value.items()}
        for key in ('previousTask', 'task'):
            task = result.get(key)
            if isinstance(task, dict) and task.get('messageId') in cancelled_messages:
                result[key] = {**task, 'state': 'cancelled', 'remaining': [], 'question': []}
        return result
    # Later, unrelated inputs may still carry a previousTask snapshot. End only
    # that retired task's projection, without cancelling the newer job/input.
    for row in db.execute(sa.select(jobs.c.id, jobs.c.result)).mappings():
        result = retire_previous_tasks(row['result'])
        if result != row['result']:
            db.execute(jobs.update().where(jobs.c.id == row['id']).values(result=result))
    # Keep all original message fields, work content/revisions and attachments.
    # Only structured sources, cards and derived context are cleaned.
    for name, columns in {
        'company_message': ('access', 'citations', 'suggestions'),
        'company_work_item': ('access', 'business_links'),
        'company_work_revision': ('access', 'business_links'),
        'company_progress_draft': ('access', 'business_links'),
        'company_conversation_task_state': ('payload',),
    }.items():
        if name not in sa.inspect(db).get_table_names():
            continue
        target = table(name)
        columns = [column for column in columns if column in target.c]
        for row in db.execute(sa.select(target)).mappings():
            changes = {column: scrub(row[column]) for column in columns if references(row[column], ids)}
            if name == 'company_conversation_task_state':
                payload = changes.get('payload', row['payload'])
                retired = retire_previous_tasks(payload)
                if retired != payload:
                    changes['payload'] = retired
                if changes:
                    changes.update(revision=row['revision'] + 1, updated_at=sa.func.now())
            if name == 'company_message':
                # Retain readable original chat while dropping only retired
                # source credentials and structured citation/suggestion cards.
                if 'access' in changes:
                    changes['access'] = {**row['access'], 'reads': {key: evidence for key, evidence in row['access'].get('reads', {}).items() if not references(evidence, ids)}}
                for column in ('citations', 'suggestions'):
                    if column in changes:
                        changes[column] = [item for item in row[column] if not references(item, ids)]
            if name == 'company_message' and (changes or row['id'] in affected_messages):
                if row['conversation_id']:
                    affected_conversations.add(row['conversation_id'])
            if changes:
                key = list(target.primary_key.columns)[0]
                db.execute(target.update().where(key == row[key.name]).values(**changes))
    contexts = table('company_conversation_context')
    for row in db.execute(sa.select(contexts)).mappings():
        if row['conversation_id'] in affected_conversations or references(row['payload'], ids):
            db.execute(contexts.update().where(contexts.c.conversation_id == row['conversation_id']).values(payload={}, revision=row['revision'] + 1, invalidation_version=row['invalidation_version'] + 1))
    idem = table('company_idempotency')
    for row in db.execute(sa.select(idem)).mappings():
        if references(row['response'], ids) or any(row['action'] == prefix + identifier for prefix, group in (('submit:', report_ids), ('prepare-obligation:', obligation_ids)) for identifier in group):
            db.execute(idem.delete().where(idem.c.id == row['id']))
    # Remove only job-specific derived graph caches. Never remove a whole
    # owner's/company's conversations or checkpoints by a text keyword.
    for row in job_rows:
        if row['id'] not in affected_jobs:
            continue
        prefix = f"{row['company_id']}:{row['owner_id']}:job:{row['id']}%"
        for name in ('checkpoint_writes', 'checkpoint_blobs', 'checkpoints'):
            if db.scalar(sa.text('SELECT to_regclass(:name)'), {'name': name}):
                db.execute(sa.text(f'DELETE FROM {name} WHERE thread_id LIKE :prefix'), {'prefix': prefix})
    notifications = table('company_report_notification')
    db.execute(notifications.delete().where(notifications.c.obligation_id.in_(obligation_ids)))
    db.execute(obligations.delete().where(obligations.c.id.in_(obligation_ids)))
    schedules = table('company_report_schedule')
    db.execute(schedules.delete().where(schedules.c.kind == 'daily'))
    db.execute(sa.text("UPDATE company SET rules = rules - 'daily' WHERE rules ? 'daily'"))
    revisions = table('company_report_revision')
    db.execute(revisions.delete().where(revisions.c.report_id.in_(report_ids)))
    db.execute(reports.delete().where(reports.c.id.in_(report_ids)))
    # Database guards also protect against an accidentally retained old worker.
    for name in ('company_report', 'company_report_schedule', 'company_report_obligation'):
        op.create_check_constraint('ck_' + name + '_weekly', name, "kind = 'weekly'")


def downgrade():
    raise RuntimeError('日报正文已永久清理；请停止服务并从迁移前备份恢复，不能通过 downgrade 恢复。')
