"""Ownership-checked Spec080 runtime and passive model-input observations."""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from environment import load_environment

p = argparse.ArgumentParser()
p.add_argument('--metadata', required=True)
p.add_argument('--trace', required=True)
p.add_argument('service', choices=['api', 'worker'])
a = p.parse_args()
metadata, private = load_environment(a.metadata)
assert metadata['suite'] == 'spec080'
os.environ.update(private['environment'])
os.environ['AGENT_AUDIT_PLAN_INPUT'] = 'synthetic'
# Use the existing passive observer with full synthetic transport evidence.
# Its suite gate only affects recording; the actual environment identity stays Spec080.
spec = importlib.util.spec_from_file_location('spec080_trace', HERE.parents[3] / 'eval/web/agent-audit/trace.py')
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)
original_suite = os.environ['ACCEPTANCE_SUITE']
os.environ['ACCEPTANCE_SUITE'] = 'spec074'
trace.install(a.trace)
os.environ['ACCEPTANCE_SUITE'] = original_suite
# The request wrapper's gate is evaluated at runtime; add synthetic input explicitly.
from app.integrations.models import chat
original = chat._chat
async def observed(settings, config, key, messages, **kwargs):
    trace.emit('spec080_provider_input', config={k: config.get(k) for k in ('model', 'parameters', 'protocol')}, messages=messages,
               tools=kwargs.get('tools'), toolChoice=kwargs.get('tool_choice'), maxTokens=kwargs.get('max_tokens', 4000))
    result = await original(settings, config, key, messages, **kwargs)
    trace.emit('spec080_provider_output', response={'choices': [{'message': {k: c.get('message', {}).get(k) for k in ('role','content','tool_calls')}, 'finish_reason': c.get('finish_reason')} for c in result.get('choices',[])]})
    return result
chat._chat = observed
trace.emit('spec080_runtime_start', service=a.service, schema=metadata['schema'], commit=metadata['commit'])
if a.service == 'api':
    import uvicorn
    uvicorn.run('app.main:app', host='127.0.0.1', port=int(metadata['apiOrigin'].rsplit(':',1)[1]), access_log=False)
else:
    spec = importlib.util.spec_from_file_location('spec080_launch', HERE.parents[3] / 'eval/web/agent-audit/launch.py')
    launch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launch)
    launch.audit_trace = trace
    asyncio.run(launch.worker(metadata['schema']))
