"""Executable boundaries for the shared backend's module ownership."""
import ast
import httpx
import pytest
from dataclasses import replace
from importlib.util import resolve_name
from paa_server.api import create_app
from paa_server.core.config import Settings
from paa_server.db.registry import metadata
from pathlib import Path



ROOT = Path(__file__).resolve().parents[2] / 'apps/server/src/paa_server'


def module_dependencies(root=ROOT):
    modules = {}
    for path in root.rglob('*.py'):
        relative = path.relative_to(root)
        if 'migrations' in relative.parts:
            continue
        parts = relative.as_posix().removesuffix('.py').split('/')
        if parts[-1] == '__init__':
            parts.pop()
        modules['.'.join(['paa_server', *parts])] = path

    graph = {}
    for name, path in modules.items():
        package = name if path.name == '__init__.py' else name.rpartition('.')[0]
        targets = set()
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.ImportFrom):
                target = resolve_name('.' * node.level + (node.module or ''), package)
                for alias in node.names:
                    child = target + '.' + alias.name
                    # A known submodule is an edge; a function/class belongs to its source module.
                    targets.add(child if child in modules else target)
            elif isinstance(node, ast.Import):
                targets.update(alias.name for alias in node.names)
        if path.name == '__init__.py':
            # Importing the package's own attributes does not create a module cycle.
            targets.discard(name)
        graph[name] = targets & modules.keys()
    return graph


def assert_dependency_boundaries(graph):
    visiting, done = [], set()

    def in_package(name, *packages):
        return any(name == package or name.startswith(package + '.') for package in packages)

    def visit(name):
        assert name not in visiting, 'Circular dependency: ' + ' -> '.join([*visiting, name])
        if name in done:
            return
        visiting.append(name)
        for target in graph.get(name, ()):
            visit(target)
        visiting.pop()
        done.add(name)

    for name, targets in graph.items():
        visit(name)
        assert not targets & {'paa_server.api', 'paa_server.worker', 'paa_server.cli'}, name
        if in_package(name, 'paa_server.core', 'paa_server.integrations') or name in ('paa_server.db.base', 'paa_server.tasks.context'):
            assert not any(in_package(target, 'paa_server.agent', 'paa_server.modules', 'paa_server.http.routers') for target in targets), name
        if in_package(name, 'paa_server.modules') and not name.endswith(('_router', '.router')):
            assert not any(target.endswith(('_router', '.router', '.harness')) or target == 'paa_server.http.dependencies' for target in targets), name
        if name == 'paa_server.tasks.lease':
            assert not targets & {'paa_server.tasks.handlers', 'paa_server.tasks.runner', 'paa_server.agent.harness'}, name


def test_dependencies_are_acyclic_and_do_not_import_entrypoints():
    assert_dependency_boundaries(module_dependencies())


def source_dependencies(tmp_path, sources):
    for relative, source in sources.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding='utf-8')
    return module_dependencies(tmp_path)


@pytest.mark.parametrize(('source', 'statement', 'target'), [
    ('core/config.py', 'import paa_server.api as entry', 'api.py'),
    ('core/config.py', 'from paa_server import api as entry', 'api.py'),
    ('modules/work/commands.py', 'from paa_server.agent import harness', 'agent/harness.py'),
    ('tasks/lease.py', 'from paa_server.tasks import runner', 'tasks/runner.py'),
    ('tasks/lease.py', 'from . import runner as run', 'tasks/runner.py'),
    ('core/__init__.py', 'from ..agent import harness', 'agent/harness.py'),
    ('__init__.py', 'from . import api', 'api.py'),
])
def test_import_variants_cannot_bypass_boundaries(tmp_path, source, statement, target):
    graph = source_dependencies(tmp_path, {source: statement, target: ''})
    with pytest.raises(AssertionError, match='^paa_server'):
        assert_dependency_boundaries(graph)


@pytest.mark.parametrize('sources', [
    {
        'helpers/__init__.py': 'from . import first',
        'helpers/first.py': 'from paa_server.helpers import second',
        'helpers/second.py': 'from . import first',
    },
    {
        'helpers/__init__.py': 'from .worker import run\nexported = 1',
        'helpers/worker.py': 'from . import exported\ndef run(): pass',
    },
])
def test_submodule_and_package_cycles_are_detected(tmp_path, sources):
    with pytest.raises(AssertionError, match='Circular dependency:'):
        assert_dependency_boundaries(source_dependencies(tmp_path, sources))


def test_symbol_imports_and_package_reexports_do_not_create_false_dependencies(tmp_path):
    graph = source_dependencies(tmp_path, {
        '__init__.py': 'from .helpers import api',
        'helpers/__init__.py': 'from . import operations\nfrom .operations import api',
        'helpers/operations.py': 'def api(): pass',
        'core/config.py': 'from ..helpers import api\nfrom paa_server.helpers import operations as ops',
    })
    assert graph == {
        'paa_server': {'paa_server.helpers'},
        'paa_server.helpers': {'paa_server.helpers.operations'},
        'paa_server.helpers.operations': set(),
        'paa_server.core.config': {'paa_server.helpers', 'paa_server.helpers.operations'},
    }
    assert_dependency_boundaries(graph)


def test_registry_registers_all_models_and_resolves_cross_domain_foreign_keys():
    tables = metadata.sorted_tables
    assert {'company', 'company_member', 'company_job', 'company_message', 'company_work_item', 'company_report', 'company_voiceprint'} <= {table.name for table in tables}
    for table in tables:
        for foreign_key in table.foreign_keys:
            assert foreign_key.column.table in tables


@pytest.mark.asyncio
async def test_two_applications_keep_request_dependencies_isolated(tmp_path):
    settings = Settings()
    first = create_app(replace(settings, web_origin='http://first.test', media_dir=tmp_path / 'first'))
    second = create_app(replace(settings, web_origin='http://second.test', media_dir=tmp_path / 'second'))
    async with first.router.lifespan_context(first), second.router.lifespan_context(second):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=first), base_url='http://first.test') as a, httpx.AsyncClient(transport=httpx.ASGITransport(app=second), base_url='http://second.test') as b:
            for client, origin in ((a, 'http://first.test'), (b, 'http://second.test'), (a, 'http://first.test')):
                response = await client.get('/api/v1/desktop/info')
                assert response.status_code == 200
                assert response.json() == {'protocolVersion': 1, 'webOrigin': origin}
                rejected = await client.post('/api/v1/auth/login', headers={'Origin': 'http://wrong.test'}, json={})
                assert rejected.status_code == 403 and rejected.json()['error']['code'] == 'origin_rejected'
