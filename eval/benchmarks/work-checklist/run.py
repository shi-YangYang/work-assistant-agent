"""Frozen paired low/high HTTP/SSE turns. Never resend an admitted/failed sample."""
import argparse
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from uuid import uuid4, uuid5, NAMESPACE_URL

import httpx
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/company/web-acceptance'))
from environment import load_environment
spec = importlib.util.spec_from_file_location('latency_helpers', ROOT / 'eval/benchmarks/assistant-latency.py')
latency = importlib.util.module_from_spec(spec)
spec.loader.exec_module(latency)
checked, write_json = latency.checked, latency.write_json


def paragraph(value):
    return {'type': 'paragraph', 'content': [{'type': 'text', 'text': value}]}


def task_items(body):
    def walk(node):
        result = []
        if node.get('type') == 'taskItem':
            result.append({'id': node.get('attrs', {}).get('id'), 'checked': node.get('attrs', {}).get('checked', False), 'text': node_text(node)})
        return result + [item for child in node.get('content', []) for item in walk(child)]
    return [item for node in (body or {}).get('content', []) for item in walk(node)]


def node_text(node):
    return node.get('text', '') + ''.join(node_text(child) for child in node.get('content', []))


async def setup(client, private, effort):
    actor = private['accounts']['realEmployee']
    identity = checked(await client.post('/api/v1/auth/login', json={'username': actor['username'], 'password': actor['password']}))
    client.headers['X-CSRF-Token'] = identity['csrf']
    execution = checked(await client.get('/api/v1/assistant/execution-settings'))
    if execution['executionMode'] != 'full':
        checked(await client.patch('/api/v1/assistant/execution-settings', json={'executionMode': 'full', 'fullAccessConfirmed': True, 'expectedRevision': execution['modeRevision']}))
    reasoning = checked(await client.get('/api/v1/assistant/reasoning-settings'))
    if reasoning.get('selected', {}).get('effort') != effort:
        reasoning = checked(await client.patch('/api/v1/assistant/reasoning-settings', json={'effort': effort, 'preferenceRevision': reasoning['preferenceRevision'], 'configVersion': reasoning['configVersion']}))
    if reasoning.get('selected', {}).get('effort') != effort:
        raise RuntimeError('Effective effort mismatch')
    return {'effort': effort, 'preferenceRevision': reasoning['preferenceRevision'], 'configVersion': reasoning['configVersion']}


async def fixture(client, manifest, kind, title):
    upload = checked(await client.post('/api/v1/uploads', files={'file': ('合成设备说明.txt', '合成资料：试验设备编号 S-63，请保留本材料。'.encode(), 'text/plain')}), (201,))
    if kind == 'checklist':
        items = [{'type': 'taskItem', 'attrs': {'id': str(uuid5(NAMESPACE_URL, title + ':' + str(i))), 'checked': item['checked']}, 'content': [paragraph(item['text'])]} for i, item in enumerate(manifest['initialItems'])]
        nodes = [{'type': 'taskList', 'content': items}, paragraph('备注：先确认打印设备可用。')]
    else:
        nodes = [paragraph('初始试验说明，等待补充正式内容。')]
    body = {'title': title, 'status': 'in_progress', 'dueDate': '2026-10-12', 'blocker': '打印设备需要检查', 'nextStep': '按约定推进', 'body': {'schemaVersion': 1, 'content': nodes}, 'materials': [{'attachmentId': upload['id']}]}
    return checked(await client.post('/api/v1/work-items', json=body, headers={'Idempotency-Key': str(uuid4())}), (201,))


def database_evidence(private, job_id, message_id):
    engine = create_engine(private['environment']['DATABASE_URL'])
    try:
        with engine.connect() as connection:
            connection.execute(text('SET TRANSACTION READ ONLY'))
            usages = connection.execute(text('SELECT kind,status,model_name,elapsed_ms,actual_input_tokens,actual_output_tokens,input_tokens,output_tokens,error_code FROM company_model_usage WHERE job_id=:job ORDER BY created_at'), {'job': job_id}).mappings().all()
            actions = connection.execute(text('SELECT id,action,state,result FROM company_business_action WHERE message_id=:message'), {'message': message_id}).mappings().all()
            work_ids = {row['result'].get('objectId') for row in actions if row['state'] == 'succeeded' and row['result'].get('objectType') == 'work'}
            revisions = []
            for work_id in work_ids:
                revisions.extend(dict(row) for row in connection.execute(text('SELECT work_id,revision,content FROM company_work_revision WHERE work_id=:work ORDER BY revision'), {'work': work_id}).mappings())
            return {'usage': [dict(row) for row in usages], 'actions': [dict(row) for row in actions], 'workRevisions': revisions}
    finally:
        engine.dispose()


def trace_evidence(path, job_id):
    events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    events = [row for row in events if row.get('jobId') == job_id]
    tools = [row['tool'] for row in events if row['kind'] == 'tool_dispatch']
    return {'modelAttempts': sum(row['kind'] == 'model_attempt_start' for row in events), 'providerRequests': sum(row['kind'] == 'provider_request_start' for row in events), 'tools': tools, 'toolCount': len(tools), 'events': events}


def quality(case, side, manifest, before, after, reply):
    changes = [work for work in after if work['title'] == case['title']]
    if case['id'] == 'knowledge':
        return {'noWorkWrites': before == after, 'replyNonempty': bool(reply.strip())}
    if len(changes) != 1:
        return {'exactlyOneTargetWork': False, 'targetWorks': len(changes)}
    work = changes[0]
    items = task_items(work.get('body'))
    raw = '\n'.join(node_text(n) for n in work.get('body', {}).get('content', []))
    result = {'exactlyOneTargetWork': True, 'statusUnchanged': work['status'] == 'in_progress', 'dueDatePreserved': work.get('dueDate') == '2026-10-12', 'items': items, 'rawBody': raw}
    if case['id'] == 'create':
        result.update({'checklistCountCorrect': len(items) == 17, 'allUnchecked': all(not item['checked'] for item in items), 'exactTextsInOrder': [item['text'] for item in items] == manifest['items'], 'allSourceTextsPresent': all(value in raw for value in manifest['items']), 'notePreserved': '办公打印机卡纸' in raw, 'candidateChecklistRequired': side == 'candidate'})
    elif case['id'] == 'append':
        previous = next(work for work in before if work['title'] == case['title'])
        initial = task_items(previous.get('body'))
        result.update({'checklistCountCorrect': len(items) == 6, 'initialItemsPreserved': items[:3] == initial, 'materialsPreserved': work.get('materialIds') == previous.get('materialIds'), 'otherFieldsPreserved': all(work.get(key) == previous.get(key) for key in ('status', 'dueDate', 'blocker', 'nextStep')), 'newItemsUnchecked': all(not item['checked'] for item in items[3:])})
    else:
        previous = next(work for work in before if work['title'] == case['title'])
        result.update({'noChecklist': not items, 'materialsPreserved': work.get('materialIds') == previous.get('materialIds'), 'conditionPreserved': all(value in raw for value in ('24', '45', '20', '风道', '没有实际试验结果'))})
    return result


def flow_checks(result, manifest=None):
    """Final content and the path to save it are separate acceptance dimensions."""
    actions = result.get('database', {}).get('actions', [])
    succeeded = [row for row in actions if row['state'] == 'succeeded' and row['action'] in ('create_work', 'update_work')]
    events = result.get('trace', {}).get('events', [])
    writes = [row for row in events if row['kind'] == 'tool_dispatch' and row.get('tool') == 'execute_business_action' and row.get('arguments', {}).get('action') in ('create_work', 'update_work')]
    responses = []
    for row in events:
        if row['kind'] == 'tool_dispatch_result' and row.get('tool') == 'execute_business_action':
            try:
                responses.append(json.loads(row.get('content', '{}')))
            except (ValueError, TypeError):
                responses.append({'category': 'unreadable_result'})
    result_checks = {'writeToolAttempts': len(writes), 'successfulWrites': len(succeeded), 'parameterRejections': sum(row.get('category') == 'invalid_arguments' for row in responses), 'rejectedWriteResults': sum(row.get('state') != 'succeeded' for row in responses)}
    if result.get('case') == 'create' and manifest:
        initial = [row for row in result.get('database', {}).get('workRevisions', []) if row['revision'] == 1]
        items = task_items(initial[0]['content'].get('body')) if len(initial) == 1 else []
        raw = '\n'.join(node_text(node) for node in initial[0]['content'].get('body', {}).get('content', [])) if len(initial) == 1 else ''
        result_checks['initialVersionComplete'] = len(items) == 17 and all(value in raw for value in manifest['items']) and '办公打印机卡纸' in raw and all(not item['checked'] for item in items)
        result_checks['singleCompleteCreation'] = result_checks['initialVersionComplete'] and len(succeeded) == 1 and len(writes) == 1 and result_checks['rejectedWriteResults'] == 0
    return result_checks


async def full_works(client):
    rows = await latency.works(client)
    return [checked(await client.get('/api/v1/work-items/' + work['id'])) for work in rows]


async def send(client, body, directory, *, timeout=1200):
    began = time.perf_counter()
    result = {'metrics': {'firstSseTextSeconds': None, 'terminalSseSeconds': None, 'finalReadbackSeconds': None}}
    observer = None
    try:
        receipt = checked(await client.post('/api/v1/messages', json=body, headers={'Idempotency-Key': str(uuid4())}), (202,))
        result['receipt'] = receipt
        result['metrics']['admittedSeconds'] = time.perf_counter() - began
        write_json(directory / 'admission.json', receipt)
        observer = asyncio.create_task(latency.observe(client, receipt, began, directory / 'sse.jsonl', 2, result['metrics']))
        async with asyncio.timeout(timeout):
            while True:
                message = checked(await client.get('/api/v1/messages/' + receipt['messageId']))
                if message.get('job', {}).get('state') in latency.TERMINAL:
                    result['message'] = message
                    result['metrics']['finalReadbackSeconds'] = time.perf_counter() - began
                    break
                await asyncio.sleep(.5)
        try:
            await asyncio.wait_for(asyncio.shield(observer), 3)
        except TimeoutError:
            observer.cancel()
    except Exception as error:
        result['exception'] = {'type': type(error).__name__, 'message': str(error)[:500]}
        if result.get('receipt'):
            job = checked(await client.get('/api/v1/jobs/' + result['receipt']['jobId']))
            if job['state'] in ('queued', 'running'):
                await client.post('/api/v1/jobs/' + job['id'] + '/cancel', json={'expectedAttempt': job['attempt'], 'expectedFence': job['fence']})
    finally:
        if observer:
            observer.cancel()
            await asyncio.gather(observer, return_exceptions=True)
    return result


async def sample(root, manifest, case, side, effort, pair):
    environment = root / side / 'environment.json'
    metadata, private = load_environment(environment)
    if metadata.get('suite') != 'spec063':
        raise RuntimeError('Exact spec063 ownership required')
    directory = root / 'samples' / effort / case['id'] / str(pair) / side
    if directory.exists():
        if (directory / 'result.json').exists():
            return
        raise RuntimeError('An unfinished first attempt exists; preserve it and investigate')
    directory.mkdir(parents=True)
    write_json(directory / 'started.json', {'wallTime': time.time(), 'schema': metadata['schema'], 'caseSha256': hashlib.sha256((Path(__file__).parent / 'cases.json').read_bytes()).hexdigest()})
    case = {**case, 'title': f"合成{case['id']}-{effort}-{pair}"}
    async with httpx.AsyncClient(base_url=metadata['apiUrl'], headers={'Origin': metadata['origin']}, timeout=45, trust_env=False) as client:
        reasoning = await setup(client, private, effort)
        work = await fixture(client, manifest, case['fixture'], case['title']) if case.get('fixture') else None
        before = await full_works(client)
        prompt = case['prompt'].format(title=case['title'], items='\n'.join(f'{i + 1}. {item}' for i, item in enumerate(manifest['items'])))
        body = {'text': prompt, 'attachmentIds': [], 'newConversation': True, 'personaId': manifest['persona'], 'reasoning': reasoning}
        if work:
            body['workReference'] = {'workId': work['id']}
        result = await send(client, body, directory)
        result.update({'case': case['id'], 'side': side, 'effort': effort, 'pair': pair, 'prompt': prompt, 'beforeWorks': before})
        result['afterWorks'] = await full_works(client)
        result['quality'] = quality(case, side, manifest, before, result['afterWorks'], result.get('message', {}).get('reply', ''))
        if result.get('receipt'):
            result['database'] = database_evidence(private, result['receipt']['jobId'], result['receipt']['messageId'])
            result['trace'] = trace_evidence(root / side / 'trace.jsonl', result['receipt']['jobId'])
            result['flow'] = flow_checks(result, manifest)
        write_json(directory / 'result.json', result)
        await client.post('/api/v1/auth/logout', json={})
        print(json.dumps({'sample': str(directory.relative_to(root)), 'state': result.get('message', {}).get('job', {}).get('state'), 'metrics': result['metrics'], 'quality': {k:v for k,v in result['quality'].items() if isinstance(v, bool)}, 'tools': result.get('trace', {}).get('tools'), 'exception': result.get('exception')}, ensure_ascii=False), flush=True)


async def main(args):
    root = Path(args.evidence).resolve()
    manifest = json.loads((Path(__file__).parent / 'cases.json').read_text())
    for effort in manifest['efforts']:
        for case in manifest['cases']:
            for pair in range(1, manifest['pairsPerCase'] + 1):
                for side in (('baseline', 'candidate') if pair % 2 else ('candidate', 'baseline')):
                    if (args.effort and effort != args.effort) or (args.case and case['id'] != args.case) or (args.side and side != args.side) or (args.pair and pair != args.pair):
                        continue
                    await sample(root, manifest, case, side, effort, pair)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--effort', choices=('low', 'high'))
    parser.add_argument('--side', choices=('baseline', 'candidate'))
    parser.add_argument('--case')
    parser.add_argument('--pair', type=int)
    asyncio.run(main(parser.parse_args()))
