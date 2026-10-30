"""Owned Spec081 runtime: passive, symmetric synthetic evidence only.

No credentials/headers or provider private reasoning are recorded. The complete
outgoing chat JSON is captured only in this explicitly owned test process.
"""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import time
from contextvars import ContextVar
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / 'scripts/company/web-acceptance'
sys.path.insert(0, str(SUPPORT))
from environment import load_environment

REQUEST_ID = ContextVar('latency_request_id', default=None)
MAX_FAILURE_CHARS = 64000
MAX_FAILURE_DELTAS = 1024


def redact_secret(value, secret):
    """Redact even a known provider key split across adjacent public fragments."""
    strings = []
    def collect(item):
        if isinstance(item, str):
            strings.append(item)
        elif isinstance(item, list):
            for child in item:
                collect(child)
        elif isinstance(item, dict):
            for child in item.values():
                collect(child)
    collect(value)
    combined = ''.join(strings)
    if secret:
        combined = combined.replace(secret, '*' * len(secret))
    offset = 0
    def rebuild(item):
        nonlocal offset
        if isinstance(item, str):
            start, offset = offset, offset + len(item)
            return combined[start:offset]
        if isinstance(item, list):
            return [rebuild(child) for child in item]
        if isinstance(item, dict):
            return {key: rebuild(child) for key, child in item.items()}
        return item
    return rebuild(value)


def observed_chat_call(original_chat, trace):
    async def observed_chat(*args, **kwargs):
        start = time.perf_counter()
        request_id = uuid4().hex
        token = REQUEST_ID.set(request_id)
        original_delta, original_timing = kwargs.get('on_delta'), kwargs.get('on_timing')
        fragments, chars, omitted, stage = [], 0, 0, 'before_send'
        diagnostic = None
        secret = args[2] if len(args) > 2 else kwargs.get('key', '')

        async def delta(value):
            nonlocal chars, omitted
            public = {'content': value.text, 'tools': [
                {'index': item.index, 'name': item.name, 'arguments': item.arguments, 'id': item.id}
                for item in value.tools]}
            size = len(json.dumps(public, ensure_ascii=False))
            if not omitted and len(fragments) < MAX_FAILURE_DELTAS and chars + size <= MAX_FAILURE_CHARS:
                fragments.append(public)
                chars += size
            else:
                omitted += 1
            if original_delta:
                await original_delta(value)

        def timing(event, **fields):
            nonlocal stage, diagnostic
            stage = event
            if event == 'model.invalid_response':
                diagnostic = fields.get('reason')
            if original_timing:
                original_timing(event, **fields)

        kwargs.update(on_delta=delta, on_timing=timing)
        try:
            result = await original_chat(*args, **kwargs)
            trace.emit('wire_output', requestId=request_id, seconds=time.perf_counter() - start,
                       response=redact_secret({'usage': result.get('usage'), 'choices': [
                           {'finish_reason': c.get('finish_reason'), 'message': {
                               k: c.get('message', {}).get(k) for k in ('role', 'content', 'tool_calls')}}
                           for c in result.get('choices', [])]}, secret))
            return result
        except BaseException as error:
            try:
                trace.emit('wire_failure', requestId=request_id, seconds=time.perf_counter() - start,
                           errorType=type(error).__name__, stage=stage, diagnostic=diagnostic,
                           evidenceScope='parsed_public_deltas_only', deltas=redact_secret(fragments, secret),
                           capturedChars=chars, truncated=bool(omitted), omittedDeltas=omitted)
            except Exception as capture_error:
                logging.getLogger(__name__).warning('Failure evidence unavailable: %s', type(capture_error).__name__)
            raise
        finally:
            REQUEST_ID.reset(token)
    return observed_chat


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--trace', required=True)
    parser.add_argument('service', choices=['api', 'worker'])
    args = parser.parse_args()
    metadata, private = load_environment(args.metadata)
    if metadata['suite'] != 'spec081':
        raise RuntimeError('Owned Spec081 environment required')
    os.environ.update(private['environment'])
    source = Path(args.source).resolve()
    sys.path[:0] = [str(source / 'apps/server'), str(source / 'packages/voiceprint-engine/src')]
    trace = module('latency_trace', ROOT / 'eval/web/agent-audit/trace.py')
    trace.install(args.trace)
    import httpx
    original_send = httpx.AsyncClient.send

    async def observed_send(self, request, **kwargs):
        try:
            payload = json.loads(request.content)
        except (ValueError, UnicodeDecodeError, httpx.RequestNotRead):
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get('messages'), list):
            # JSON string avoids the generic observer redacting synthetic tool
            # fields named authorization, which are part of the actual schema.
            trace.emit('wire_input', requestId=REQUEST_ID.get(), payloadJson=json.dumps(payload, ensure_ascii=False),
                       sha256=hashlib.sha256(request.content).hexdigest())
        return await original_send(self, request, **kwargs)
    httpx.AsyncClient.send = observed_send
    from app.integrations.models import chat
    original_chat = chat._chat

    chat._chat = observed_chat_call(original_chat, trace)
    from app.agent import harness
    original_build = harness.build_graph

    def observed_build(*args, **kwargs):
        start = time.perf_counter()
        cpu = time.process_time()
        try:
            return original_build(*args, **kwargs)
        finally:
            trace.emit('build_graph', seconds=time.perf_counter() - start,
                       cpuSeconds=time.process_time() - cpu)
    harness.build_graph = observed_build
    from app.agent.context import compaction
    original_schemas = compaction.tool_schemas

    def observed_schemas(tools):
        start = time.perf_counter()
        value = original_schemas(tools)
        trace.emit('tool_schema_conversion', seconds=time.perf_counter() - start, count=len(tools))
        return value
    compaction.tool_schemas = observed_schemas
    trace.emit('latency_runtime_start', source=str(source), commit=metadata['commit'],
               service=args.service, schema=metadata['schema'])
    logging.basicConfig(level=logging.INFO)
    if args.service == 'api':
        import uvicorn
        uvicorn.run('app.main:app', host='127.0.0.1', port=int(metadata['apiOrigin'].rsplit(':', 1)[1]), access_log=False)
    else:
        launch = module('latency_launch', ROOT / 'eval/web/agent-audit/launch.py')
        launch.audit_trace = trace
        asyncio.run(launch.worker(metadata['schema']))


if __name__ == '__main__':
    main()
