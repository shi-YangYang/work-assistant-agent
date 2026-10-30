"""Explicit local self checks. Deliberately outside pytest discovery."""
import tempfile
from pathlib import Path
from .contracts import catalog
from .evidence import write, read, seal, verify
from .grading import aggregate, overall, parse_semantic, deterministic
from .report import render


def check():
    catalog()
    assert aggregate(['PASS', 'INCOMPLETE']) == 'INCOMPLETE'
    assert aggregate(['FAIL', 'INCOMPLETE']) == 'FAIL'
    assert overall([{'status': 'FAIL'}], {}, {'actorType': 'human', 'requirements': [{'status': 'PASS'}]}) == 'FAIL'
    assert overall([{'status': 'PASS'}], {}, {'actorType': 'agent', 'requirements': [{'status': 'PASS'}]}) == 'INCOMPLETE'
    requirements = [{'id': 'r', 'text': '金额400'}]
    assert parse_semantic('{"requirements":[{"id":"r","status":"PASS","reason":"等价","quotes":["四百"]}]}', requirements, {'reply': '四百'})[0]['status'] == 'PASS'
    try:
        parse_semantic('{"requirements":[{"id":"r","status":"PASS","reason":"虚假证据","quotes":["400"]}]}', requirements, {'reply': '已完成'})
        raise AssertionError('Fabricated evidence accepted')
    except ValueError:
        pass
    case = {'input': {'turns': ['save']}, 'assertions': [{'id': 'created', 'kind': 'created', 'key': 'work', 'count': 1}]}
    false_receipt = {'turns': [{'message': {'reply': '已保存', 'job': {'state': 'succeeded'}}}], 'before': {'work': {'status': 200, 'items': []}}, 'after': {'work': {'status': 200, 'items': []}}}
    assert aggregate(r['status'] for r in deterministic(case, false_receipt)) == 'FAIL'
    assert deterministic(case, None)[0]['status'] == 'INCOMPLETE'
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'evidence.json'
        write(path, seal({'reply': 'original'}))
        try:
            write(path, {'reply': 'overwrite'})
            raise AssertionError('Overwrote evidence')
        except FileExistsError:
            pass
        bad = read(path); bad['reply'] = 'tampered'
        try:
            verify(bad)
            raise AssertionError('Tamper accepted')
        except ValueError:
            pass
    page = render({'status': 'INCOMPLETE', 'denominator': 1, 'rows': [{'id': '<script>', 'caseId': 'test', 'status': 'INCOMPLETE', 'seconds': None, 'evidence': 'trials/test'}]})
    assert '<script>' not in page
    print('PASS: catalog, hard failure precedence, human gate, semantic evidence, false receipts, missing evidence, append-only/tamper, HTML escaping')
    import asyncio, os, sys, importlib.util
    from .cancellation import bounded_trial, terminate_process
    async def cancellation_check():
        process = await asyncio.create_subprocess_exec(sys.executable, '-c', 'import time; time.sleep(60)', start_new_session=True)
        await terminate_process(process)
        assert process.returncode is not None
        with tempfile.TemporaryDirectory() as temp:
            stopped = asyncio.Event(); stopped.set()
            result = await bounded_trial(asyncio.sleep(60), stopped, 0.1, Path(temp))
            assert result['reason'] == 'cancelled' and result['cleanup']['status'] == 'not-admitted'
        with tempfile.TemporaryDirectory() as temp:
            result = await bounded_trial(asyncio.sleep(60), asyncio.Event(), 0.01, Path(temp))
            assert result['reason'] == 'timeout'
    asyncio.run(cancellation_check())
    from .evidence import ROOT
    sys.path.insert(0, str(ROOT / 'scripts/company/web-acceptance'))
    from environment import checked_url
    for url in ('postgresql://127.0.0.1/production', 'postgresql://example.com/paa_company_test'):
        try:
            checked_url(url)
            raise AssertionError('Unsafe DB accepted')
        except RuntimeError:
            pass
    spec = importlib.util.spec_from_file_location('eval_trace_check', ROOT / 'scripts/company/web-acceptance/agent-audit/trace.py')
    trace = importlib.util.module_from_spec(spec); spec.loader.exec_module(trace)
    filtered = trace.public_input({'messages': [{'role': 'assistant', 'content': 'public', 'reasoning_content': 'private'}], 'reasoning_effort': 'high', 'tools': [{'type': 'function'}]})
    assert filtered['messages'][0] == {'role': 'assistant', 'content': 'public'}
    assert filtered['reasoning_effort'] == 'high' and filtered['tools']
    result = dict(false_receipt, evidenceAvailable=[])
    evidence_case = dict(case, requiredEvidence=['actual-model-input'])
    assert any(r['id'] == 'evidence:actual-model-input' and r['status'] == 'INCOMPLETE' for r in deterministic(evidence_case, result))
    print('PASS: bounded cancellation/timeout, owned process termination, unsafe DB rejection, private reasoning removal, required evidence gate')
    from unittest.mock import AsyncMock, patch
    from types import SimpleNamespace
    from .grading import semantic
    configured = (SimpleNamespace(Settings=lambda: None), {'model': {'model': 'fixture', 'parameters': {}}, 'choice': {}, 'base': 'http://127.0.0.1', 'key': 'synthetic'})
    async def raw_error_check():
        with patch('app.integrations.models.chat.chat', new=AsyncMock(return_value={'choices': [{'message': {'content': 'invalid-json-verdict'}}], 'usage': {'total_tokens': 1}})):
            value = await semantic([{'id': 'r', 'text': 'test'}], {'reply': 'test'}, 'unused', configured)
        assert value['status'] == 'INCOMPLETE' and value['raw'] == 'invalid-json-verdict' and value['usage']['total_tokens'] == 1
    asyncio.run(raw_error_check())
    print('PASS: malformed grader response retains raw output and usage')
    from .grading import evidence_surface, parse_evidence_grade
    surface = evidence_surface({'reply': '四百元', 'after': {'work': []}})
    assert surface[1]['kind'] == 'observed-state'
    verdict = '{"requirements":[{"id":"r","status":"PASS","reason":"actual empty state","evidenceIds":["E0002"]}]}'
    assert parse_evidence_grade(verdict, [{'id': 'r'}], surface)[0]['status'] == 'PASS'
    try:
        parse_evidence_grade(verdict.replace('E0002', 'E9999'), [{'id': 'r'}], surface)
        raise AssertionError('Invented evidence ID accepted')
    except ValueError:
        pass
    print('PASS: typed text/state evidence and nonexistent evidence ID rejection')
