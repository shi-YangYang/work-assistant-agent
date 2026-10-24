"""One fixed low/high current-work journey; preserve failures without resampling."""
import argparse
import asyncio
import json
from pathlib import Path
import httpx
from run import checked, database_evidence, full_works, load_environment, send, setup, trace_evidence, write_json


async def journey(root, effort):
    metadata, private = load_environment(root / 'environment.json')
    if metadata.get('suite') != 'spec079':
        raise RuntimeError('Exact spec079 ownership required')
    directory = root / effort
    directory.mkdir()  # A partial or completed run must never be overwritten.
    title = '合成当前内容验收-' + effort
    prompts = [
        f'请新建一项工作，标题为“{title}”，正文完整保存“目标：改进客户官网。计划：先确认需求，再安排首页评审；尚未完成上线。”，状态为进行中。不要生成报告。',
        '请为这项工作记录一条进展：“客户已确认首页配色，仍需评审移动端。”，整项工作保持进行中，正文计划保持不变。',
        '请读取这项工作的当前正文、状态和进展，告诉我已记录的事实与尚未完成的计划。只查询，不修改。',
    ]
    rows, work, conversation = [], None, None
    async with httpx.AsyncClient(base_url=metadata['apiUrl'], headers={'Origin': metadata['origin']}, timeout=45, trust_env=False) as client:
        reasoning = await setup(client, private, effort)
        write_json(directory / 'manifest.json', {'effort': effort, 'reasoning': reasoning, 'prompts': prompts, 'sampling': 'one attempt per turn; no quality retries'})
        for index, prompt in enumerate(prompts):
            turn = directory / str(index + 1)
            turn.mkdir()
            before = checked(await client.get('/api/v1/work-items/' + work['id'])) if work else None
            body = {'text': prompt, 'attachmentIds': [], 'reasoning': reasoning}
            body.update({'conversationId': conversation} if conversation else {'newConversation': True, 'personaId': 'professional'})
            if work:
                body['workReference'] = {'workId': work['id']}
            result = await send(client, body, turn)
            if result.get('receipt'):
                receipt = result['receipt']
                conversation = receipt['conversationId']
                result['database'] = database_evidence(private, receipt['jobId'], receipt['messageId'])
                result['trace'] = trace_evidence(root / 'trace.jsonl', receipt['jobId'])
            matches = [item for item in await full_works(client) if item['title'] == title]
            work = matches[0] if len(matches) == 1 else None
            updates = checked(await client.get('/api/v1/work-items/' + work['id'] + '/updates')) if work else None
            job = result.get('message', {}).get('job', {})
            # Completed read-only replies intentionally settle at awaiting_input.
            delivered = job.get('phase') == 'complete' and job.get('state') in ('succeeded', 'awaiting_input') and job.get('taskOutcome', {}).get('state') == 'completed' and not job.get('error')
            checks = {'oneTargetWork': len(matches) == 1, 'replyDelivered': delivered}
            if work:
                checks.update(bodyPreserved=work['bodyText'] == '目标：改进客户官网。计划：先确认需求，再安排首页评审；尚未完成上线。', inProgress=work['status'] == 'in_progress')
                checks['expectedProgress'] = ([item['text'] for item in updates['items']] == ([] if index == 0 else ['客户已确认首页配色，仍需评审移动端。']))
                if index == 2:
                    checks['queryDidNotWrite'] = before == work
            result.update(prompt=prompt, beforeWork=before, afterWork=work, updates=updates, checks=checks)
            write_json(turn / 'result.json', result)
            rows.append(result)
            print(json.dumps({'effort': effort, 'turn': index + 1, 'checks': checks, 'seconds': result['metrics'].get('finalReadbackSeconds'), 'tools': result.get('trace', {}).get('tools'), 'exception': result.get('exception')}, ensure_ascii=False), flush=True)
            if work is None:
                break  # Do not manufacture a target after an unsuccessful creation.
        write_json(directory / 'result.json', {'effort': effort, 'turns': rows})
        await client.post('/api/v1/auth/logout', json={})


async def main(args):
    for effort in ('low', 'high'):
        await journey(Path(args.evidence).resolve(), effort)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True)
    asyncio.run(main(parser.parse_args()))
