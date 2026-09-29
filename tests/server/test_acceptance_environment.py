"""Safety checks for the opt-in acceptance launcher and destructive cleanup."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


path = Path(__file__).resolve().parents[2] / 'scripts/company/web-acceptance/environment.py'
spec = importlib.util.spec_from_file_location('acceptance_environment', path)
environment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(environment)


@pytest.mark.parametrize('url', [
    'postgresql://test@127.0.0.1/paa_company',
    'postgresql://test@remote.example/paa_company_test',
    'postgresql://test@127.0.0.1/postgres',
])
def test_acceptance_refuses_nonlocal_or_non_test_databases(url):
    with pytest.raises(RuntimeError, match='local dedicated paa_company_test'):
        environment.checked_url(url)


def manifest(tmp_path, *, mode=0o600, schema='spec044_web_0123456789ab'):
    secret = tmp_path / 'private.json'
    secret.write_text(json.dumps({'environment': {'DATABASE_URL': 'postgresql://test@127.0.0.1/paa_company_test?options=-csearch_path%3D' + schema}}))
    secret.chmod(mode)
    public = tmp_path / 'manifest.json'
    public.write_text(json.dumps({'schema': schema, 'secretFile': str(secret), 'runId': 'known-run'}))
    return public


def test_acceptance_refuses_world_readable_private_environment(tmp_path, monkeypatch):
    connect = MagicMock()
    monkeypatch.setattr(environment, 'create_engine', connect)
    with pytest.raises(RuntimeError, match='0600'):
        environment.load_environment(manifest(tmp_path, mode=0o644))
    connect.assert_not_called()


def test_acceptance_refuses_unowned_schema_before_running_or_dropping(tmp_path, monkeypatch):
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.scalar.return_value = 'spec044:another-run'
    monkeypatch.setattr(environment, 'create_engine', lambda _: engine)
    with pytest.raises(RuntimeError, match='Ownership marker mismatch'):
        environment.load_environment(manifest(tmp_path))
    engine.begin.assert_not_called()
    engine.dispose.assert_called_once()


def test_acceptance_refuses_unscoped_public_schema(tmp_path, monkeypatch):
    connect = MagicMock()
    monkeypatch.setattr(environment, 'create_engine', connect)
    with pytest.raises(RuntimeError, match='Unexpected acceptance schema'):
        environment.load_environment(manifest(tmp_path, schema='public'))
    connect.assert_not_called()


def test_cleanup_validates_resource_paths_before_dropping_schema(tmp_path, monkeypatch):
    from types import SimpleNamespace
    connect = MagicMock()
    monkeypatch.setattr(environment, 'create_engine', connect)
    monkeypatch.setattr(environment, 'load_environment', lambda _: ({'schema': 'spec044_web_0123456789ab', 'privateDirectory': str(tmp_path / 'unowned'), 'credentialsFile': str(tmp_path / 'credentials.json')}, {'environment': {}}))
    with pytest.raises(RuntimeError, match='unexpected private directory'):
        environment.cleanup(SimpleNamespace(metadata=str(tmp_path / 'manifest.json')))
    connect.assert_not_called()


@pytest.mark.parametrize('mismatch', ['project', 'service', 'port', 'volume', 'ordinary-port', None])
def test_sandbox_target_guard_checks_disposable_ownership_before_control_actions(monkeypatch, mismatch):
    from types import SimpleNamespace
    sandbox_path = Path(__file__).resolve().parents[1] / 'sandbox'
    monkeypatch.syspath_prepend(str(sandbox_path))
    import recovery_execution
    monkeypatch.setenv('SPEC042_SANDBOX_TEST', '1')
    monkeypatch.setenv('SANDBOX_TEST_COMPOSE_PROJECT', 'noria-spec044')
    monkeypatch.setenv('SANDBOX_TEST_CONTROL_CONTAINER', 'noria-spec044-control')
    monkeypatch.setenv('SANDBOX_TEST_URL', 'http://127.0.0.1:8018')
    container = {'Id': 'controlled-container-id', 'Config': {'Labels': {'com.docker.compose.project': 'noria-spec044', 'com.docker.compose.service': 'control'}}, 'HostConfig': {'PortBindings': {'8010/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8018'}]}}, 'Mounts': [{'Type': 'volume', 'Destination': '/state', 'Name': 'noria-spec044_control-state'}, {'Type': 'volume', 'Destination': '/var/run', 'Name': 'noria-spec044_engine-socket'}]}
    if mismatch in ('project', 'service'):
        container['Config']['Labels']['com.docker.compose.' + mismatch] = 'ordinary-user-service'
    elif mismatch == 'port':
        container['HostConfig']['PortBindings']['8010/tcp'][0]['HostPort'] = '8011'
    elif mismatch == 'volume':
        container['Mounts'][0]['Name'] = 'ordinary-data'
    elif mismatch == 'ordinary-port':
        monkeypatch.setenv('SANDBOX_TEST_URL', 'http://127.0.0.1:8011')
    command = MagicMock(return_value=SimpleNamespace(stdout=json.dumps([container])))
    monkeypatch.setattr(recovery_execution.subprocess, 'run', command)
    if mismatch:
        with pytest.raises(RuntimeError):
            recovery_execution.isolated_control()
    else:
        assert recovery_execution.isolated_control() == 'controlled-container-id'
    assert all(call.args[0][:2] == ['docker', 'inspect'] for call in command.call_args_list)
    if mismatch == 'ordinary-port':
        command.assert_not_called()
