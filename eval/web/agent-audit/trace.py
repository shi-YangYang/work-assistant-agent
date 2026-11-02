"""Test-process-only observations; full synthetic input is opt-in; never store private reasoning."""
from contextvars import ContextVar
import base64
import hashlib
import json
import os
from pathlib import Path
import time
from uuid import uuid4

scope = ContextVar('audit_scope', default={})
http_scope = ContextVar('audit_http_scope', default=None)
OUTPUT = None
commit_capture = ContextVar('audit_commit_capture', default=None)


def database_diagnostic(ctx):
    """Driver/control-flow evidence only; never SQL parameters or exception prose."""
    import asyncio
    import re
    import traceback
    error = ctx.original_exception
    statement = ctx.statement or ''
    operation = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else None
    if operation not in {'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'BEGIN', 'COMMIT', 'ROLLBACK', 'SAVEPOINT', 'RELEASE', 'WITH'}:
        operation = 'other' if statement else None
    # These messages are constants in psycopg, not PostgreSQL messages which
    # may embed user data. A hash correlates every other message without copying it.
    message = str(error)
    constant = message if message in {'no result available', 'COPY cannot be mixed with other operations',
                                     'you cannot mix COPY with other operations', 'the connection is closed'} else None
    if re.fullmatch(r"the last operation didn't produce records \(command status: [A-Z ]+\)", message):
        constant = message
    if re.fullmatch(r"can't change '(?:autocommit|isolation_level|read_only|deferrable)' now: connection in transaction status [A-Z]+", message):
        constant = message
    frames = traceback.extract_tb(error.__traceback__)
    request = http_scope.get()
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return {
        'errorObjectId': id(error), 'errorModule': type(error).__module__,
        'error': type(error).__name__, 'sqlstate': getattr(error, 'sqlstate', None),
        'disconnect': ctx.is_disconnect, 'isPrePing': ctx.is_pre_ping,
        'operation': operation, 'statementSha256': digest(statement),
        'constantMessage': constant, 'messageSha256': digest(message),
        'stack': [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name} for f in frames[-16:]],
        'route': getattr(request.get('route'), 'path', '<unmatched>') if request else None,
        'requestId': request.get('state', {}).get('request_id') if request else None,
        'taskCancelling': task.cancelling() if task else None,
    }


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def safe(value):
    if isinstance(value, dict):
        return {k: '[redacted]' if any(s in k.lower() for s in ('password', 'secret', 'credential', 'api_key', 'authorization', 'cookie')) else safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [safe(v) for v in value]
    return value if value is None or isinstance(value, (str, int, float, bool)) else str(value)


def public_input(value):
    """Preserve public messages/tool schemas while removing private reasoning."""
    if isinstance(value, dict):
        if value.get('type') in ('thinking', 'reasoning', 'redacted_thinking'):
            return {'type': 'private-reasoning-omitted'}
        return {k: public_input(v) for k, v in value.items()
                if k.lower() not in ('reasoning_content', 'thinking', 'reasoning_details', 'encrypted_content', 'signature')}
    if isinstance(value, list):
        return [public_input(v) for v in value]
    return value


def transport_input(body):
    """Describe actual synthetic chat inputs without saving prompts or pixels."""
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get('messages'), list):
        return None
    if os.environ.get('PAA_EVAL_FULL_INPUT') == '1':
        return safe(public_input(payload))
    messages = []
    for message in payload['messages']:
        role = message.get('role')
        content = message.get('content')
        item = {'role': role, 'contentSha256': digest(content)}
        if role in ('system', 'developer'):
            item['characters'] = len(str(content))
        else:
            parts = content if isinstance(content, list) else [{'type': 'text', 'text': content}]
            observed = []
            for part in parts:
                if not isinstance(part, dict):
                    continue
                if part.get('type') == 'text':
                    text = part.get('text') or ''
                    observed.append({'type': 'text', 'text': text[:100000],
                                     'characters': len(text), 'truncated': len(text) > 100000})
                elif part.get('type') == 'image_url':
                    source = part.get('image_url', {})
                    url = source.get('url', '') if isinstance(source, dict) else str(source)
                    image = {'type': 'image_url', 'urlSha256': digest(url)}
                    if url.startswith('data:') and ';base64,' in url:
                        header, encoded = url.split(';base64,', 1)
                        try:
                            raw = base64.b64decode(encoded, validate=True)
                            image.update(mime=header[5:], bytes=len(raw), pixelFileSha256=hashlib.sha256(raw).hexdigest())
                        except ValueError:
                            image['encoding'] = 'invalid-base64'
                    else:
                        image['source'] = 'remote-url'
                    observed.append(image)
            item['parts'] = observed
        if message.get('tool_call_id'):
            item['toolCallId'] = message['tool_call_id']
        messages.append(item)
    return {'model': payload.get('model'), 'reasoningEffort': payload.get('reasoning_effort'),
            'stream': payload.get('stream'), 'messages': messages}


def emit(kind, **values):
    capture = commit_capture.get()
    row = {'time': time.time(), 'pid': os.getpid(), **scope.get(), 'kind': kind, **safe(values)}
    if capture:
        row['captureId'] = capture['id']
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
        capture = {'id': str(uuid4()), 'commits': [], 'unsupported': []}
        capture_token = commit_capture.set(capture)
        emit('commit_observation_start', protocol=1)
        emit('worker_job_start')
        try:
            return await operation(job, *args, **kwargs)
        finally:
            emit('worker_job_end')
            emit('commit_observation_end', protocol=1, commits=capture['commits'], unsupported=capture['unsupported'])
            commit_capture.reset(capture_token)
            scope.reset(token)
    return observed


def install(path):
    global OUTPUT
    OUTPUT = str(Path(path).resolve())
    Path(OUTPUT).parent.mkdir(parents=True, exist_ok=True)
    import importlib
    from app.http.middleware import Boundaries
    original_boundaries = Boundaries.__call__

    async def observed_boundaries(self, request_scope, receive, send):
        token = http_scope.set(request_scope if request_scope['type'] == 'http' else None)
        try:
            return await original_boundaries(self, request_scope, receive, send)
        finally:
            http_scope.reset(token)

    Boundaries.__call__ = observed_boundaries
    if os.environ.get('ACCEPTANCE_SUITE') == 'spec074' or os.environ.get('PAA_EVAL_FULL_INPUT') == '1':
        import httpx
        original_send = httpx.AsyncClient.send

        async def observed_send(self, request, **kwargs):
            external = request.url.host not in ('127.0.0.1', 'localhost', '::1')
            observed_id = str(uuid4())
            if external:
                try:
                    body_hash = hashlib.sha256(request.content).hexdigest()
                except httpx.RequestNotRead:
                    body_hash = None
                emit('upstream_http_start', observationId=observed_id, method=request.method,
                     endpoint=str(request.url.copy_with(query=None)),
                     requestBodySha256=body_hash,
                     input=transport_input(request.content) if body_hash else None)
            try:
                response = await original_send(self, request, **kwargs)
                if external:
                    emit('upstream_http_headers', observationId=observed_id, status=response.status_code,
                         upstreamRequestId=next((response.headers[h] for h in ('x-request-id', 'request-id', 'x-dashscope-request-id') if h in response.headers), None))
                    if 'text/event-stream' in response.headers.get('content-type', ''):
                        original_stream = response.stream

                        class ObservedStream(httpx.AsyncByteStream):
                            async def __aiter__(stream_self):
                                pending = b''
                                size, events, text_chars = 0, 0, 0
                                finishes, usage, first_body = [], None, False
                                try:
                                    async for chunk in original_stream:
                                        size += len(chunk)
                                        pending += chunk
                                        while b'\n' in pending:
                                            line, pending = pending.split(b'\n', 1)
                                            if not line.startswith(b'data:'):
                                                continue
                                            try:
                                                value = json.loads(line[5:].strip())
                                            except (ValueError, UnicodeDecodeError):
                                                continue
                                            if not isinstance(value, dict):
                                                continue
                                            events += 1
                                            usage = value.get('usage') or usage
                                            for choice in value.get('choices') or []:
                                                if not isinstance(choice, dict):
                                                    continue
                                                finish = choice.get('finish_reason')
                                                if finish is not None and finish not in finishes:
                                                    finishes.append(finish)
                                                delta = choice.get('delta') or {}
                                                content = delta.get('content') if isinstance(delta, dict) else None
                                                if isinstance(content, str):
                                                    text_chars += len(content)
                                                    if content.strip() and not first_body:
                                                        first_body = True
                                                        emit('upstream_http_first_body', observationId=observed_id)
                                        yield chunk
                                finally:
                                    emit('upstream_http_stream_end', observationId=observed_id,
                                         bytes=size, events=events, bodyCharacters=text_chars,
                                         finishReasons=finishes, usage=usage)

                            async def aclose(stream_self):
                                await original_stream.aclose()

                        response.stream = ObservedStream()
                return response
            except BaseException as error:
                if external:
                    emit('upstream_http_error', observationId=observed_id, error=type(error).__name__)
                raise

        httpx.AsyncClient.send = observed_send
    chat_module = importlib.import_module('app.integrations.models.chat')
    original_chat = chat_module._chat

    async def provider_request(settings, config, key, messages, **kwargs):
        token = scope.set({**scope.get(), 'providerRequestId': str(uuid4())})
        emit('provider_request_start', config={k: config.get(k) for k in ('model', 'parameters', 'streaming', 'protocol')}, idType='local-observation-id')
        try:
            result = await original_chat(settings, config, key, messages, **kwargs)
            observed_response = {'usage': result.get('usage'), 'choices': [
                {'finish_reason': c.get('finish_reason'), 'message': {
                    k: c.get('message', {}).get(k) for k in ('role', 'content', 'tool_calls')}}
                for c in result.get('choices', [])]}
            emit('provider_request_end', status='succeeded', **({'response': observed_response} if os.environ.get('ACCEPTANCE_SUITE') == 'spec074' or os.environ.get('PAA_EVAL_FULL_INPUT') == '1' else {}))
            return result
        except BaseException as error:
            emit('provider_request_end', status='failed', error=type(error).__name__, code=getattr(error, 'code', None),
                 upstreamDiagnostic=getattr(error, 'upstream_diagnostic', None))
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

    @event.listens_for(Session, 'before_flush')
    def begin_flush(session, ctx, instances):
        session.connection().info['audit_orm_flush'] = True

    @event.listens_for(Session, 'after_flush')
    def flushed(session, ctx):
        rows = session.info.setdefault('audit_changes', [])
        session.info.setdefault('audit_transaction', str(uuid4()))
        for operation, objects in (('insert', session.new), ('update', session.dirty), ('delete', session.deleted)):
            for obj in objects:
                table = getattr(obj, '__tablename__', '')
                if table not in tables or operation == 'update' and not session.is_modified(obj):
                    continue
                values = {c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs if c.key in ('id', 'owner_id', 'company_id', 'revision', 'state', 'document', 'content', 'work_id', 'report_id', 'action', 'result', 'deleted', 'material_id', 'update_id', 'status')}
                rows.append({'operation': operation, 'table': table, 'values': safe(values), 'scope': scope.get()})

    @event.listens_for(Session, 'after_flush_postexec')
    def end_flush(session, ctx):
        session.connection().info.pop('audit_orm_flush', None)

    @event.listens_for(Session, 'after_commit')
    def committed(session):
        if session.in_nested_transaction():
            return
        transaction = session.info.pop('audit_transaction', None)
        committed = {}
        for row in session.info.pop('audit_changes', []):
            key = (row['table'], row['values'].get('id'))
            if key in committed and committed[key]['operation'] == 'insert':
                row = {**row, 'operation': 'insert'}
            committed[key] = row
        rows = list(committed.values())
        for row in rows:
            emit('database_commit', transactionId=transaction, **row)
        capture = commit_capture.get()
        if capture is not None and rows:
            capture['commits'].append({'transactionId': transaction, 'rows': len(rows), 'sha256': digest(rows)})

    @event.listens_for(Session, 'after_rollback')
    def rolled_back(session):
        capture = commit_capture.get()
        if capture is not None:
            capture['unsupported'].append('rollback: flushed history discarded; no completeness claim')
        session.info.pop('audit_changes', None)
        session.info.pop('audit_transaction', None)

    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, 'rollback')
    @event.listens_for(Engine, 'commit')
    def clear_flush_flag(conn):
        conn.info.pop('audit_orm_flush', None)

    @event.listens_for(Engine, 'before_cursor_execute')
    def observe_sql(conn, cursor, statement, parameters, context, executemany):
        capture = commit_capture.get()
        if capture is None:
            return
        import re
        match = re.search(r'\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:[\w\"]+\.)?[\"]?(company_\w+)', statement, re.I)
        if match and match.group(1).lower() in tables and not conn.info.get('audit_orm_flush'):
            capture['unsupported'].append({'reason': 'non-ORM mutation', 'table': match.group(1), 'statementSha256': digest(statement)})

    @event.listens_for(Engine, 'handle_error')
    def database_error(ctx):
        emit('database_error', **database_diagnostic(ctx))
