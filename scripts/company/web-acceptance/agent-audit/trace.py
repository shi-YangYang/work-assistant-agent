"""Test-process-only observations; never store system prompts or private reasoning."""
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import time
from uuid import uuid4

scope = ContextVar('audit_scope', default={})
OUTPUT = None


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def safe(value):
    if isinstance(value, dict):
        return {k: '[redacted]' if any(s in k.lower() for s in ('password', 'secret', 'credential', 'api_key', 'authorization', 'cookie')) else safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [safe(v) for v in value]
    return value if value is None or isinstance(value, (str, int, float, bool)) else str(value)


def emit(kind, **values):
    row = {'time': time.time(), 'pid': os.getpid(), **scope.get(), 'kind': kind, **safe(values)}
    data = (json.dumps(row, ensure_ascii=False, default=str) + '\n').encode()
    descriptor = os.open(OUTPUT, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, data)
    finally:
        os.close(descriptor)


def context_values(context):
    return {'jobId': context.job_id, 'companyId': context.company_id, 'ownerId': context.owner_id, 'attempt': context.attempt, 'fence': context.fence, 'stateVersions': dict(context.read_versions)}


def validation_causes(error):
    """Observe constant validation reasons, never model input or raw verdict text."""
    import ast
    from pydantic import ValidationError
    from app.agent.actions import intent
    source = ast.parse(Path(intent.__file__).read_text())
    constants = {node.args[0].value for node in ast.walk(source)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                 and node.func.id == 'ValueError' and node.args
                 and isinstance(node.args[0], ast.Constant)
                 and isinstance(node.args[0].value, str)}
    result, seen = [], set()
    cause = error.__cause__
    while cause is not None and id(cause) not in seen and len(result) < 4:
        seen.add(id(cause))
        row = {'type': type(cause).__name__}
        if isinstance(cause, ValidationError):
            row['errors'] = [{key: item[key] for key in ('type', 'loc', 'msg')}
                             for item in cause.errors(include_input=False, include_context=False, include_url=False)]
        elif type(cause) is ValueError and str(cause) in constants:
            row['message'] = str(cause)
        result.append(row)
        cause = cause.__cause__
    return result


def observe_job(operation):
    async def observed(job, *args, **kwargs):
        token = scope.set({'jobId': job.id, 'companyId': job.company_id, 'ownerId': job.owner_id, 'attempt': job.attempt, 'fence': job.fence, 'jobKind': job.kind, 'stateVersions': {}})
        emit('worker_job_start')
        try:
            return await operation(job, *args, **kwargs)
        finally:
            emit('worker_job_end')
            scope.reset(token)
    return observed


def install(path):
    global OUTPUT
    OUTPUT = str(Path(path).resolve())
    Path(OUTPUT).parent.mkdir(parents=True, exist_ok=True)
    import importlib
    chat_module = importlib.import_module('app.integrations.models.chat')
    original_chat = chat_module._chat

    async def provider_request(settings, config, key, messages, **kwargs):
        token = scope.set({**scope.get(), 'providerRequestId': str(uuid4())})
        emit('provider_request_start', config={k: config.get(k) for k in ('model', 'parameters', 'streaming', 'protocol')})
        try:
            result = await original_chat(settings, config, key, messages, **kwargs)
            emit('provider_request_end', status='succeeded')
            return result
        except BaseException as error:
            emit('provider_request_end', status='failed', error=type(error).__name__, code=getattr(error, 'code', None))
            raise
        finally:
            scope.reset(token)

    chat_module._chat = provider_request
    from app.agent.runtime.model import BoundedChatModel
    from app.agent.runtime.middleware import ToolBoundary
    from app.agent.runtime import tool_nodes
    original_model = BoundedChatModel._single
    original_boundary = ToolBoundary.awrap_tool_call
    original_node = tool_nodes.tool_node

    async def model(self, messages, *args, **kwargs):
        token = scope.set({**context_values(self._run_context), 'modelAttemptId': str(uuid4())})
        payload = self._get_request_payload(messages, **kwargs)
        emit('model_attempt_start', adapterParameters={k: payload[k] for k in ('model', 'reasoning_effort', 'stream', 'max_tokens', 'max_completion_tokens') if k in payload}, offered=[t.get('function', {}).get('name') for t in payload.get('tools', [])])
        try:
            result = await original_model(self, messages, *args, **kwargs)
            for generation in result.generations:
                emit('model_attempt_result', toolCalls=generation.message.tool_calls, contentCharacters=len(str(generation.message.content)), usage=generation.message.usage_metadata)
            return result
        except BaseException as error:
            details = {'validationCauses': validation_causes(error)} if os.environ.get('AGENT_AUDIT_PLAN_INPUT') == 'synthetic' else {}
            emit('model_attempt_error', error=type(error).__name__, **details)
            raise
        finally:
            scope.reset(token)

    async def boundary(self, request, handler):
        token = scope.set({**context_values(request.runtime.context), 'toolCallId': request.tool_call['id'], 'tool': request.tool_call['name']})
        emit('tool_dispatch', arguments=request.tool_call.get('args', {}))
        async def observed_handler(req):
            emit('tool_attempt_start')
            try:
                value = await handler(req)
                content = getattr(value, 'content', None)
                emit('tool_attempt_result', status=getattr(value, 'status', None), content=content)
                return value
            except BaseException as error:
                emit('tool_attempt_error', error=type(error).__name__)
                raise
        try:
            value = await original_boundary(self, request, observed_handler)
            emit('tool_dispatch_result', status=getattr(value, 'status', None), content=getattr(value, 'content', None))
            return value
        finally:
            scope.reset(token)

    async def node(context, request, operation):
        emit('tool_logical_node', arguments=request.tool_call.get('args', {}))
        return await original_node(context, request, operation)

    BoundedChatModel._single = model
    ToolBoundary.awrap_tool_call = boundary
    tool_nodes.tool_node = node
    if os.environ.get('AGENT_AUDIT_PLAN_INPUT') == 'synthetic':
        plan_module = importlib.import_module('app.agent.actions.work_change_plan')
        original_input = plan_module.source_input
        original_plan = plan_module.work_change_plan

        def plan_input(request, proposal, message_id):
            payload = original_input(request, proposal, message_id)
            emit('work_change_plan_input', payload=payload, payloadSha256=digest(payload))
            return payload

        async def planned(context, request, proposal, message_id, judge):
            token = scope.set({**scope.get(), **context_values(context)})
            try:
                result = await original_plan(context, request, proposal, message_id, judge)
                emit('work_change_plan_result', messageId=message_id,
                     targetId=proposal.get('targetId'), plan=result.model_dump(),
                     sourceRevision=context.source_revision,
                     documentVersions=context.document_versions)
                return result
            finally:
                scope.reset(token)

        plan_module.source_input = plan_input
        plan_module.work_change_plan = planned
    from sqlalchemy import event, inspect
    from sqlalchemy.orm import Session
    tables = {'company_work_item', 'company_work_revision', 'company_report', 'company_report_revision', 'company_assistant_memory', 'company_deliverable', 'company_deliverable_revision', 'company_business_action', 'company_sandbox_execution', 'company_work_material', 'company_work_update', 'company_work_update_revision'}

    @event.listens_for(Session, 'after_flush')
    def flushed(session, ctx):
        rows = session.info.setdefault('audit_changes', [])
        session.info.setdefault('audit_transaction', str(uuid4()))
        for operation, objects in (('insert', session.new), ('update', session.dirty), ('delete', session.deleted)):
            for obj in objects:
                table = getattr(obj, '__tablename__', '')
                if table not in tables or operation == 'update' and not session.is_modified(obj):
                    continue
                values = {c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs if c.key in ('id', 'owner_id', 'company_id', 'revision', 'state', 'document', 'content', 'work_id', 'report_id', 'action', 'result')}
                rows.append({'operation': operation, 'table': table, 'values': safe(values), 'scope': scope.get()})

    @event.listens_for(Session, 'after_commit')
    def committed(session):
        transaction = session.info.pop('audit_transaction', None)
        committed = {}
        for row in session.info.pop('audit_changes', []):
            key = (row['table'], row['values'].get('id'))
            if key in committed and committed[key]['operation'] == 'insert':
                row = {**row, 'operation': 'insert'}
            committed[key] = row
        for row in committed.values():
            emit('database_commit', transactionId=transaction, **row)

    @event.listens_for(Session, 'after_rollback')
    def rolled_back(session):
        session.info.pop('audit_changes', None)
        session.info.pop('audit_transaction', None)

    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, 'handle_error')
    def database_error(ctx):
        emit('database_error', error=type(ctx.original_exception).__name__, sqlstate=getattr(ctx.original_exception, 'sqlstate', None), disconnect=ctx.is_disconnect)
