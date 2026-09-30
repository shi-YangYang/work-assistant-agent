"""Freeze registered operations/tools and candidate test mappings (not coverage)."""
import argparse
import ast
import hashlib
import inspect
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'apps/server'), str(ROOT / 'packages/voiceprint-engine/src')]

MATRIX = {
    'auth': ['W01', 'W02', 'D02'], 'conversations': ['W04', 'W09', 'D01', 'D05'],
    'messages': ['W05', 'W07', 'W08', 'D04', 'D07'], 'attachments': ['W06', 'D01', 'D12', 'D13'],
    'tasks': ['W08', 'D08', 'D09', 'D10'], 'jobs': ['W08', 'D08', 'D09', 'D10'],
    'work-items': ['W12', 'D04', 'D05'], 'progress-drafts': ['W07', 'W12', 'D04'],
    'reports': ['W13', 'D04', 'D05'], 'team': ['W14', 'D01'], 'members': ['W15', 'D11'],
    'settings': ['W16', 'W18'], 'voiceprints': ['W17', 'D01'], 'support': ['W18'],
    'feedback': ['W18'], 'support-feedback': ['W18'], 'notifications': ['W18'],
    'desktop': ['W17', 'D01', 'D02'], 'health': ['W03'],
    'uploads': ['W06', 'D01', 'D12', 'D13'], 'business-sources': ['W07', 'W14', 'D01'],
    'report-obligations': ['W13', 'W18'], 'business-actions': ['W07', 'D04', 'D05'],
    'interactions': ['W07', 'D04'], 'deliverables': ['W11', 'D01', 'D15'],
}


def main(output):
    from app.main import create_app
    from app.agent.tools.registry import BUSINESS_TOOLS
    from app.agent.tools.team import TEAM_TOOLS
    from app.agent.prompts.policies import ALLOWED_TOOLS, TEAM_TOOL_NAMES
    schema = create_app().openapi()
    test_sources = {str(path.relative_to(ROOT)): path.read_text() for path in (ROOT / 'tests/server').glob('test_*.py')}
    operations = []
    for path, methods in sorted(schema['paths'].items()):
        for method, operation in sorted(methods.items()):
            prefix = path.split('/')[3] if path.startswith('/api/v1/') else 'health'
            constant = path.split('{')[0].rstrip('/')
            candidates = [name for name, source in test_sources.items() if constant in source]
            operations.append({'id': method.upper() + ' ' + path, 'operationId': operation['operationId'], 'matrix': MATRIX.get(prefix, ['UNMAPPED']),
                               'candidateTestFiles': candidates, 'coverageStatus': 'UNTRACED',
                               'note': 'Source references are discovery aids; only executed assertions establish coverage.',
                               'parameters': operation.get('parameters', []), 'responses': sorted(operation.get('responses', {}))})
    tools = []
    for tool in [*BUSINESS_TOOLS, *TEAM_TOOLS]:
        source = inspect.getsourcefile(tool.coroutine or tool.func)
        tools.append({'name': tool.name, 'roles': ['admin'] if tool.name in TEAM_TOOL_NAMES else ['employee', 'admin'], 'source': str(Path(source).relative_to(ROOT)), 'args': {key: str(field.annotation) for key, field in tool.args_schema.model_fields.items() if key != 'runtime'} if tool.args_schema else {}, 'coverageStatus': 'UNTRACED'})
    for name in sorted((ALLOWED_TOOLS | TEAM_TOOL_NAMES) - {tool['name'] for tool in tools}):
        tools.append({'name': name, 'source': 'harness filesystem middleware', 'coverageStatus': 'UNTRACED'})
    jobs = []
    for path in (ROOT / 'apps/server/app').rglob('*.py'):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and ((isinstance(node.func, ast.Name) and node.func.id == 'Job') or (isinstance(node.func, ast.Attribute) and node.func.attr == 'Job')):
                for keyword in node.keywords:
                    if keyword.arg == 'kind':
                        jobs.append({'kind': ast.unparse(keyword.value), 'source': str(path.relative_to(ROOT)), 'line': node.lineno, 'coverageStatus': 'UNTRACED'})
    # Dynamic HTTP action dispatch is a separate branch inventory.
    branches = []
    for path in (ROOT / 'apps/server/app/modules').rglob('*.py'):
        source = path.read_text()
        for match in re.finditer(r"(?:action|operation)\s*(?:==|in|not in)\s*([^\n]+)", source):
            branches.append({'source': str(path.relative_to(ROOT)), 'line': source[:match.start()].count('\n') + 1, 'predicate': match.group(0), 'coverageStatus': 'UNTRACED'})
    result = {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'openapiSha256': hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(),
              'operations': operations, 'tools': tools, 'jobConstructors': jobs, 'dynamicBranches': branches,
              'backgroundLoops': [
                  {'name': 'worker slots', 'source': 'apps/server/app/tasks/runtime/runner.py', 'tasks': ['message', 'report', 'document']},
                  {'name': 'voiceprint extraction queue', 'source': 'apps/server/app/tasks/processing/voiceprints.py', 'persistedModel': 'Voiceprint'},
                  {'name': 'report scheduling and cleanup', 'source': 'apps/server/app/tasks/maintenance/maintenance.py', 'functions': ['schedule_once', 'maintenance']},
                  {'name': 'sandbox execution and retirement', 'source': 'apps/server/app/modules/executions/service.py', 'persistedModel': 'SandboxExecution'},
              ],
              'summary': {'operations': len(operations), 'tools': len(tools), 'distinctJobKinds': sorted({job['kind'] for job in jobs})}}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result['summary'], ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='artifacts/spec044/server/inventory.json')
    main(parser.parse_args().output)
