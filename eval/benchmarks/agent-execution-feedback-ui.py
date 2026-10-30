"""Owned real-model UI fixture and passive observations for the Spec075 runner.

Accounts are independent per case/effort. The worker stays idle until a browser
or HTTP client submits a request. It executes one job at a time, without model
stubs or automatic answers. The original case manifest is never rewritten.
"""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
from uuid import uuid4


class AdmissionObservation:
    """Observe public admission receipts without changing request/response bytes."""

    def __init__(self, app, pending, output):
        self.app, self.pending, self.output = app, pending, output

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        tracked = scope.get('method') == 'POST' and (
            path == '/api/v1/messages' or
            path.startswith('/api/v1/interactions/') and path.endswith('/answer'))
        if not tracked:
            return await self.app(scope, receive, send)
        began, started = time.perf_counter(), time.time()
        request, response, status = bytearray(), bytearray(), None

        async def observed_receive():
            message = await receive()
            request.extend(message.get('body', b''))
            return message

        async def observed_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
            if message['type'] == 'http.response.body':
                response.extend(message.get('body', b''))
                if not message.get('more_body') and status in (200, 202):
                    try:
                        body = json.loads(response)
                        receipt = body.get('continuation') or body
                        job_id = receipt.get('jobId')
                        if job_id:
                            event = {'path': path, 'started': started, '_clock': began,
                                     'send_ms': (time.perf_counter() - began) * 1000,
                                     'request': json.loads(request), 'receipt': receipt}
                            self.pending.setdefault(job_id, event)
                            self.output({key: value for key, value in event.items() if key != '_clock'})
                    except (TypeError, ValueError, AttributeError):
                        # Observation must not change admission or execution.
                        self.output({'path': path, 'started': started, 'observationError': 'invalid_receipt'})
            await send(message)

        await self.app(scope, observed_receive, observed_send)


async def serve(args, runner, fixture_module, config, cases, evidence, password,
                schema, digest, timings, activate):
    import httpx
    import uvicorn
    from fastapi import Response
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from sqlalchemy import select
    from app.modules.auth.sessions import issue_session
    from app.modules.members.models import Member
    from app.modules.messages.models import Message
    from app.modules.model_services.models import ModelUsage
    from app.tasks.models import Job
    from app.tasks.processing.handlers import process_job
    from app.tasks.runtime.queue import claim

    with tempfile.TemporaryDirectory(prefix='noria-spec075-ui-') as temporary:
        fixture = fixture_module.setup.__wrapped__(Path(temporary), password)
        settings, sessions, users, fixture_clients = await anext(fixture)
        clients, accounts, pending, runs = {}, {}, {}, {}
        stop = asyncio.Event()
        try:
            await runner.install(config, settings, sessions, users['employee'].company_id)
            ui_settings = replace(settings, web_origin='http://127.0.0.1:5175')
            app = fixture_module.create_app(ui_settings)
            app.add_middleware(AdmissionObservation, pending=pending,
                               output=lambda event: runner.append(args.output / 'ui-admissions.jsonl', event))
            for identifier in args.ids.split(','):
                for effort in args.efforts.split(','):
                    key = identifier + '-' + effort
                    async with sessions.begin() as db:
                        actor = Member(company_id=users['employee'].company_id,
                                       username='spec075_' + uuid4().hex[:14], name=key,
                                       role='employee', password_hash=password, execution_mode='full',
                                       full_access_confirmed=True)
                        db.add(actor)
                        await db.flush()
                        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                                   base_url='http://test', headers={'Origin': ui_settings.web_origin})
                        response = Response()
                        client.headers['X-CSRF-Token'] = issue_session(db, actor, response, settings)
                        client.cookies.extract_cookies(httpx.Response(200, headers=response.headers,
                                                       request=httpx.Request('POST', 'http://test/api/v1/auth/login')))
                    clients[key] = client
                    seeded = await runner.seed(cases[identifier], settings, sessions, actor, client, fixture_clients, evidence)
                    preference = runner.checked(await client.get('/api/v1/assistant/reasoning-settings'))
                    runner.checked(await client.patch('/api/v1/assistant/reasoning-settings', json={
                        'effort': effort, 'preferenceRevision': preference['preferenceRevision'],
                        'configVersion': preference['configVersion']}))
                    accounts[key] = {'actor': actor, 'case': identifier, 'effort': effort,
                                     'seed': seeded, 'initial': await runner.snapshot(sessions, actor)}
            async def drain_owned():
                async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
                    while not stop.is_set():
                        for key, entry in accounts.items():
                            actor, client = entry['actor'], clients[key]
                            job = await claim(sessions, actor.id)
                            if not job:
                                continue
                            if job.kind != 'message':
                                # Saved files enqueue document extraction jobs. They
                                # are real background work, not additional chat turns.
                                began = time.perf_counter()
                                await process_job(job, sessions, ui_settings, saver)
                                async with sessions() as db:
                                    current = await db.get(Job, job.id)
                                    runner.append(args.output / 'ui-background-jobs.jsonl', {
                                        'account': key, 'jobId': job.id, 'kind': job.kind,
                                        'state': current.state, 'phase': current.phase,
                                        'elapsedMs': (time.perf_counter() - began) * 1000,
                                        'error': current.error})
                                continue
                            runs[key] = runs.get(key, 0) + 1
                            admission = pending.pop(job.id, {})
                            clock = admission.get('_clock', time.perf_counter())
                            row = {'case': entry['case'], 'effort': entry['effort'], 'sample': 0,
                                   'turn': runs[key], 'label': args.label, 'channel': 'live-http-ui',
                                   'account': key, 'jobId': job.id, 'messageId': job.target_id,
                                   'seed': entry['seed'], 'requests': [], 'stream': [], 'first_answer_ms': None,
                                   'publicObservationVersion': 2, 'started': admission.get('started', time.time()),
                                   'timingBoundary': 'HTTP admission start' if admission else 'worker claim; admission observation missing',
                                   'send_ms': admission.get('send_ms'),
                                   'queue_ms': (time.perf_counter() - clock) * 1000 - admission.get('send_ms', 0),
                                   'submittedAnswer': admission.get('request') if admission.get('path', '').endswith('/answer') else None,
                                   '_clock': clock}
                            try:
                                assert runner.source_digest(args.app_root.resolve()) == digest, 'Source changed during UI run'
                                async with sessions() as db:
                                    message = await db.get(Message, job.target_id)
                                    row['prompt'] = message.text
                                row['initial'] = await runner.snapshot(sessions, actor)
                                activate(row)
                                await process_job(job, sessions, ui_settings, saver)
                                dto = runner.checked(await client.get('/api/v1/messages/' + job.target_id))
                                row['total_ms'] = (time.perf_counter() - clock) * 1000
                                row['answer'], row['message'] = dto['reply'], dto
                                row['interactions'] = runner.checked(await client.get(
                                    '/api/v1/conversations/' + entry['seed']['conversationId'] + '/interactions'))['items']
                                row['final'] = await runner.snapshot(sessions, actor)
                                async with sessions() as db:
                                    current = await db.get(Job, job.id)
                                    row['jobResult'] = current.result
                                    usages = (await db.scalars(select(ModelUsage).where(
                                        ModelUsage.job_id == job.id).order_by(ModelUsage.created_at))).all()
                                    row['usage'] = [{'kind': item.kind, 'state': item.status, 'ms': item.elapsed_ms,
                                                     'input': item.actual_input_tokens, 'output': item.actual_output_tokens,
                                                     'error': item.error_code} for item in usages]
                                row['events'] = [event for event in timings.events if event.get('job') == job.id]
                                row['refreshSameReply'] = runner.checked(await client.get(
                                    '/api/v1/messages/' + job.target_id))['reply'] == dto['reply']
                                if row['first_answer_ms'] is None and dto['reply']:
                                    row['first_answer_ms'] = row['total_ms']
                                    row['first_answer_source'] = 'final API snapshot only'
                                else:
                                    row['first_answer_source'] = 'public Redis event'
                                runner.complete_public_observation(row)
                            except Exception as error:
                                row['error'] = {'type': type(error).__name__, 'detail': str(error)[:600]}
                                row['total_ms'] = (time.perf_counter() - clock) * 1000
                            finally:
                                activate(None)
                                row.pop('_clock', None)
                                runner.append(args.output / 'ui-results.jsonl', row)
                                print(json.dumps({'account': key, 'turn': runs[key], 'jobId': job.id,
                                                  'state': row.get('message', {}).get('job', {}).get('state'),
                                                  'calls': len(row['requests']), 'error': row.get('error')}, ensure_ascii=False), flush=True)
                        await asyncio.sleep(.2)

            info = {'port': args.port, 'password': 'controlled-test-password', 'schema': schema,
                    'accounts': {key: {'username': entry['actor'].username, 'case': entry['case'],
                                      'effort': entry['effort'], 'prompt': cases[entry['case']]['prompt'],
                                      'seed': entry['seed'], 'initial': entry['initial']}
                                 for key, entry in accounts.items()},
                    'disclosure': {'executionMode': 'full', 'productionModes': {'E00-A': 'auto', 'E00-B': 'full'},
                                   'answers': 'Only an explicit test answer submitted by the operator continues a question; no automatic answers.',
                                   'questionTiming': 'Persisted interaction after commit; excludes browser paint.',
                                   'cases': 'Original fixed manifest retained unchanged; assess meaning/destination ambiguity before any write.',
                                   'sourceDigest': digest}}
            runner.write(args.output / 'ui-fixture.json', info)
            print(json.dumps({'ready': True, 'fixture': str(args.output / 'ui-fixture.json')}, ensure_ascii=False), flush=True)
            worker = asyncio.create_task(drain_owned())
            try:
                await uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port, log_level='warning')).serve()
            finally:
                stop.set()
                await worker
                runner.write(args.output / 'ui-final-snapshot.json', {
                    key: await runner.snapshot(sessions, entry['actor']) for key, entry in accounts.items()})
        finally:
            for client in clients.values():
                await client.aclose()
            await fixture.aclose()
