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
    'auth': ['W01', 'W02', 'W16', 'D12'], 'conversations': ['W04', 'W09', 'D01', 'D05'],
    'messages': ['W05', 'W07', 'W08', 'W10', 'D01', 'D07'], 'attachments': ['W06', 'W10', 'D08', 'D11'],
    'tasks': ['W07', 'D03', 'D05'], 'jobs': ['W07', 'W09', 'D03', 'D05'],
    'work-items': ['W11', 'W12', 'D04'], 'progress-drafts': ['W07', 'W12', 'D04'],
    'reports': ['W13', 'D03', 'D04'], 'team': ['W14'], 'members': ['W15', 'D11'],
    'settings': ['W16', 'W17', 'W18', 'W19', 'W20', 'W22'], 'voiceprints': ['W21', 'D08'],
    'support': ['W23'], 'feedback': ['W23'], 'support-feedback': ['W23'], 'notifications': ['W03', 'W13'],
    'desktop': ['W02'], 'health': ['W03', 'D06'], 'uploads': ['W06', 'D08'],
    'business-sources': ['W10', 'W14'], 'report-obligations': ['W13', 'W18'],
    'business-actions': ['W07', 'D03', 'D04'], 'interactions': ['W07', 'W08', 'D03'],
    'deliverables': ['W10', 'D11'],
}


ASSISTANT_MATRIX = {
    'execution-settings': ['W08', 'A25', 'D04', 'D12'],
    'memory': ['W17', 'A22', 'A23', 'D04', 'D12'],
    'reasoning-settings': ['W08', 'W19', 'A25', 'A28', 'D04', 'D12'],
}


def matrix_for(path):
    parts = path.split('/')
    prefix = parts[3] if path.startswith('/api/v1/') else 'health'
    if prefix == 'assistant':
        return ASSISTANT_MATRIX.get(parts[4] if len(parts) > 4 else '', ['UNMAPPED'])
    return MATRIX.get(prefix, ['UNMAPPED'])


def test_sources(root):
    """Include extracted fixtures as discovery evidence, never as collected tests."""
    def source(path, seen):
        if path in seen or not path.is_file():
            return ''
        seen.add(path)
        text = path.read_text()
        dependencies = []
        for node in ast.walk(ast.parse(text)):
            names = [node.module] if isinstance(node, ast.ImportFrom) else [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
            for name in names:
                if name and name.startswith('_support.'):
                    dependencies.append(source(root / (name.replace('.', '/') + '.py'), seen))
        return '\n'.join([text, *dependencies])

    return {str(path.relative_to(ROOT)): source(path, set()) for path in sorted(root.rglob('test_*.py'))}


def main(output):
    from app.main import create_app
    from app.agent.tools.registry import BUSINESS_TOOLS
    from app.agent.tools.business.team import TEAM_TOOLS
    from app.agent.prompts.policies import ALLOWED_TOOLS, TEAM_TOOL_NAMES
    schema = create_app().openapi()
    sources = test_sources(ROOT / 'tests/server')
    operations = []
    for path, methods in sorted(schema['paths'].items()):
        for method, operation in sorted(methods.items()):
            constant = path.split('{')[0].rstrip('/')
            candidates = [name for name, source in sources.items() if constant in source]
            operations.append({'id': method.upper() + ' ' + path, 'operationId': operation['operationId'], 'matrix': matrix_for(path),
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
