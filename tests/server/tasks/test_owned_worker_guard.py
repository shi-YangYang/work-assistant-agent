"""Probe guard rejects broad suite prefixes and mismatched owned runs."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def probe():
    path = Path(__file__).resolve().parents[1] / 'probes/full_system_worker_probe.py'
    spec = importlib.util.spec_from_file_location('worker_guard_probe', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('url', [
    'postgresql://127.0.0.1/production?options=-csearch_path%3Dspec044_recovery_aaaaaaaaaaaa',
    'postgresql://example.com/paa_company_test?options=-csearch_path%3Dspec044_recovery_aaaaaaaaaaaa',
    'postgresql://127.0.0.1/paa_company_test?options=-csearch_path%3Dspec044_recovery_bbbbbbbbbbbb',
    'postgresql://127.0.0.1/paa_company_test?options=-csearch_path%3Dspec068_recovery_aaaaaaaaaaaa',
    'postgresql://127.0.0.1/paa_company_test?options=-csearch_path%3Dspec044_anything',
])
def test_probe_rejects_undeclared_or_mismatched_targets(monkeypatch, url):
    monkeypatch.setenv('SPEC044_RUN_ID', 'a' * 32)
    monkeypatch.delenv('PAA_AGENT_FAULT_ENVIRONMENT', raising=False)
    with pytest.raises(SystemExit):
        probe().checked_target(SimpleNamespace(database_url=url))


def test_probe_legacy_run_requires_exact_schema_and_run(monkeypatch):
    monkeypatch.setenv('SPEC044_RUN_ID', 'a' * 32)
    monkeypatch.delenv('PAA_AGENT_FAULT_ENVIRONMENT', raising=False)
    settings = SimpleNamespace(database_url='postgresql://127.0.0.1/paa_company_test?options=-csearch_path%3Dspec054_recovery_aaaaaaaaaaaa')
    assert probe().checked_target(settings).database == 'paa_company_test'
    monkeypatch.setenv('SPEC044_RUN_ID', 'b' * 32)
    with pytest.raises(SystemExit):
        probe().checked_target(settings)


def test_declared_probe_checks_exact_run_and_database(monkeypatch):
    import os
    from dataclasses import replace
    from sqlalchemy.engine import make_url
    from app.core.config import Settings
    if not os.getenv('PAA_AGENT_FAULT_ENVIRONMENT'):
        pytest.skip('Exact owned manifest required for probe guard verification')
    module, settings = probe(), Settings()
    assert module.checked_target(settings).database == 'paa_company_test'
    original = os.environ['SPEC044_RUN_ID']
    # Matching schema prefixes cannot stand in for the full ownership marker.
    monkeypatch.setenv('SPEC044_RUN_ID', original[:12] + ('a' if original[12] != 'a' else 'b') + original[13:])
    with pytest.raises(SystemExit, match='does not match'):
        module.checked_target(settings)
    monkeypatch.setenv('SPEC044_RUN_ID', original)
    mismatched = make_url(settings.database_url).update_query_dict({'options': '-csearch_path=spec068_recovery_' + 'f' * 12})
    with pytest.raises(RuntimeError, match='does not match'):
        module.checked_target(replace(settings, database_url=mismatched.render_as_string(hide_password=False)))
