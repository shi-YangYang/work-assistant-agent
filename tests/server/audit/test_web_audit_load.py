"""Opt-in bounded 30/50 synthetic-user extension of the existing mixed-task probe."""
import asyncio
import importlib.util
import os
from pathlib import Path
import resource
import time
import pytest
probe_spec = importlib.util.spec_from_file_location('web_audit_owned_probe', Path(__file__).with_name('test_agent_audit_faults.py'))
probe = importlib.util.module_from_spec(probe_spec)
probe_spec.loader.exec_module(probe)
mixed_users = probe.test_isolated_users_mixed_tasks_do_not_cross_outputs
owned_fault_environment = probe.owned_fault_environment
from faults import evidence

PREVIOUS_FAILED = False


@pytest.mark.asyncio
@pytest.mark.parametrize('concurrency', [30, 50])
async def test_large_owned_mixed_tasks(owned_fault_environment, setup, concurrency):
    global PREVIOUS_FAILED
    if not os.getenv('PAA_WEB_AUDIT_LOAD'):
        pytest.skip('Explicit full Web audit load only')
    if PREVIOUS_FAILED:
        pytest.skip('Stopped escalation after previous load failure')
    started = time.monotonic()
    cpu = time.process_time()
    status = 'PASS'
    try:
        async with asyncio.timeout(60):
            await mixed_users(owned_fault_environment, setup, concurrency)
    except BaseException:
        PREVIOUS_FAILED = True
        status = 'FAIL'
        raise
    finally:
        evidence(f'load-{concurrency}-resources', {
            'status': status, 'seconds': time.monotonic() - started,
            'cpuSeconds': time.process_time() - cpu,
            'maxRssPlatformUnits': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'poolCheckedOutAfter': setup[1].kw['bind'].pool.checkedout(),
            'scope': 'in-process ASGI real DB controlled model; serial logins then concurrent jobs',
        })
