"""Read-only inventory and isolated fixed Agent test runner for Spec 059."""
import argparse
import ast
import functools
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'apps/server'), str(ROOT / 'scripts/company/web-acceptance')]
EXCLUDED = {
    'test_acceptance_agent_http', 'test_acceptance_environment', 'test_admin_scope_coverage',
    'test_auth_concurrency', 'test_company', 'test_config_paths', 'test_core_scope_coverage',
    'test_desktop_voiceprints', 'test_dingtalk', 'test_feedback_connections',
    'test_inactive_member_cleanup', 'test_management', 'test_member_deletion',
    'test_member_management', 'test_model_service_http_coverage', 'test_model_services',
    'test_password_schema_migration', 'test_session_lifetime', 'test_support_feedback',
    'test_voiceprint_lifecycle', 'test_assistant_memory_migration',
    'test_assistant_reasoning_migration', 'test_builtin_execution_migration',
    'test_execution_settings_migration', 'test_api_coverage_gaps',
    'test_request_contract_coverage', 'test_full_system_acceptance',
    'test_infrastructure_failures', 'test_process_worker_recovery', 'test_sandbox_runtime',
    'test_agent_audit', 'test_agent_audit_faults',
}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def inventory():
    from langchain_core.utils.function_calling import convert_to_openai_tool
    from app.agent.tools.registry import BUSINESS_TOOLS
    from app.agent.tools.business.team import TEAM_TOOLS
    from app.agent.tools.catalog import available_groups, allowed_tools
    from app.agent.prompts.policies import EXCLUDED_TOOLS
    from app.agent.tools.business.actions import execute_business_action
    from app.main import create_app
    from app.core.config import Settings
    registered = {tool.name: tool for tool in BUSINESS_TOOLS + TEAM_TOOLS}
    tools = []
    for name in sorted(set(registered) | {'read_file'}):
        entry = registered.get(name)
        source = Path(entry.coroutine.__code__.co_filename) if entry else None
        tools.append({'name': name, 'source': str(source.relative_to(ROOT)) if source else 'deepagents StateBackend read_file',
                      'inputSchema': convert_to_openai_tool(entry)['function']['parameters'] if entry else None,
                      'compatibilityOnly': name == 'finish_task'})
    variants = []
    for role in ('employee', 'admin'):
        for sandbox in (False, True):
            context = SimpleNamespace(role=role, settings=SimpleNamespace(sandbox_url='isolated' if sandbox else '', sandbox_token='configured' if sandbox else ''))
            variants.append({'role': role, 'sandbox': sandbox, 'initial': ['load_tools'],
                             'allowed': sorted(allowed_tools(context)),
                             'groups': {key: sorted(value) for key, value in available_groups(context).items()}})
    app = create_app(Settings())
    paths = app.openapi()['paths']
    prefixes = ('/api/v1/messages', '/api/v1/conversations', '/api/v1/jobs', '/api/v1/assistant',
                '/api/v1/work-items', '/api/v1/operations', '/api/v1/progress', '/api/v1/reports',
                '/api/v1/uploads', '/api/v1/documents', '/api/v1/deliverables', '/api/v1/executions', '/api/v1/team',
                '/api/v1/business-actions', '/api/v1/business-sources', '/api/v1/interactions')
    apis = [{'method': method.upper(), 'path': path, 'operationId': definition.get('operationId')}
            for path, methods in paths.items() if path.startswith(prefixes)
            for method, definition in methods.items() if method in ('get', 'post', 'put', 'patch', 'delete')]
    source_files = sorted((ROOT / 'apps/server/app/tasks').rglob('*.py'))
    states = {}
    for path in source_files:
        tree = ast.parse(path.read_text())
        literals = sorted({node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                           and isinstance(node.value, str) and node.value in {
                               'queued', 'running', 'succeeded', 'failed', 'cancelled', 'needs_input',
                               'awaiting_retry', 'retry_wait', 'completed', 'partial', 'blocked', 'waiting'}})
        if literals:
            states[str(path.relative_to(ROOT))] = literals
    return {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'tools': tools, 'variants': variants, 'excludedFrameworkTools': sorted(EXCLUDED_TOOLS),
            'businessActions': convert_to_openai_tool(execute_business_action)['function']['parameters']['properties']['action']['enum'],
            'apis': apis, 'taskStateSourceInventory': states}


def selected_tests():
    return [str(path.relative_to(ROOT)) for path in sorted((ROOT / 'tests/server').rglob('test_*.py')) if path.stem not in EXCLUDED]


def run(args):
    from environment import load_environment
    metadata, private = load_environment(args.metadata)
    if metadata.get('suite') not in ('spec059', 'spec060', 'spec068'):
        raise RuntimeError('Supported owned audit environment required')
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = inventory()
    files = args.cases or selected_tests()
    manifest['selectedTestFiles'] = files
    manifest['excludedTestFiles'] = sorted(EXCLUDED)
    manifest['schema'] = metadata['schema']
    save(output / 'inventory.json', manifest)
    env = {**os.environ, **private['environment'], 'SPEC059_FIXED_EVIDENCE': str(output),
           'PAA_REPLY_STREAM_REDIS_URL': args.redis_url or private['environment'].get('PAA_REPLY_STREAM_REDIS_URL', ''),
           'PAA_REPLY_STREAM_TEST_URL': args.redis_url or private['environment'].get('PAA_REPLY_STREAM_TEST_URL', ''),
           'PAA_AGENT_FAULT_ENVIRONMENT': str(Path(args.metadata).resolve()),
           'PYTHONPATH': os.pathsep.join([str(Path(__file__).parent), private['environment']['PYTHONPATH']])}
    env = {key: value for key, value in env.items() if key.lower() not in ('http_proxy', 'https_proxy', 'all_proxy')}
    command = [sys.executable, '-m', 'pytest', '-q', '-p', 'fixed', '--tb=short',
               '--junitxml=' + str(output / 'fixed.xml'), *files]
    save(output / 'command.json', {'command': command, 'cwd': str(ROOT), 'schema': metadata['schema'],
                                  'appCodeChanged': False, 'startedAt': time.time()})
    started = time.monotonic()
    with (output / 'fixed.log').open('w') as log:
        status = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    tree = ET.parse(output / 'fixed.xml')
    results = []
    for case in tree.findall('.//testcase'):
        failure = case.find('failure')
        error = case.find('error')
        skipped = case.find('skipped')
        detail = failure if failure is not None else error
        results.append({'id': case.attrib['classname'] + '::' + case.attrib['name'],
                        'status': 'FAIL' if detail is not None else 'BLOCKED' if skipped is not None else 'PASS',
                        'seconds': float(case.attrib.get('time', 0)),
                        'detail': detail.text if detail is not None else skipped.attrib.get('message') if skipped is not None else None})
    save(output / 'results.json', {'exitCode': status, 'seconds': round(time.monotonic() - started, 2), 'cases': results})
    save(output / 'issues.json', [result for result in results if result['status'] != 'PASS'])
    print(json.dumps({'exitCode': status, 'counts': {state: sum(case['status'] == state for case in results)
                                                  for state in ('PASS', 'FAIL', 'BLOCKED')}, 'output': str(output)}), flush=True)
    return status


# Pytest-only observation: wrappers preserve each registered tool's arguments,
# result and exception. No dispatch, authorization or retry decision is changed.
CURRENT = None
EVENTS = []


def pytest_sessionstart(session):
    if not os.getenv('SPEC059_FIXED_EVIDENCE'):
        return
    from app.agent.tools.registry import BUSINESS_TOOLS
    from app.agent.tools.business.team import TEAM_TOOLS
    for tool in BUSINESS_TOOLS + TEAM_TOOLS:
        original = tool.coroutine
        def instrument(original, name):
            @functools.wraps(original)
            async def call(*args, **kwargs):
                started = time.monotonic()
                row = {'test': CURRENT, 'tool': name, 'phase': 'tool_body', 'outcome': 'returned'}
                try:
                    result = await original(*args, **kwargs)
                    if isinstance(result, str):
                        row['resultDigest'] = hashlib.sha256(result.encode()).hexdigest()
                        try:
                            parsed = json.loads(result)
                            row['state'] = parsed.get('state') if isinstance(parsed, dict) else None
                        except (TypeError, ValueError):
                            pass
                    return result
                except BaseException as error:
                    row['outcome'] = type(error).__name__
                    raise
                finally:
                    row['seconds'] = round(time.monotonic() - started, 4)
                    EVENTS.append(row)
            return call
        tool.coroutine = instrument(original, tool.name)


def pytest_runtest_setup(item):
    global CURRENT
    CURRENT = item.nodeid


def pytest_sessionfinish(session, exitstatus):
    if os.getenv('SPEC059_FIXED_EVIDENCE'):
        save(Path(os.environ['SPEC059_FIXED_EVIDENCE']) / 'tool-execution-observation.json', EVENTS)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--redis-url', default='')
    parser.add_argument('--cases', nargs='+')
    raise SystemExit(run(parser.parse_args()))
