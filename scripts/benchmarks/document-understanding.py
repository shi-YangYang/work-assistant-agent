"""Opt-in Spec072 paired API/worker accuracy and latency benchmark.

Only configuration is read from the local development database. All business
writes use owned spec072 schemas in the dedicated localhost:15472 test database;
files and Redis events are synthetic. Saved provider credentials stay in memory
and are re-encrypted with each fixture's temporary key. Never default CI.

The coordinator keeps both source revisions alive, alternates A/B and B/A, and
records every attempt. Measurements include real in-process ASGI admission,
worker claim/process_job, parser/render subprocesses, graph/tools and provider.
First answer is the first nonempty reply event accepted by real Redis, equivalent
to the stream event available to clients, not browser paint or network latency.
"""
import argparse
import asyncio
import base64
from contextvars import ContextVar
import copy
import hashlib
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import re
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
DATABASE = 'postgresql://spec072:spec072-local-only@127.0.0.1:15472/paa_company_test'
REDIS = 'redis://127.0.0.1:16472/0'


def options():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, default=ROOT / 'artifacts/spec072/performance/fixtures')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--after', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--label', default='before')
    parser.add_argument('--source-user', default='admin')
    parser.add_argument('--mode', choices=('live', 'controlled'), default='live')
    parser.add_argument('--cases', default='none,text_code,office_pdf,table,repeat')
    parser.add_argument('--efforts', default='low,high')
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--start-index', type=int, default=0)
    parser.add_argument('--make-fixtures', action='store_true')
    parser.add_argument('--worker', action='store_true')
    return parser.parse_args()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def append(path, value):
    with path.open('a') as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + '\n')


def source_digest(root):
    files = sorted(path for path in (root / 'apps/server/app').rglob('*') if path.is_file() and path.suffix in ('.py', '.md', '.json'))
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def grade(answer, facts):
    normalized = answer.lower().replace('，', ',')
    def present(value):
        token = value.lower()
        if len(token) == 1 and token.isascii() and token.isalpha():
            return re.search(r'(?<![a-z])' + re.escape(token) + r'(?![a-z])', normalized) is not None
        return token in normalized
    results = {key: any(present(value) for value in variants) for key, variants in facts.items()}
    return {'facts': results, 'correct': sum(results.values()), 'total': len(results), 'all_correct': all(results.values()),
            'method': 'fixed fact strings; visual relationships/full coverage require transcript review'}


def summarize(rows):
    groups = {}
    for row in rows:
        if row.get('warmup'):
            continue
        key = '/'.join((row['case'], row['effort'], row['label']))
        groups.setdefault(key, []).append(row)
    result = {}
    for key, items in groups.items():
        metrics = {}
        for name in ('send_ms', 'queue_ms', 'prepare_ms', 'first_model_ms', 'first_answer_ms', 'total_ms', 'system_ms', 'between_models_ms'):
            values = sorted(item[name] for item in items if item.get(name) is not None)
            if values:
                metrics[name] = {'median': round(statistics.median(values), 3), 'min': round(min(values), 3), 'max': round(max(values), 3)}
                if len(values) >= 30:
                    metrics[name]['p95'] = round(values[math.ceil(.95 * len(values)) - 1], 3)
        result[key] = {'n': len(items), 'completed': sum(item.get('completed', False) for item in items),
                       'correct_facts': sum(item.get('accuracy', {}).get('correct', 0) for item in items),
                       'total_facts': sum(item.get('accuracy', {}).get('total', 0) for item in items),
                       'model_calls': [item.get('model_calls') for item in items], 'metrics': metrics}
    return result


def safe_inputs(messages, facts):
    texts, images = [], []
    for message in messages:
        content = message.get('content') if isinstance(message, dict) else message.content
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get('type') == 'text':
                    texts.append(block.get('text', ''))
                if block.get('type') == 'image_url':
                    url = block.get('image_url', {})
                    url = url.get('url', '') if isinstance(url, dict) else url
                    if isinstance(url, str) and url.startswith('data:'):
                        payload = base64.b64decode(url.split(',', 1)[1])
                        images.append({'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)})
                    else:
                        images.append({'reference': 'non-inline authorized image'})
    text = '\n'.join(texts)
    return {'text_chars': len(text), 'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'text_fact_presence': grade(text, facts)['facts'], 'images': images,
            'citation_tokens': sorted(set(re.findall(r'\[\[(?:file|page|document)[^\]]+\]\]', text)))}


class Timings(logging.Handler):
    def __init__(self):
        super().__init__()
        self.jobs = {}

    def emit(self, record):
        value = record.getMessage()
        if value.startswith('latency '):
            data = json.loads(value[len('latency '):])
            self.jobs.setdefault(data['job'], []).append(data)


async def worker(args):
    from dotenv import dotenv_values, load_dotenv
    actual_env = dotenv_values(ROOT / 'apps/server/.env.web')
    load_dotenv(ROOT / 'apps/server/.env.web')
    source = args.source.resolve()
    sys.path[:0] = [str(source / 'apps/server'), str(source / 'tests/server'), str(source / 'packages/voiceprint-engine/src')]
    from dataclasses import replace
    from sqlalchemy import select, text
    from sqlalchemy.engine import make_url
    from app.core.config import Settings
    from app.db.session import database
    from app.modules.members.models import Member
    from app.modules.model_services.models import ModelService, ModelServiceRevision, ModelRouting, ModelUsage
    from app.modules.model_services.bindings import bind_job
    from app.security.secrets import decrypt, encrypt
    from types import SimpleNamespace
    source_settings = replace(Settings(), database_url=actual_env.get('DATABASE_URL', Settings().database_url).replace('postgresql://', 'postgresql+psycopg://', 1), model_key_file=(ROOT / actual_env.get('PAA_MODEL_KEY_FILE', 'data/company/model-master.key')).resolve())
    assert make_url(source_settings.database_url).host in ('127.0.0.1', 'localhost'), 'Only local saved configuration is authorized'
    engine, sessions = database(source_settings)
    try:
        async with sessions() as db:
            users = (await db.scalars(select(Member).where(Member.username == args.source_user, Member.active.is_(True)))).all()
            if len(users) != 1:
                raise RuntimeError('Source username must identify one active local user')
            dummy = SimpleNamespace(kind='message', result={}, model_binding=None, config_attempt=0, company_id=users[0].company_id, owner_id=users[0].id)
            binding = await bind_job(db, dummy, source_settings)
            chosen = binding.get('assistant')
            if not chosen or not chosen.get('revisionId'):
                raise RuntimeError('Saved assistant model is not configured')
            revision = await db.get(ModelServiceRevision, chosen['revisionId'])
            model_definition = copy.deepcopy(next(item for item in revision.models if item['id'] == chosen['modelId']))
            config = {'model': model_definition, 'base': revision.base_url, 'choice': chosen,
                      'key': decrypt(source_settings.model_key_file, revision.credential, users[0].company_id, chosen['serviceId'], revision.revision)}
    finally:
        await engine.dispose()
    requested_efforts = args.efforts.split(',')
    if not set(requested_efforts) <= {'low', 'high'}:
        raise ValueError('Only low/high are authorized')
    if not set(requested_efforts) <= set(model_definition.get('reasoning', {}).get('efforts', [])):
        raise RuntimeError('Saved model does not expose requested low/high efforts')
    schema = 'spec072_perf_' + args.label + '_' + uuid4().hex[:8]
    import psycopg
    with psycopg.connect(DATABASE, autocommit=True) as connection:
        connection.execute('CREATE SCHEMA ' + schema)
    test_url = DATABASE + '?options=-csearch_path%3D' + schema
    migration_env = {**os.environ, 'DATABASE_URL': test_url, 'PYTHONPATH': os.pathsep.join((str(source / 'apps/server'), str(source / 'packages/voiceprint-engine/src')))}
    migration = await asyncio.create_subprocess_exec(sys.executable, '-m', 'app.cli', 'migrate', cwd=source, env=migration_env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await migration.communicate()
    if migration.returncode:
        raise RuntimeError('Owned schema migration failed: ' + err.decode()[-1000:])
    os.environ['DATABASE_TEST_URL'] = test_url
    os.environ['PAA_REPLY_STREAM_REDIS_URL'] = REDIS
    os.environ['PAA_REPLY_STREAM_NAMESPACE'] = schema
    module_spec = importlib.util.spec_from_file_location('spec072_fixture', source / 'tests/server/conftest.py')
    fixtures_module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(fixtures_module)
    from _support.http.management import conversation, message
    from _support.materials.documents import upload
    from app.tasks.processing.handlers import process_job
    from app.tasks.runtime.queue import claim
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from pwdlib import PasswordHash
    from app.tasks.streaming.redis_store import RedisReplyStore
    from app.tasks.processing import documents
    from app.integrations.models import chat as chat_module
    from app.tasks.models import Job
    assert Path(documents.__file__).resolve().is_relative_to(source), 'Wrong source revision imported'
    args.output.mkdir(parents=True, exist_ok=True)
    result_path = args.output / 'results.jsonl'
    if result_path.exists():
        raise RuntimeError('Refusing to overwrite or silently retry existing results')
    manifest = json.loads((args.fixtures / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        if hashlib.sha256((args.fixtures / name).read_bytes()).hexdigest() != expected['sha256']:
            raise RuntimeError('Frozen fixture changed: ' + name)
    source_sha = source_digest(source)
    write(args.output / 'environment.json', {'source': str(source), 'source_digest': source_sha,
        'baseline_commit': '3916434b2059b7366ba5f81d01c1e55eaa5afc23' if args.label == 'before' else None,
        'python': sys.version, 'mode': args.mode, 'schema': schema,
        'model': {'model': model_definition['model'], 'service': chosen['name'], 'revision': chosen['revision'], 'streaming': chosen['streaming'], 'efforts': requested_efforts, 'parameters': model_definition.get('parameters', {}), 'reasoning': model_definition.get('reasoning', {})},
        'fixtures': manifest['files'], 'fixture_revision': manifest.get('revision'), 'manifest_sha256': hashlib.sha256((args.fixtures / 'manifest.json').read_bytes()).hexdigest(), 'timing_scope': 'ASGI send to persisted result; actual worker claim + Redis reply event, no browser paint/HTTP network/periodic worker polling; upload separate; no warmup provider requests'})
    timings = Timings()
    logger = logging.getLogger('paa.latency')
    logger.handlers[:] = [timings]
    logger.propagate = False
    active = ContextVar('spec072_probe', default=None)
    originals = []
    targets = [('app.integrations.parsing.process', 'parse_process'),
               ('app.integrations.parsing.office_conversion', 'parse_office')]
    if (source / 'apps/server/app/integrations/parsing/document_rendering.py').exists():
        targets.append(('app.integrations.parsing.document_rendering', 'render_pages'))
    for module_name, name in targets:
        target = importlib.import_module(module_name)
        original = getattr(target, name)
        async def measured(*values, _original=original, _name=name, **kwargs):
            row = active.get()
            at = time.perf_counter()
            span = {'kind': _name, 'start_ms': (at - row['_clock']) * 1000} if row is not None else None
            if span is not None:
                if _name == 'parse_office':
                    span['mode'] = kwargs.get('mode', 'parse')
                if _name == 'render_pages':
                    span['pages'] = values[2] if len(values) > 2 else kwargs.get('pages')
                    span['resolution'] = kwargs.get('resolution', 'normal')
                row['operations'].append(span)
            try:
                result = await _original(*values, **kwargs)
                if span is not None:
                    if _name == 'render_pages':
                        span['references'] = result
                    elif isinstance(result, dict):
                        span['status'] = result.get('status')
                return result
            finally:
                if span is not None:
                    span['elapsed_ms'] = (time.perf_counter() - at) * 1000
        # Replace already imported aliases as well as the owner; no processing
        # result is altered. Subsequent imports receive the same observer.
        for loaded_name, loaded in list(sys.modules.items()):
            if loaded_name.startswith('app.') and loaded:
                for attribute, value in list(vars(loaded).items()):
                    if value is original:
                        originals.append((loaded, attribute, original))
                        setattr(loaded, attribute, measured)
    original_chat = chat_module.chat
    async def observed_chat(settings, wire, key, messages, **kwargs):
        row = active.get()
        at = time.perf_counter()
        observation = None
        if row is not None:
            observation = {'start_ms': (at - row['_clock']) * 1000, 'model': wire['model'], 'parameters': wire.get('parameters', {}), **safe_inputs(messages, row['_facts'])}
            row['requests'].append(observation)
        try:
            response = await original_chat(settings, wire, key, messages, **kwargs)
            if observation is not None:
                observation['usage'] = response.get('usage', {})
                observation['tools'] = [call.get('function', {}).get('name') for choice in response.get('choices', []) for call in choice.get('message', {}).get('tool_calls', [])]
                observation['tool_args'] = [call.get('function', {}) for choice in response.get('choices', []) for call in choice.get('message', {}).get('tool_calls', []) if call.get('function', {}).get('name') != 'finish_task']
            return response
        except BaseException as error:
            if observation is not None:
                observation['error'] = {'type': type(error).__name__, 'code': getattr(error, 'code', None), 'status': getattr(error, 'status', None)}
            raise
        finally:
            if observation is not None:
                observation['elapsed_ms'] = (time.perf_counter() - at) * 1000
    chat_module.chat = observed_chat
    original_publish = RedisReplyStore.publish
    async def observed_publish(store, identity, snapshot, event):
        accepted = await original_publish(store, identity, snapshot, event)
        row = active.get()
        if accepted and row is not None and snapshot.get('text', '').strip():
            at = (time.perf_counter() - row['_clock']) * 1000
            row['stream_events'].append({'at_ms': at, 'generation': snapshot['generation'], 'seq': snapshot['seq'], 'chars': len(snapshot['text']), 'state': snapshot['state']})
            if row.get('first_answer_ms') is None:
                row['first_answer_ms'] = at
        return accepted
    RedisReplyStore.publish = observed_publish

    from _support.agent.fakes import ReviewedFixtureModel, completion
    from langchain_core.messages import ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from pydantic import Field
    class FixedModel(ReviewedFixtureModel):
        has_documents: bool = False
        calls: list = Field(default_factory=list, exclude=True)
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            row = active.get()
            at = time.perf_counter()
            observation = {'start_ms': (at - row['_clock']) * 1000, **safe_inputs(messages, row['_facts']), 'tools': []}
            self.calls.append(observation)
            row['requests'].append(observation)
            last = messages[-1]
            def call(name, values):
                from langchain_core.messages import AIMessage
                observation['tools'] = [name]
                return AIMessage(content='', tool_calls=[{'id': 'fixed-' + name + '-' + str(len(self.calls)), 'name': name, 'args': values}])
            raw = '\n'.join(m.content if isinstance(m.content, str) else json.dumps(m.content, ensure_ascii=False) for m in messages)
            if not self.has_documents:
                answer = completion('43')
            elif all(observation['text_fact_presence'].values()):
                citations = re.findall(r'\[\[file:[^\]]+\]\]', raw)
                answer = completion('批次 L8N4V6；批准金额 7319.25；交付日期 2026-11-23；付款前必须验收。' + (citations[-1] if citations else ''))
            elif isinstance(last, ToolMessage) and last.name == 'find_documents':
                result = json.loads(last.content)
                answer = call('read_document', {'attachment_id': result['items'][0]['id'], 'start': 0})
            else:
                answer = call('find_documents', {'query': ''})
            observation['elapsed_ms'] = (time.perf_counter() - at) * 1000
            return ChatResult(generations=[ChatGeneration(message=answer)])

    with tempfile.TemporaryDirectory(prefix='spec072-benchmark-') as temporary:
        fixture = fixtures_module.setup.__wrapped__(Path(temporary), PasswordHash.recommended().hash('controlled-test-password'))
        settings, sessions, users, clients = await anext(fixture)
        try:
            service_id = str(uuid4())
            async with sessions.begin() as db:
                service = ModelService(id=service_id, company_id=users['employee'].company_id, name='Spec072 isolated evaluation', base_url=config['base'], models=[model_definition])
                db.add(service)
                await db.flush()
                db.add(ModelServiceRevision(company_id=service.company_id, service_id=service.id, revision=1, name=service.name, base_url=service.base_url, models=service.models, credential=encrypt(settings.model_key_file, config['key'], service.company_id, service.id, 1)))
                db.add(ModelRouting(company_id=service.company_id, choices={'assistant': {'serviceId': service.id, 'modelId': model_definition['id']}, 'asr': None, 'image': None}))
            del config['key']
            client = clients['employee']
            async def one(command, *, conv=None, attachment_ids=None, prompt=None, phase='main'):
                case = manifest['cases'][command['case']]
                effort = command['effort']
                state = (await client.get('/api/v1/assistant/reasoning-settings')).json()
                changed = await client.patch('/api/v1/assistant/reasoning-settings', json={'effort': effort, 'preferenceRevision': state['preferenceRevision'], 'configVersion': state['configVersion']})
                if changed.status_code != 200:
                    raise RuntimeError('Unable to set isolated reasoning preference: ' + changed.text)
                view = changed.json()
                conv = conv or await conversation(client, 'Synthetic document evaluation')
                row = {**command, 'label': args.label, 'mode': args.mode, 'phase': phase, 'requests': [], 'operations': [], 'stream_events': [], 'first_answer_ms': None, '_facts': case['facts'], '_clock': time.perf_counter()}
                token = active.set(row)
                uploads = []
                at = time.perf_counter()
                if attachment_ids is None:
                    for name in case['files']:
                        uploads.append(await upload(client, name, (args.fixtures / name).read_bytes()))
                    attachment_ids = [item['id'] for item in uploads]
                row['upload_ms'] = (time.perf_counter() - at) * 1000
                if row['operations'] or row['requests']:
                    raise AssertionError('Uploading triggered extraction or model processing')
                row['_clock'] = time.perf_counter()
                try:
                    receipt = await message(client, conv, prompt or case['prompt'], attachment_ids, reasoning={'effort': effort, 'preferenceRevision': view['preferenceRevision'], 'configVersion': view['configVersion']})
                    row['send_ms'] = (time.perf_counter() - row['_clock']) * 1000
                    job = await claim(sessions, owner_id=users['employee'].id)
                    if job is None or job.id != receipt['jobId']:
                        raise RuntimeError('Owned worker did not claim accepted message')
                    row['queue_ms'] = (time.perf_counter() - row['_clock']) * 1000 - row['send_ms']
                    model = FixedModel(model='controlled-spec072', api_key='not-a-secret-no-network', base_url='http://127.0.0.1:1', max_retries=0, has_documents=bool(case['files'])) if args.mode == 'controlled' else None
                    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
                        await process_job(job, sessions, settings, saver, model=model)
                    data = (await client.get('/api/v1/messages/' + receipt['messageId'])).json()
                    row['total_ms'] = (time.perf_counter() - row['_clock']) * 1000
                    row['job_id'], row['message_id'] = job.id, receipt['messageId']
                    row['job'] = data['job']
                    row['answer'] = data.get('reply', '')
                    row['citations'] = data.get('citations', [])
                    row['attachments'] = [{'id': item['id'], 'name': item['name'], 'extraction': item.get('extraction')} for item in data.get('attachments', [])]
                    row['completed'] = data['job'].get('taskOutcome', {}).get('state') == 'completed' and not data['job'].get('error')
                    row['accuracy'] = grade(row['answer'], case['facts'])
                    async with sessions() as db:
                        usages = (await db.scalars(select(ModelUsage).where(ModelUsage.job_id == job.id).order_by(ModelUsage.created_at))).all()
                        row['usage'] = [{'kind': item.kind, 'state': item.status, 'elapsed_ms': item.elapsed_ms, 'input_tokens': item.actual_input_tokens, 'output_tokens': item.actual_output_tokens, 'error_code': item.error_code} for item in usages]
                        current = await db.get(Job, job.id)
                        row['processing_result'] = {key: value for key, value in current.result.items() if key in ('documentReads', 'documentReadAliases', 'documentPages', 'documentCoverage', 'documentInputCoverage', 'documentRenderedPages', 'documentPageReads', 'documentPageRequests', 'documentPagesProvided')}
                    row['events'] = timings.jobs.pop(job.id, [])
                    row['prepare_ms'] = next((item['at_ms'] for item in row['events'] if item['event'] == 'prepare.end'), None)
                    row['model_calls'] = len(row['requests'])
                    row['first_model_ms'] = row['requests'][0]['start_ms'] if row['requests'] else None
                    row['system_ms'] = row['total_ms'] - sum(request['elapsed_ms'] for request in row['requests'])
                    row['between_models_ms'] = sum(max(0, latter['start_ms'] - former['start_ms'] - former['elapsed_ms']) for former, latter in zip(row['requests'], row['requests'][1:]))
                    row['peak_self_rss_native'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                    row['peak_children_rss_native'] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
                    refreshed = (await client.get('/api/v1/messages/' + receipt['messageId'])).json()
                    row['refresh_persisted'] = refreshed.get('reply') == row['answer'] and refreshed.get('citations') == row['citations']
                    if row['first_answer_ms'] is None and row['answer']:
                        row['first_answer_ms'] = row['total_ms']
                        row['first_answer_source'] = 'final API snapshot; no incremental event'
                    else:
                        row['first_answer_source'] = 'nonempty event accepted by real Redis'
                except Exception as error:
                    row['error'] = {'type': type(error).__name__, 'detail': str(error)[:500]}
                    row['completed'] = False
                    row['total_ms'] = (time.perf_counter() - row['_clock']) * 1000
                    row['accuracy'] = grade('', case['facts'])
                finally:
                    active.reset(token)
                    row.pop('_clock')
                    row.pop('_facts')
                    append(result_path, row)
                return row, conv
            print(json.dumps({'ready': True, 'label': args.label, 'source_digest': source_sha}), flush=True)
            while True:
                line = await asyncio.to_thread(sys.stdin.readline)
                if not line:
                    break
                command = json.loads(line)
                if command.get('stop'):
                    break
                if source_digest(source) != source_sha:
                    raise RuntimeError('Source changed while benchmark worker was alive; stop and record a new run')
                case = manifest['cases'][command['case']]
                row, conv = await one(command, phase='prime' if case.get('followup') else 'main')
                if case.get('followup'):
                    row, _ = await one(command, conv=conv, attachment_ids=[], prompt=case['followup'], phase='followup')
                print(json.dumps({'result': row}, ensure_ascii=False), flush=True)
        finally:
            await fixture.aclose()
            chat_module.chat = original_chat
            RedisReplyStore.publish = original_publish
            for module, name, original in originals:
                setattr(module, name, original)
    # Keep schema for independent inspection; it contains no surviving accounts,
    # messages or credentials after fixture cleanup. Drop only by explicit owner.


async def coordinate(args):
    if not args.output or not args.before or not args.after:
        raise ValueError('Paired mode requires --before, --after and --output')
    if args.output.exists():
        raise RuntimeError('Result directory exists; preserve it and use a new run directory')
    args.output.mkdir(parents=True)
    children = {}
    logs = []
    rows = []
    try:
        for label, source in (('before', args.before), ('after', args.after)):
            log = (args.output / (label + '-stderr.log')).open('w')
            logs.append(log)
            process = await asyncio.create_subprocess_exec(sys.executable, str(Path(__file__).resolve()), '--worker', '--source', str(source.resolve()), '--label', label, '--output', str(args.output / label), '--fixtures', str(args.fixtures.resolve()), '--mode', args.mode, '--source-user', args.source_user, '--efforts', args.efforts, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=log, limit=16 * 1024 * 1024)
            children[label] = process
            line = await process.stdout.readline()
            if not line:
                raise RuntimeError(label + ' failed to initialize; see its stderr log')
            ready = json.loads(line)
            if not ready.get('ready'):
                raise RuntimeError('Unexpected worker startup output')
            print(json.dumps(ready), flush=True)
        environments = [json.loads((args.output / label / 'environment.json').read_text()) for label in ('before', 'after')]
        if environments[0]['model'] != environments[1]['model'] or environments[0]['manifest_sha256'] != environments[1]['manifest_sha256']:
            raise RuntimeError('A/B model configuration or fixture bytes differ')
        indices = list(range(args.start_index, args.start_index + args.samples))
        if args.mode == 'controlled':
            indices.insert(0, -1)
        for index in indices:
            for effort in args.efforts.split(','):
                for case in args.cases.split(','):
                    command = {'case': case, 'effort': effort, 'sample': index, 'warmup': index < 0}
                    order = ('before', 'after') if index % 2 == 0 else ('after', 'before')
                    for label in order:
                        child = children[label]
                        child.stdin.write((json.dumps(command) + '\n').encode())
                        await child.stdin.drain()
                        line = await child.stdout.readline()
                        if not line:
                            raise RuntimeError(label + ' stopped; preserve partial results and inspect stderr')
                        value = json.loads(line)
                        row = value['result']
                        rows.append(row)
                        append(args.output / 'paired-results.jsonl', row)
                        print(json.dumps({'case': case, 'sample': index, 'effort': effort, 'label': label, 'state': row.get('job', {}).get('state'), 'accuracy': row.get('accuracy'), 'first_answer_ms': row.get('first_answer_ms'), 'total_ms': row['total_ms'], 'model_calls': row.get('model_calls'), 'error': row.get('error')}, ensure_ascii=False), flush=True)
        write(args.output / 'summary.json', summarize(rows))
    finally:
        for child in children.values():
            if child.returncode is None:
                try:
                    child.stdin.write(b'{"stop":true}\n')
                    await child.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
        for child in children.values():
            await child.wait()
        for log in logs:
            log.close()
        if rows:
            write(args.output / 'summary.json', summarize(rows))


if __name__ == '__main__':
    args = options()
    if args.make_fixtures:
        sys.path.insert(0, str(ROOT / 'tests/server'))
        from _support.materials.spec072_samples import freeze
        print(json.dumps(freeze(args.fixtures)))
    elif args.worker:
        asyncio.run(worker(args))
    else:
        asyncio.run(coordinate(args))
