"""Invoke existing owned HTTP/worker/browser drivers, never the production DB."""
import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from .evidence import ROOT, read, write

AUDIT = ROOT / 'eval/web/agent-audit'
ENVIRONMENT = ROOT / 'scripts/company/web-acceptance'


def environment(metadata):
    sys.path.insert(0, str(ENVIRONMENT))
    from runner_environment import runner_environment
    return runner_environment(metadata_path=metadata)


async def execute(case, slot, directory, metadata, materials, timeout):
    _, owned, state = environment(metadata)
    if case['execution'] == 'contract/replay':
        from .permission_contract import evaluate
        return await evaluate(metadata, directory / 'contract')
    config = read(Path(metadata).parent / 'configuration.json')['models']['assistant']
    model = slot['model']
    if config['baseUrl'] != model['provider'] or config['model']['model'] != model['model'] or config['model'].get('parameters', {}) != model['parameters'] or model['effort'] not in config['model']['reasoning']['efforts']:
        raise ValueError('Frozen model configuration differs; no downgrade')
    global_trace = Path(metadata).parent / 'trace.jsonl'
    metadata, state = await isolate_actor(metadata, directory, owned, state)
    value = copy.deepcopy(case['input'])
    value['effort'] = model['effort']
    # All trials use independent actors and tenants, created by existing seed API
    # environment orchestration. Reject reuse rather than silently contaminate.
    value['id'] = slot['id']
    if case['execution'] == 'real-browser':
        value['verifyAfterReload'] = True
    if case.get('materials'):
        materials = directory / 'materials'; materials.mkdir()
        for name, content in case['materials'].items():
            if Path(name).name != name:
                raise ValueError('Unsafe material path')
            (materials / name).write_bytes(__import__('base64').b64decode(content['base64'])) if isinstance(content, dict) else (materials / name).write_text(content)
    started = time.monotonic()
    if case['execution'] == 'real-browser':
        cases = directory / 'browser-cases.json'
        write(cases, [value])
        env = {**os.environ, 'SPEC059_ENVIRONMENT': str(Path(metadata).resolve()), 'SPEC059_BROWSER_OUTPUT': str(directory / 'browser'), 'SPEC059_BROWSER_CASES': str(cases)}
        process = await asyncio.create_subprocess_exec('node', str(AUDIT / 'browser.mjs'), env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, start_new_session=True)
        from .cancellation import terminate_process
        try:
            out, _ = await process.communicate()
        except BaseException:
            await terminate_process(process)
            raise
        (directory / 'browser.log').write_bytes(out)
        result_path = directory / 'browser' / value['id'] / 'result.json'
        result = read(result_path) if result_path.exists() else {'turns': []}
        result = enrich(result, global_trace, state, directory)
        return {**result, 'execution': 'real-browser', 'exitCode': process.returncode, 'seconds': time.monotonic() - started, 'evidence': 'browser'}
    sys.path.insert(0, str(AUDIT))
    spec = importlib.util.spec_from_file_location('eval_audit_run', AUDIT / 'run.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    await runner.configure_case(value, state, directory / value['id'])
    token = runner.approval.current.set((value, directory / value['id']))
    try:
        result = await runner.http.execute_case(value, state, directory, Path(materials), timeout)
        result = enrich(result, global_trace, state, directory)
        return {**result, 'execution': 'real-model', 'seconds': time.monotonic() - started}
    finally:
        runner.approval.current.reset(token)


async def isolate_actor(metadata_path, directory, metadata, state):
    """Seed a fresh synthetic tenant per slot inside the ownership-checked schema."""
    from environment import load_environment, private_json
    _, private = load_environment(metadata_path)
    os.environ.update(private['environment'])
    sys.path.insert(0, str(ROOT / 'apps/server'))
    from app.core.config import Settings
    from app.db.session import database
    from app.db import registry
    from app.modules.members.models import Company, Member
    from app.modules.model_services.models import ModelRouting, ModelService, ModelServiceRevision
    from app.security.secrets import decrypt, encrypt
    from sqlalchemy import select
    from uuid import uuid4
    settings = Settings()
    engine, sessions = database(settings)
    new_state = copy.deepcopy(state)
    new_meta = copy.deepcopy(metadata)
    try:
        async with sessions.begin() as db:
            partitions = {}
            for source_company in sorted({a['companyId'] for a in state['users'].values()}):
                company = Company(name='spec082 independent trial ' + directory.name, environment_models=False)
                db.add(company); await db.flush()
                partitions[source_company] = company.id
                routing = await db.get(ModelRouting, source_company)
                choices = copy.deepcopy(routing.choices)
                for purpose, choice in choices.items():
                    if not isinstance(choice, dict):
                        continue
                    service = await db.get(ModelService, choice['serviceId'])
                    revision = await db.scalar(select(ModelServiceRevision).where(ModelServiceRevision.service_id == service.id, ModelServiceRevision.revision == service.revision))
                    sid = str(uuid4())
                    key = decrypt(settings.model_key_file, revision.credential, source_company, service.id, revision.revision)
                    clone = ModelService(id=sid, company_id=company.id, name=service.name, base_url=revision.base_url, models=revision.models)
                    db.add(clone); await db.flush()
                    db.add(ModelServiceRevision(company_id=company.id, service_id=sid, revision=1, name=clone.name, base_url=clone.base_url, models=clone.models, credential=encrypt(settings.model_key_file, key, company.id, sid, 1)))
                    choice['serviceId'] = sid
                db.add(ModelRouting(company_id=company.id, choices=choices))
            for role, account in new_state['users'].items():
                original = await db.get(Member, account['id'])
                company_id = partitions[account['companyId']]
                member = Member(company_id=company_id, username='spec082_' + uuid4().hex[:18], name='合成 ' + role, role=original.role, password_hash=original.password_hash, active=original.active, deleted=original.deleted)
                db.add(member); await db.flush()
                account.update(id=member.id, username=member.username, companyId=company_id)
            new_meta['companies'] = {label: partitions[value] for label, value in metadata['companies'].items()}
    finally:
        await engine.dispose()
    local = directory / 'environment'; local.mkdir()
    new_meta['credentialsFile'] = str((local / 'credentials.json').resolve())
    private_json(local / 'credentials.json', new_state)
    write(local / 'metadata.json', new_meta)
    return local / 'metadata.json', new_state


def enrich(result, trace, state, directory):
    for snapshot in [result.get('before', {}), result.get('after', {})] + [r.get('readback', {}) for r in result.get('turns', [])]:
        for key in ('work', 'weekly'):
            if isinstance(snapshot.get(key), list):
                snapshot[key] = {'status': 200, 'items': snapshot[key]}
    companies = {a['companyId'] for a in state['users'].values()}
    rows = [json.loads(line) for line in trace.read_text().splitlines() if line.strip()]
    events = [r for r in rows if r.get('companyId') in companies or r.get('scope', {}).get('companyId') in companies]
    write(directory / 'trace.json', events)
    result['trace'] = events
    result['evidenceAvailable'] = ['reply'] if result.get('turns') else []
    if events:
        result['evidenceAvailable'].append('trace')
    inputs = [r['input'] for r in events if r['kind'] == 'upstream_http_start' and r.get('input')]
    expected_calls = {r.get('providerRequestId') for r in events if r['kind'] == 'provider_request_start'}
    observed_calls = {r.get('providerRequestId') for r in events if r['kind'] == 'upstream_http_start' and r.get('input')}
    if expected_calls and expected_calls == observed_calls and inputs and all('messages' in v and any(m.get('role') == 'system' and 'content' in m for m in v['messages']) for v in inputs):
        result['evidenceAvailable'].append('actual-model-input')
    if result.get('before') and result.get('after'):
        result['evidenceAvailable'].append('database-before-after')
    if list(directory.rglob('*.png')) and any(r.get('afterReload') for r in result.get('turns', [])):
        result['evidenceAvailable'].append('browser')
    result['evidenceFiles'] = {str(p.relative_to(directory)): __import__('hashlib').sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file() and 'environment' not in p.relative_to(directory).parts}
    result['timing'] = [read(p) for p in directory.rglob('metrics-*.json')]
    result['usage'] = [r.get('response', {}).get('usage') for r in events if r['kind'] == 'provider_request_end']
    result['providerRequests'] = sum(r['kind'] == 'provider_request_start' for r in events)
    result['cost'] = None
    return result
