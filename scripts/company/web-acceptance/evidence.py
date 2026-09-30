"""Read actual model usage and checkpoint tool outcomes, without message bodies."""
import argparse
import asyncio
from collections import Counter, defaultdict
import json
import os
from pathlib import Path

from environment import load_environment


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    metadata, private = load_environment(args.metadata)
    output = Path(args.output)
    if output.exists():
        raise RuntimeError('Refusing to overwrite evidence')
    os.environ.update(private['environment'])
    from sqlalchemy import select, text
    from app.core.config import Settings
    from app.db import registry
    from app.db.session import database
    from app.tasks.models import Job
    from app.modules.messages.models import Message
    from app.modules.model_services.models import ModelUsage
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    settings = Settings()
    engine, sessions = database(settings)
    company = metadata['companies']['real']
    try:
        async with sessions() as db:
            jobs = (await db.scalars(select(Job).where(Job.company_id == company))).all()
            messages = (await db.scalars(select(Message).where(Message.company_id == company))).all()
            usages = (await db.scalars(select(ModelUsage).where(ModelUsage.company_id == company))).all()
            threads = (await db.execute(text('SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE :prefix'), {'prefix': company + ':%'})).scalars().all()
        result = {
            'baseCommit': metadata['commit'], 'sourceState': 'Working tree with uncommitted Spec044 changes',
            'messages': len(messages), 'jobsByState': dict(Counter(j.state for j in jobs)),
            'activeJobs': [{'id': j.id, 'kind': j.kind, 'state': j.state} for j in jobs if j.state in ('queued', 'running')],
            'modelUsage': {
                'requests': len(usages), 'byKindAndStatus': dict(Counter(f'{u.kind}:{u.status}' for u in usages)),
                'reportedInputTokens': sum(u.actual_input_tokens or 0 for u in usages),
                'reportedOutputTokens': sum(u.actual_output_tokens or 0 for u in usages),
                'requestsMissingUsage': sum(u.actual_input_tokens is None or u.actual_output_tokens is None for u in usages),
                'scope': 'All recorded model calls including review, compaction and retry; missing usage is unknown, not zero',
            },
        }
        tools = defaultdict(lambda: {'success': 0, 'error': 0, 'jobs': set()})
        seen = set()
        from app.agent.harness import build_graph
        from app.tasks.context import RunContext
        from langchain_openai import ChatOpenAI
        by_id = {job.id: job for job in jobs}
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_url) as saver:
            for thread in threads:
                job_id = thread.split(':job:', 1)[-1].split(':', 1)[0]
                job = by_id.get(job_id)
                if not job or thread.endswith(':context'):
                    continue
                context = RunContext(job.owner_id, company, job.id, job.fence, sessions, settings)
                graph = build_graph(settings, saver, context, model=ChatOpenAI(model='read-only-state', api_key='unused'))
                # get_state reconstructs delta-backed channels. It never invokes
                # a graph, model, tool or business write.
                state = await graph.aget_state({'configurable': {'thread_id': thread, 'checkpoint_ns': ''}})
                values = state.values.get('messages', [])
                calls = {call['id']: call['name'] for message in values for call in getattr(message, 'tool_calls', [])}
                for message in values:
                    identifier = getattr(message, 'tool_call_id', None)
                    name = calls.get(identifier) or getattr(message, 'name', None)
                    if not identifier or not name or (job_id, identifier) in seen:
                        continue
                    seen.add((job_id, identifier))
                    row = tools[name]
                    row['error' if getattr(message, 'status', 'success') == 'error' else 'success'] += 1
                    row['jobs'].add(job_id)
        result['toolOutcomes'] = {name: {**row, 'jobs': sorted(row['jobs'])} for name, row in sorted(tools.items())}
        result['toolOutcomeScope'] = 'Actual checkpoint ToolMessage status, not independent semantic acceptance'
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print({key: result[key] for key in ('messages', 'jobsByState', 'activeJobs', 'modelUsage')})
        print('Tool names observed:', ', '.join(tools))
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
