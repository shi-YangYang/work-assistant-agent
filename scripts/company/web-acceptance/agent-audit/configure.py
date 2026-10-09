"""Copy selected local model configuration into an ownership-checked test schema.

Credentials remain in encrypted DB records, never in evidence or stdout.
"""
import argparse
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from environment import load_environment, ROOT
sys.path.insert(0, str(ROOT / 'apps/server'))
from app.core.config import Settings
from app.db.session import database
from app.db import registry
from app.modules.members.models import Member
from app.modules.model_services.models import ModelRouting, ModelService, ModelServiceRevision
from app.security.secrets import decrypt, encrypt
from sqlalchemy import select, text


async def configure(path, username):
    original = Settings()
    source_engine, source_sessions = database(original)
    configs = {}
    try:
        async with source_sessions() as db:
            await db.execute(text('SET TRANSACTION READ ONLY'))
            members = list(await db.scalars(select(Member).where(Member.username == username, Member.active.is_(True))))
            if len(members) != 1:
                raise RuntimeError('Expected one local source account')
            company = members[0].company_id
            routing = await db.get(ModelRouting, company)
            for purpose, choice in routing.choices.items():
                if not choice:
                    continue
                service = await db.get(ModelService, choice['serviceId'])
                revision = await db.scalar(select(ModelServiceRevision).where(ModelServiceRevision.service_id == service.id, ModelServiceRevision.revision == service.revision))
                model = next(m for m in revision.models if m['id'] == choice['modelId'])
                configs[purpose] = {'base': revision.base_url, 'model': copy.deepcopy(model), 'choice': copy.deepcopy(choice), 'key': decrypt(original.model_key_file, revision.credential, company, service.id, revision.revision)}
    finally:
        await source_engine.dispose()
    metadata, private = load_environment(path)
    env = private['environment']
    env.update({'PAA_REPLY_STREAM_REDIS_URL': original.reply_stream_redis_url or 'redis://127.0.0.1:6379/0', 'PAA_REPLY_STREAM_NAMESPACE': 'spec059:' + metadata['runId'], 'PAA_SANDBOX_URL': original.sandbox_url, 'PAA_SANDBOX_TOKEN': original.sandbox_token})
    Path(metadata['secretFile']).write_text(json.dumps(private, ensure_ascii=False, indent=2))
    import shlex
    Path(metadata['secretEnvFile']).write_text(''.join(f'export {k}={shlex.quote(v)}\n' for k, v in env.items()))
    os.environ.update(env)
    settings = Settings()
    engine, sessions = database(settings)
    try:
        async with sessions.begin() as db:
            for company in metadata['companies'].values():
                choices = {}
                for purpose, config in configs.items():
                    sid = str(uuid4())
                    model = config['model']
                    service = ModelService(id=sid, company_id=company, name='Spec059 ' + purpose, base_url=config['base'], models=[model])
                    db.add(service)
                    await db.flush()
                    db.add(ModelServiceRevision(company_id=company, service_id=sid, revision=1, name=service.name, base_url=service.base_url, models=service.models, credential=encrypt(settings.model_key_file, config['key'], company, sid, 1)))
                    choices[purpose] = {**config['choice'], 'serviceId': sid, 'modelId': model['id']}
                db.add(ModelRouting(company_id=company, choices=choices))
    finally:
        await engine.dispose()
    public = {'models': {p: {'baseUrl': c['base'], 'model': c['model'], 'streaming': c['choice'].get('streaming')} for p, c in configs.items()}, 'sandbox': bool(original.sandbox_url and original.sandbox_token), 'redis': bool(env['PAA_REPLY_STREAM_REDIS_URL']), 'namespace': env['PAA_REPLY_STREAM_NAMESPACE']}
    (Path(path).parent / 'configuration.json').write_text(json.dumps(public, ensure_ascii=False, indent=2))
    print(json.dumps(public, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--metadata', required=True)
    p.add_argument('--source-user', default='admin')
    args = p.parse_args()
    asyncio.run(configure(args.metadata, args.source_user))
