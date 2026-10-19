"""Six real direct-provider observations, separate from Agent quality scores."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
sys.path.insert(0, str(HERE.parents[1]))
from environment import load_environment


async def main(args):
    metadata, private = load_environment(args.metadata)
    if metadata.get('suite') != 'spec074':
        raise RuntimeError('Spec074 owned environment required')
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    os.environ.update(private['environment'])
    from app.core.config import Settings
    from app.db import registry
    from app.db.session import database
    from app.modules.model_services.models import ModelRouting, ModelService, ModelServiceRevision
    from app.modules.model_services.parameters import request_options
    from app.modules.model_services.routing_choices import unified_choices
    from app.security.secrets import decrypt
    from sqlalchemy import select, text
    import trace as observer
    observer.install(root / 'trace.jsonl')
    from app.integrations.models.chat import _chat
    settings = Settings()
    engine, sessions = database(settings)
    try:
        async with sessions() as db:
            await db.execute(text('SET TRANSACTION READ ONLY'))
            company = private['accounts']['realEmployee']['companyId']
            routing = await db.get(ModelRouting, company)
            selection = unified_choices(routing.choices)['assistant']
            service = await db.get(ModelService, selection['serviceId'])
            revision = await db.scalar(select(ModelServiceRevision).where(
                ModelServiceRevision.service_id == service.id,
                ModelServiceRevision.revision == service.revision))
            model = next(row for row in revision.models if row['id'] == selection['modelId'])
            key = decrypt(settings.model_key_file, revision.credential, company, service.id, revision.revision)
            base = revision.base_url
        rows = []
        for number in range(1, 4):
            for effort in (('low', 'high') if number % 2 else ('high', 'low')):
                identifier = f'direct-chat-{effort}-{number}'
                config = {'baseUrl': base, 'model': model['model'], 'protocol': model['protocol'],
                          'parameters': request_options(model, effort), 'streaming': model['streaming']}
                if config['parameters'].get('reasoning_effort') != effort:
                    raise RuntimeError('Frozen direct-provider effort unavailable; refusing downgrade')
                started = time.perf_counter()
                events = []

                def timing(event, **fields):
                    events.append({'event': event, 'seconds': time.perf_counter() - started, **fields})

                token = observer.scope.set({'caseId': identifier, 'jobId': identifier, 'directProvider': True})
                record = {'id': identifier, 'effort': effort,
                          'input': '计算17加26，只给结果，不需要调用工具。',
                          'actualConfig': {k: v for k, v in config.items() if k != 'baseUrl'},
                          'basis': 'direct same-provider transport; no Agent prompt/tools/queue; not browser paint'}
                try:
                    response = await _chat(settings, config, key,
                                           [{'role': 'user', 'content': record['input']}],
                                           max_tokens=None, on_timing=timing)
                    record.update(status='succeeded', response=response)
                except Exception as error:
                    record.update(status='failed', error=type(error).__name__, code=getattr(error, 'code', None))
                finally:
                    record.update(seconds=time.perf_counter() - started, events=events)
                    observer.scope.reset(token)
                (root / (identifier + '.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2))
                rows.append(record)
                print(json.dumps({'case': identifier, 'status': record['status'], 'seconds': record['seconds']}), flush=True)
        (root / 'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--output', required=True)
    asyncio.run(main(parser.parse_args()))
