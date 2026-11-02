"""Candidate-only multi-turn read/write and ambiguity journeys; no quality reruns."""
import argparse
import asyncio
import json
from pathlib import Path
import time
from uuid import uuid4
import httpx

from run import checked, database_evidence, flow_checks, full_works, load_environment, paragraph, send, setup, task_items, trace_evidence, write_json


async def seed_ambiguity(client, title):
    def task(label, identifier):
        return {'type': 'taskItem', 'attrs': {'checked': False, 'id': identifier}, 'content': [paragraph(label)]}
    nodes = [{'type': 'heading', 'attrs': {'level': 2}, 'content': [{'type': 'text', 'text': '招聘'}]}, {'type': 'taskList', 'content': [task('打印材料', 'recruit-print')]}, {'type': 'heading', 'attrs': {'level': 2}, 'content': [{'type': 'text', 'text': '报销'}]}, {'type': 'taskList', 'content': [task('打印材料', 'expenses-print'), task('律师审核后交经理确认合同', 'contract-composite')]}]
    return checked(await client.post('/api/v1/work-items', json={'title': title, 'status': 'in_progress', 'body': {'schemaVersion': 1, 'content': nodes}}, headers={'Idempotency-Key': str(uuid4())}), (201,))


def flags(work):
    return {item['text']: item['checked'] for item in task_items(work.get('body'))}


async def journey(root, manifest, case, effort):
    metadata, private = load_environment(root / 'candidate/environment.json')
    if metadata.get('suite') != 'spec063':
        raise RuntimeError('Exact spec063 ownership required')
    directory = root / 'journeys' / effort / case['id']
    if directory.exists():
        if (directory / 'result.json').exists():
            return
        raise RuntimeError('Unfinished first journey exists; do not rerun')
    directory.mkdir(parents=True)
    title = f"合成旅程-{case['id']}-{effort}"
    write_json(directory / 'started.json', {'time': time.time(), 'title': title})
    async with httpx.AsyncClient(base_url=metadata['apiUrl'], headers={'Origin': metadata['origin']}, timeout=45, trust_env=False) as client:
        reasoning = await setup(client, private, effort)
        work = await seed_ambiguity(client, title) if case['id'] == 'ambiguity' else None
        rows, conversation = [], None
        for index, prompt in enumerate(case['turns']):
            turn_dir = directory / str(index + 1)
            turn_dir.mkdir()
            before = checked(await client.get('/api/v1/work-items/' + work['id'])) if work else None
            body = {'text': prompt.format(title=title), 'attachmentIds': [], 'reasoning': reasoning}
            if conversation:
                body['conversationId'] = conversation
            else:
                body.update({'newConversation': True, 'personaId': manifest['persona']})
            if work:
                body['workReference'] = {'workId': work['id']}
            result = await send(client, body, turn_dir)
            if result.get('receipt'):
                conversation = result['receipt']['conversationId']
                result['database'] = database_evidence(private, result['receipt']['jobId'], result['receipt']['messageId'])
                result['trace'] = trace_evidence(root / 'candidate/trace.jsonl', result['receipt']['jobId'])
            if not work:
                matches = [row for row in await full_works(client) if row['title'] == title]
                if len(matches) == 1:
                    work = matches[0]
            after = checked(await client.get('/api/v1/work-items/' + work['id'])) if work else None
            result.update({'prompt': body['text'], 'beforeWork': before, 'afterWork': after})
            result['flow'] = flow_checks(result)
            if case['id'] == 'lifecycle':
                expected = [False, False, False] if index == 0 else [True, True, False] if index == 2 else [True, False, False]
                result['quality'] = {'workCreated': bool(after), 'correctStates': bool(after) and [item['checked'] for item in task_items(after.get('body'))] == expected, 'wholeWorkUnchanged': bool(after) and after['status'] == 'in_progress'}
                if index in (1, 4):
                    result['quality']['readOnly'] = before == after
            else:
                expected = [False, False, False] if index < 2 else [True, False, index == 3]
                result['quality'] = {'correctStates': bool(after) and [item['checked'] for item in task_items(after.get('body'))] == expected, 'wholeWorkUnchanged': bool(after) and after['status'] == 'in_progress'}
                if index < 2:
                    result['quality']['noAmbiguousWrites'] = before == after
            write_json(turn_dir / 'result.json', result)
            rows.append(result)
            print(json.dumps({'journey': case['id'], 'effort': effort, 'turn': index + 1, 'metrics': result['metrics'], 'quality': result['quality'], 'tools': result.get('trace', {}).get('tools')}, ensure_ascii=False), flush=True)
            if case['id'] == 'lifecycle' and index == 0:
                items = task_items(after.get('body')) if after else []
                if len(items) != 3 or not items[0]['id']:
                    rows.append({'blocked': 'Model did not create the required identified checklist; dependent steps not fabricated'})
                    break
                manual = checked(await client.patch('/api/v1/work-items/' + work['id'], json={'expectedRevision': after['revision'], 'bodyEdits': [{'action': 'set_checked', 'itemId': items[0]['id'], 'checked': True}]}, headers={'Idempotency-Key': str(uuid4())}))
                write_json(directory / 'manual-check.json', manual)
        write_json(directory / 'result.json', {'journey': case['id'], 'effort': effort, 'turns': rows})
        await client.post('/api/v1/auth/logout', json={})


async def main(args):
    manifest = json.loads((Path(__file__).parent / 'cases.json').read_text())
    for effort in manifest['efforts']:
        for case in manifest['journeys']:
            if (not args.effort or args.effort == effort) and (not args.journey or args.journey == case['id']):
                await journey(Path(args.evidence).resolve(), manifest, case, effort)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--effort', choices=('low', 'high'))
    parser.add_argument('--journey', choices=('lifecycle', 'ambiguity'))
    asyncio.run(main(parser.parse_args()))
