"""Owned Spec073 synthetic provider and production task runner; no paid services."""
import argparse
import asyncio
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import re
import signal
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from environment import load_environment

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--metadata', required=True)
parser.add_argument('mode', choices=['configure', 'provider', 'worker'])
args = parser.parse_args()
metadata, private = load_environment(args.metadata)
if metadata['suite'] != 'spec073' or metadata['purpose'] != 'web':
    raise RuntimeError('Exact owned Spec073 environment required')
os.environ.update(private['environment'])
os.environ.update(PAA_MODEL_ALLOWED_ORIGINS='http://127.0.0.1:8096')
stream_url = os.environ.get('SPEC073_STREAM_REDIS', '')
if stream_url not in ('', 'redis://127.0.0.1:16383/0'):
    raise RuntimeError('Only the dedicated owned Redis is allowed')
os.environ.update(PAA_REPLY_STREAM_REDIS_URL=stream_url, PAA_REPLY_STREAM_NAMESPACE='spec073:' + metadata['runId'])
for key in tuple(os.environ):
    if key.lower() in ('http_proxy', 'https_proxy', 'all_proxy'):
        del os.environ[key]
output = Path(args.metadata).resolve().parent


async def configure():
    from app.core.config import Settings
    from app.db import registry
    from app.db.session import database
    from app.modules.model_services.models import ModelRouting, ModelService, ModelServiceRevision
    from app.modules.model_services.schemas import ServiceModel
    from app.security.secrets import encrypt
    settings = Settings()
    engine, sessions = database(settings)
    # Only primary company; other company remains independent for UI configuration journeys.
    company = metadata['companies']['primary']
    model = ServiceModel(id='controlled-model', model='synthetic-mobile-audit', protocol='chat', contextWindow=100000).model_dump()
    async with sessions.begin() as db:
        if await db.get(ModelRouting, company):
            raise RuntimeError('Refusing to overwrite existing routing')
        service = ModelService(id=str(uuid4()), company_id=company, name='合成 UI 固定响应（无付费调用）', base_url='http://127.0.0.1:8096/v1', models=[model])
        db.add(service)
        await db.flush()
        db.add(ModelServiceRevision(company_id=company, service_id=service.id, revision=1, name=service.name, base_url=service.base_url, models=service.models, credential=encrypt(settings.model_key_file, 'synthetic-not-secret', company, service.id, 1)))
        db.add(ModelRouting(company_id=company, choices={'assistant': {'serviceId': service.id, 'modelId': model['id']}}))
    await engine.dispose()
    print('Configured synthetic localhost model for owned primary company')


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        prompt = json.dumps(body.get('messages', []), ensure_ascii=False)
        tags = sorted(set(re.findall(r'SPEC073_MARKER_[A-Z0-9_]+', prompt)))
        with (output / 'provider-requests.jsonl').open('a') as out:
            out.write(json.dumps({'path': self.path, 'stream': bool(body.get('stream')), 'messageCount': len(body.get('messages', [])), 'markers': tags, 'at': time.time()}, ensure_ascii=False) + '\n')
        reply = '受控 UI 验收回复：真实任务已完成。' + ('本次输入中的合成标记：' + '、'.join(tags) if tags else '本条用于核对消息状态、刷新和返回。')
        if 'SPEC073_MARKER_STREAM' in prompt:
            reply += '\n' + ''.join(f'第{n}段：这是一条受控的长回复，用于核对流式消息在切换页面、返回和取消后的状态。' for n in range(1, 25))
        if body.get('stream'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            for part in [reply[i:i+5] for i in range(0, len(reply), 5)]:
                chunk = {'id': 'spec073-' + uuid4().hex, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': body.get('model', 'synthetic'), 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': part}, 'finish_reason': None}]}
                self.wfile.write(('data: ' + json.dumps(chunk, ensure_ascii=False) + '\n\n').encode())
                self.wfile.flush()
                time.sleep(.15)
            self.wfile.write(('data: ' + json.dumps({'id': 'spec073-done', 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': 'synthetic', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}) + '\n\ndata: [DONE]\n\n').encode())
            self.wfile.flush()
        else:
            data = json.dumps({'id': 'spec073-' + uuid4().hex, 'object': 'chat.completion', 'created': int(time.time()), 'model': body.get('model', 'synthetic'), 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': reply}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 30, 'total_tokens': 130}}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)


async def worker():
    from app.core.config import Settings
    from app.db import registry
    from app.db.session import database
    from app.tasks.runtime.runner import run_slots
    from psycopg import AsyncConnection
    settings = Settings()
    engine, sessions = database(settings)
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    key = int(hashlib.sha256(metadata['schema'].encode()).hexdigest()[:7], 16)
    async with await AsyncConnection.connect(settings.checkpoint_url, autocommit=True) as guard:
        if not (await (await guard.execute('SELECT pg_try_advisory_lock(%s)', (key,))).fetchone())[0]:
            raise RuntimeError('Owned worker already running')
        try:
            await run_slots(sessions, settings, stop)
        finally:
            from app.tasks.streaming.redis_store import close_stores
            await close_stores()
            await engine.dispose()


if args.mode == 'configure':
    asyncio.run(configure())
elif args.mode == 'provider':
    ThreadingHTTPServer(('127.0.0.1', 8096), Provider).serve_forever()
else:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(worker())
