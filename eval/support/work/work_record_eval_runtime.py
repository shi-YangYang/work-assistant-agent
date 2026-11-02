"""Serial real-harness runner with public API writes and durable-state probes."""
import asyncio
from contextlib import ExitStack
from dataclasses import replace
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
from uuid import uuid4

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select, text

from app.agent.harness import build_graph
from app.core.config import Settings
from app.modules.attachments.models import Attachment
from app.modules.members.models import Company
from app.modules.messages.models import Message
from app.modules.model_services.models import ModelUsage
from app.modules.operations.models import BusinessAction
from app.modules.reports.models import Report, ReportRevision
from app.modules.work.models import WorkItem, WorkMaterial, WorkRevision, WorkUpdate, WorkUpdateRevision
from app.tasks.context import RunContext
from app.tasks.models import Job
from app.tasks.processing.handlers import process_job
from app.tasks.runtime.queue import claim
from conftest import setup
from eval.support.work.work_record_eval_cases import SUITE_REVISION
from eval.support.work.work_record_eval_materials import (
    BASE_TEXT, MANUAL_TEXT, EvaluationBlocked, document, downloaded, redact,
    upload_material,
)


def keyed():
    return {'Idempotency-Key': str(uuid4())}


class EvaluationAPIError(RuntimeError):
    def __init__(self, response, expected):
        super().__init__('评测 API 返回非预期状态')
        try:
            error = response.json()
        except ValueError:
            error = {'message': '响应不是 JSON'}
        self.details = {'path': response.request.url.path, 'method': response.request.method, 'expectedStatus': expected, 'actualStatus': response.status_code, 'error': redact(error)}


def check_response(response, expected):
    if response.status_code != expected:
        raise EvaluationAPIError(response, expected)
    return response.json()


class WorkRecordRun:
    def __init__(self, case, fixture, checked, directory):
        self.case = case
        self.settings, self.sessions, self.users, self.clients = fixture
        self.actor, self.client = self.users[case.role], self.clients[case.role]
        self.checked, self.directory = check_response, directory
        self.work, self.conversation, self.saver = None, None, None
        self.uploads, self.messages = {}, []
        self.turn_index, self.injected, self.block_provider = -1, False, False
        self.snapshot = {'suiteRevision': SUITE_REVISION, 'phases': [], 'hooks': [], 'materials': [], 'providerInputs': [], 'providerFailures': [], 'confirmations': []}

    async def create(self, client=None, **body):
        return self.checked(await (client or self.client).post('/api/v1/work-items', json=body, headers=keyed()), 201)

    async def read_work(self, client=None):
        return self.checked(await (client or self.client).get('/api/v1/work-items/' + self.work['id']), 200)

    async def patch_work(self, body, client=None):
        current = await self.read_work(client)
        result = self.checked(await (client or self.client).patch('/api/v1/work-items/' + current['id'], json={'expectedRevision': current['revision'], **body}, headers=keyed()), 200)
        self.work = result['work']
        return result

    async def add_update(self, value, client=None):
        current = await self.read_work(client)
        result = self.checked(await (client or self.client).post('/api/v1/work-items/' + current['id'] + '/updates', json={'expectedRevision': current['revision'], 'text': value}, headers=keyed()), 201)
        self.work = result['work']
        return result

    async def prepare(self):
        path = '/api/v1/assistant/execution-settings'
        before = self.checked(await self.client.get(path), 200)
        mode = self.checked(await self.client.patch(path, json={'expectedRevision': before['modeRevision'], 'executionMode': self.case.mode, 'fullAccessConfirmed': self.case.mode == 'full'}), 200)
        self.snapshot['executionSettings'] = mode
        self.snapshot['peerExecutionSettings'] = self.checked(await self.clients['peer'].get(path), 200)
        owner = self.clients['employee'] if self.case.setup == 'employee_work' else self.client
        for kind in self.case.materials:
            row, evidence = await upload_material(owner, kind, self.directory, self.settings, self.checked)
            self.uploads[kind] = row
            self.snapshot['materials'].append(evidence)
        if self.case.setup == 'empty':
            self.snapshot['initial'] = await self.state()
            return
        body = document(BASE_TEXT)
        self.work = await self.create(owner, title='客户官网改版', body=body)
        if self.case.id == 'A03':
            await self.patch_work({'body': document(BASE_TEXT, '固定验收口径：保留产品历史链接。')})
        bind = self.case.id not in ('A04', 'A08', 'A19')
        if self.case.setup == 'deleted_source':
            # Establish a real prior upload/message through public APIs. Its task
            # is deliberately cancelled before model execution; no fake reply.
            sent = self.checked(await owner.post('/api/v1/messages', json={
                'text': '这些是客户资料，稍后再处理。', 'newConversation': True,
                'attachmentIds': [row['id'] for row in self.uploads.values()],
            }, headers=keyed()), 202)
            await self.cancel(sent, owner)
            self.snapshot['sourceMessage'] = sent
        if bind and self.uploads:
            selected = [row for kind, row in self.uploads.items() if kind != 'private']
            await self.patch_work({'materials': [{'attachmentId': row['id']} for row in selected]}, owner)
            await self.drain(owner_id=self.users['employee'].id if self.case.setup == 'employee_work' else self.actor.id)
        if self.case.setup == 'deleted_source':
            sent = self.snapshot['sourceMessage']
            conv = self.checked(await owner.get('/api/v1/conversations/' + sent['conversationId']), 200)
            self.checked(await owner.request('DELETE', '/api/v1/conversations/' + conv['id'], json={'expectedRevision': conv['revision']}), 200)
            self.snapshot['privateDownloadAfterSourceDeletion'] = (await owner.get(self.uploads['private']['url'])).status_code
        if self.case.setup == 'duplicate':
            other = await self.create(title='客户官网改版', body=document('另一项同名工作：这个内容不能修改。'))
            self.snapshot['untouchedWorkId'] = other['id']
        if self.case.setup in ('update', 'employee_work'):
            await self.add_update('客户约周三评审首页。', owner)
        if self.case.setup == 'report':
            await self.patch_work({'body': document(BASE_TEXT, '未来计划：下周完成移动端上线，当前尚未完成。')})
            await self.add_update('已完成客户需求核对，确认在线询价入口。')
            await self.add_update('已完成首页初稿，并收到客户确认。')
        self.snapshot['targetWorkId'] = self.work['id']
        async with self.sessions() as db:
            company = await db.get(Company, self.actor.company_id)
            self.snapshot['companyTimezone'] = company.rules['timezone']
        self.snapshot['initial'] = await self.state()

    async def cancel(self, sent, client=None):
        client = client or self.client
        value = self.checked(await client.get('/api/v1/messages/' + sent['messageId']), 200)
        job = value['job']
        return self.checked(await client.post('/api/v1/jobs/' + sent['jobId'] + '/cancel', json={'expectedAttempt': job['attempt'], 'expectedFence': job['fence']}), 200)

    async def drain(self, owner_id=None):
        for _ in range(16):
            job = await claim(self.sessions, owner_id or self.actor.id)
            if job is None:
                return
            async with asyncio.timeout(480):
                await process_job(job, self.sessions, self.settings, self.saver)
        raise AssertionError('任务队列超过本场景 16 个任务的执行边界')

    async def state(self):
        async with self.sessions() as db:
            works = list((await db.scalars(select(WorkItem).where(WorkItem.company_id == self.actor.company_id).order_by(WorkItem.created_at, WorkItem.id))).all())
            revisions = list((await db.scalars(select(WorkRevision).where(WorkRevision.company_id == self.actor.company_id).order_by(WorkRevision.created_at, WorkRevision.id))).all())
            updates = list((await db.scalars(select(WorkUpdate).where(WorkUpdate.company_id == self.actor.company_id).order_by(WorkUpdate.created_at, WorkUpdate.id))).all())
            history = list((await db.scalars(select(WorkUpdateRevision).where(WorkUpdateRevision.company_id == self.actor.company_id).order_by(WorkUpdateRevision.created_at))).all())
            materials = list((await db.scalars(select(WorkMaterial).where(WorkMaterial.company_id == self.actor.company_id).order_by(WorkMaterial.created_at))).all())
            reports = list((await db.scalars(select(Report).where(Report.company_id == self.actor.company_id))).all())
            report_history = list((await db.scalars(select(ReportRevision).where(ReportRevision.company_id == self.actor.company_id).order_by(ReportRevision.created_at))).all())
            actions = list((await db.scalars(select(BusinessAction).where(BusinessAction.company_id == self.actor.company_id).order_by(BusinessAction.created_at))).all())
            files = []
            for row in materials:
                attachment = await db.get(Attachment, row.attachment_id)
                files.append({'id': row.id, 'workId': row.work_id, 'attachmentId': row.attachment_id, 'removed': row.removed, 'revision': row.revision, 'source': row.source, 'sha256': attachment.sha256, 'kind': attachment.kind, 'extractionStatus': attachment.extraction_status, 'transcript': attachment.extraction_info.get('transcript'),
                    'download': await downloaded(self.clients[next(role for role, member in self.users.items() if member.id == row.owner_id)], {'id': attachment.id, 'name': attachment.name, 'size': attachment.size, 'url': '/api/v1/uploads/' + attachment.id + '/content'})})
            result = {
                'works': [{'id': w.id, 'ownerId': w.owner_id, 'title': w.title, 'deleted': w.deleted, 'revision': w.revision, 'content': w.content} for w in works],
                'workRevisions': [{'id': r.id, 'workId': r.work_id, 'revision': r.revision, 'content': r.content, 'origin': r.origin, 'createdAt': r.created_at.isoformat()} for r in revisions],
                'updates': [{'id': u.id, 'workId': u.work_id, 'revision': u.revision, 'text': u.text, 'deleted': u.deleted, 'materialIds': u.material_ids, 'origin': u.origin} for u in updates],
                'updateRevisions': [{'updateId': u.update_id, 'revision': u.revision, 'text': u.text, 'deleted': u.deleted} for u in history],
                'materials': files,
                'reports': [{'id': r.id, 'content': r.content, 'candidate': r.candidate, 'sourceIds': r.source_ids, 'publishedRevision': r.published_revision, 'revision': r.revision} for r in reports],
                'reportRevisions': [{'reportId': r.report_id, 'revision': r.revision, 'content': r.content, 'sourceIds': r.source_ids} for r in report_history],
                'actions': [{'id': a.id, 'messageId': a.message_id, 'action': a.action, 'mode': a.execution_mode, 'state': a.state, 'params': a.params, 'result': a.result} for a in actions],
            }
            return copy.deepcopy(result)

    async def before_turn(self, index):
        self.turn_index = index
        if self.case.hook == 'new_conversation' and index == 1:
            row, evidence = await upload_material(self.client, 'new_requirement', self.directory, self.settings, self.checked)
            self.snapshot['materials'].append(evidence)
            await self.patch_work({'materials': [{'attachmentId': row['id']}]})
            await self.drain()
            self.snapshot['hooks'].append({'type': 'manual_material_added_between_conversations', 'workRevision': self.work['revision'], 'attachmentId': row['id']})
            self.conversation = None
        if self.case.hook == 'delete_work' and index == 1:
            current = await self.read_work()
            self.checked(await self.client.request('DELETE', '/api/v1/work-items/' + current['id'], json={'expectedRevision': current['revision']}), 200)
            self.snapshot['hooks'].append({'type': 'deleted_work_between_turns', 'workId': current['id']})
            self.snapshot['afterExternalDeletion'] = await self.state()

    async def run_turn(self, prompt, index):
        await self.before_turn(index)
        prompt = prompt.replace('{{employee_name}}', self.users['employee'].name)
        attachments = []
        if self.case.id == 'A10' and index == 2:
            row, evidence = await upload_material(self.client, 'silence', self.directory, self.settings, self.checked)
            attachments.append(row['id'])
            self.snapshot['materials'].append(evidence)
        if (self.case.id in ('A04', 'A08', 'A19') and index == 0) or (self.case.id == 'A01' and index == 1):
            attachments = [row['id'] for row in self.uploads.values()]
        if self.case.id == 'A01' and index == 1:
            own = [w for w in (await self.state())['works'] if not w['deleted'] and w['ownerId'] == self.actor.id]
            if len(own) == 1:
                self.work = own[0]
                self.snapshot['targetWorkId'] = own[0]['id']
        body = {'text': prompt, 'attachmentIds': attachments, 'personaId': 'professional'}
        body.update({'conversationId': self.conversation} if self.conversation else {'newConversation': True})
        use_reference = self.work and self.case.role == 'employee' and not (self.case.id == 'A13' and index > 0) and not (self.case.hook == 'delete_work' and index > 0)
        if use_reference:
            body['workReference'] = {'workId': self.work['id']}
        sent = self.checked(await self.client.post('/api/v1/messages', json=body, headers=keyed()), 202)
        self.conversation = sent['conversationId']
        self.messages.append(sent)
        started = time.monotonic()
        await self.drain()
        value = self.checked(await self.client.get('/api/v1/messages/' + sent['messageId']), 200)
        if self.case.hook == 'lost_receipt' and index == 0 and self.injected:
            before_retry = {'beforeRetry': value, 'savedBeforeRetry': await self.state()}
            self.block_provider = False
            if value['job']['state'] in ('failed', 'awaiting_retry'):
                retry = self.checked(await self.client.post('/api/v1/jobs/' + sent['jobId'] + '/retry', json={}), 200)
                self.snapshot['hooks'].append({'type': 'manual_retry_after_lost_receipt', **before_retry, 'retryResponse': retry})
                await self.drain()
                value = self.checked(await self.client.get('/api/v1/messages/' + sent['messageId']), 200)
            else:
                self.snapshot['hooks'].append({'type': 'manual_retry_not_available', 'state': value['job']['state'], **before_retry})
        if self.case.mode == 'ask':
            await self.confirm(value)
            value = self.checked(await self.client.get('/api/v1/messages/' + sent['messageId']), 200)
        generated = []
        for deliverable in value.get('deliverables', []):
            for file in deliverable.get('files', []):
                generated.append({**await downloaded(self.client, file), 'deliverableId': deliverable['id'], 'deliverableRevision': deliverable['revision']})
        async with self.sessions() as db:
            message = await db.get(Message, sent['messageId'])
            job = await db.get(Job, sent['jobId'])
            evidence = {'documentReads': job.result.get('documentReads', {}), 'result': job.result, 'transcript': message.transcript, 'transcriptRevision': message.transcript_revision}
        self.snapshot['phases'].append({'index': index, 'prompt': prompt, 'request': body, 'message': value, 'generatedFiles': generated, 'evidence': evidence, 'seconds': round(time.monotonic() - started, 2), 'state': await self.state()})

    async def confirm(self, value):
        pending = [a for a in value.get('actions', []) if a['state'] == 'pending']
        entry = {'messageId': value['id'], 'before': await self.state(), 'cards': pending, 'confirmed': []}
        self.snapshot['confirmations'].append(entry)
        for action in pending:
            async with self.sessions() as db:
                receipt = await db.get(BusinessAction, action['id'])
                target = receipt.params.get('targetId') if receipt else None
                changes = receipt.params.get('changes', {}) if receipt else {}
            preview = action.get('preview', {})
            if action['action'] != 'update_work' or target != self.work['id'] or preview.get('title') != self.work['title'] or not changes or set(changes) - {'body', 'bodyEdits'}:
                entry['rejectedUnexpectedAction'] = action
                continue
            result = self.checked(await self.client.post('/api/v1/business-actions/' + action['id'] + '/confirm', json={'expectedRevision': action['revision']}), 200)
            entry['confirmed'].append(result)
        if entry['confirmed']:
            await self.drain()
        entry['after'] = await self.state()

    def observers(self):
        from app.integrations.models.chat import chat
        from app.agent.tools.business.actions import actions_execute
        from app.integrations.models.transport import ProviderError
        stack = ExitStack()

        async def observe_chat(settings, config, key, messages, **kwargs):
            if self.block_provider:
                self.snapshot['hooks'].append({'type': 'controlled_timeout_after_committed_write', 'turn': self.turn_index})
                raise ProviderError('timeout', '受控评测：提交后回执丢失，暂停后续模型调用以验证手动重试')
            images = [part for msg in messages if isinstance(msg.get('content'), list) for part in msg['content'] if isinstance(part, dict) and part.get('type') in ('image_url', 'image')]
            self.snapshot['providerInputs'].append({'turn': self.turn_index, 'model': config['model'], 'imageBlocks': len(images), 'imageHashes': [hashlib.sha256(json.dumps(part, sort_keys=True).encode()).hexdigest() for part in images], 'messageCount': len(messages)})
            try:
                return await chat(settings, config, key, messages, **kwargs)
            except ProviderError as error:
                message = str(error).replace(key, '[REDACTED]') if key else str(error)
                self.snapshot['providerFailures'].append({'turn': self.turn_index, 'code': error.code, 'httpStatus': error.status, 'message': message[:400], 'imageBlocks': len(images)})
                raise

        async def controlled_action(context, *args, **kwargs):
            scoped = context.owner_id == self.actor.id
            if scoped and self.case.hook == 'concurrent_edit' and self.turn_index == 1 and not self.injected:
                self.injected = True
                before = await self.read_work()
                await self.patch_work({'bodyEdits': [{'action': 'append', 'blocks': document(MANUAL_TEXT)['content']}]})
                self.snapshot['hooks'].append({'type': 'concurrent_api_edit_before_agent_write', 'agentExpectedRevision': kwargs.get('expected_revision'), 'beforeRevision': before['revision'], 'afterRevision': self.work['revision']})
            try:
                result = await actions_execute(context, *args, **kwargs)
            except Exception as error:
                if scoped and self.case.hook == 'concurrent_edit':
                    self.snapshot['hooks'].append({'type': 'agent_write_after_external_edit', 'errorType': type(error).__name__, 'httpStatus': getattr(error, 'status_code', None)})
                raise
            if scoped and self.case.hook == 'concurrent_edit' and self.turn_index == 1:
                self.snapshot['hooks'].append({'type': 'agent_write_after_external_edit', 'state': result.get('state'), 'message': result.get('message', '')})
            if scoped and not self.injected and self.turn_index == 0 and result.get('state') == 'succeeded':
                if self.case.hook == 'lost_receipt':
                    self.injected = self.block_provider = True
                    self.snapshot['hooks'].append({'type': 'committed_write_response_dropped', 'receipt': result})
                    raise ConnectionError('controlled response loss after committed work write')
                if self.case.hook == 'interrupt':
                    self.injected = True
                    cancelled = await self.cancel(self.messages[-1])
                    self.snapshot['hooks'].append({'type': 'user_cancel_after_first_saved_step', 'receipt': result, 'cancelResponse': cancelled, 'savedAtInterruption': await self.state()})
            return result

        stack.enter_context(patch('app.integrations.models.chat.chat', observe_chat))
        stack.enter_context(patch('app.agent.tools.business.actions.actions_execute', controlled_action))
        return stack

    async def finish(self):
        traces = []
        async with self.sessions() as db:
            threads = (await db.scalars(text('SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE :prefix'), {'prefix': self.actor.company_id + ':%'})).all()
            usage = list((await db.scalars(select(ModelUsage).where(ModelUsage.company_id == self.actor.company_id))).all())
            jobs = list((await db.scalars(select(Job).where(Job.company_id == self.actor.company_id).order_by(Job.created_at))).all())
        for thread in threads:
            context = RunContext(self.actor.id, self.actor.company_id, '', 0, self.sessions, self.settings)
            context.role = self.actor.role
            state = await build_graph(self.settings, self.saver, context).aget_state({'configurable': {'thread_id': thread}})
            traces.append({'thread': thread, 'messages': [{'type': m.type, 'name': m.name, 'content': redact(m.content), 'toolCalls': getattr(m, 'tool_calls', [])} for m in state.values.get('messages', []) if m.type in ('ai', 'tool')]})
        self.snapshot.update(final=await self.state(), traces=traces, usage=[{'kind': u.kind, 'model': u.model_name, 'status': u.status, 'errorCode': u.error_code, 'input': u.actual_input_tokens, 'output': u.actual_output_tokens} for u in usage], jobs=[{'id': j.id, 'kind': j.kind, 'state': j.state, 'error': j.error, 'attempt': j.attempt, 'result': j.result} for j in jobs])


async def evaluate_work_record(case, configs, evaluation):
    from eval.support.work.work_record_eval_assertions import check_case
    started = time.monotonic()
    base = {'id': case.id, 'title': case.title, 'role': case.role, 'executionMode': case.mode, 'turns': case.turns, 'suiteRevision': SUITE_REVISION,
            'models': {name: {'model': config['model']['model'], 'effort': config['choice'].get('effort'), 'streaming': config['choice']['streaming']} for name, config in configs.items()}}
    run, fixture = None, None
    try:
        with tempfile.TemporaryDirectory(prefix='noria-work-record-eval-') as directory:
            if case.id == 'A10' and 'asr' not in configs:
                raise EvaluationBlocked('来源账号没有配置真实 ASR；没有用文字代替录音')
            fixture = setup.__wrapped__(Path(directory))
            values = await anext(fixture)
            settings, sessions, users, _ = values
            try:
                # Ordinary fixtures disable external execution. This opt-in real
                # scenario explicitly restores only the sandbox connection; DB,
                # accounts, media and encryption keys remain isolated.
                if case.id == 'A08':
                    local = Settings()
                    settings = replace(settings, sandbox_url=local.sandbox_url, sandbox_token=local.sandbox_token)
                    values = (settings, *values[1:])
                if case.id == 'A08' and not (settings.sandbox_url and settings.sandbox_token):
                    raise EvaluationBlocked('真实沙盒没有配置，不能验证 XLSX 计算与成果回存')
                await evaluation.install_models(configs, settings, sessions, users[case.role].company_id)
                run = WorkRecordRun(case, values, evaluation.checked, Path(directory))
                async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
                    run.saver = saver
                    completed = False
                    try:
                        await run.prepare()
                        with run.observers():
                            for index, prompt in enumerate(case.turns):
                                await run.run_turn(prompt, index)
                        completed = True
                    finally:
                        try:
                            await run.finish()
                        except Exception as error:
                            run.snapshot['evidenceError'] = type(error).__name__
                            if completed:
                                raise
                checks = check_case(case, run.snapshot)
                issues = [label for label, passed in checks.items() if not passed]
                base.update(status='PASS' if not issues else 'FAIL', passed=not issues, issues=issues, checks=checks)
                unsupported = [failure for failure in run.snapshot['providerFailures'] if failure['imageBlocks'] and any(word in failure['message'].lower() for word in ('not support image', 'does not support image', 'unsupported image', '不支持图片', '不支持图像'))]
                if issues and unsupported:
                    base.update(status='BLOCKED', failureClass='model_capability', blockedReason='已配置模型明确拒绝图片输入；未使用文件名冒充图片读取')
            finally:
                # Resume past yield; aclose() alone skips this fixture's cleanup.
                await anext(fixture, None)
                fixture = None
    except EvaluationBlocked as error:
        base.update(status='BLOCKED', passed=False, issues=[str(error)], failureClass='environment')
    except Exception as error:
        base.update(status='FAIL', passed=False, issues=['runner: ' + type(error).__name__], failureClass='runner_or_product')
        if isinstance(error, AssertionError):
            base['issues'] = ['assertion: ' + str(error)[:400]]
        if isinstance(error, EvaluationAPIError):
            base['apiFailure'] = error.details
    finally:
        if fixture is not None:
            await anext(fixture, None)
    return redact({**base, **(run.snapshot if run else {}), 'seconds': round(time.monotonic() - started, 2)})
