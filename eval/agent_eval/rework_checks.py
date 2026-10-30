"""Regression probes for accepted-evidence lifecycle and hard-fact false positives."""
import asyncio
import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from . import cancellation
from .evidence import ROOT, read, verify_files, grader_source
from .facts import sandbox, mutations, contract_checks, PERMISSION_IDS


def check():
    async def lifecycle():
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'accepted.jsonl').write_text(json.dumps({'receipt': {'jobId': 'owned', 'messageId': 'message'}}) + '\n')
            (directory / 'first.jsonl').write_text(json.dumps({'turn': 1, 'message': {'reply': 'partial'}}) + '\n')
            calls = []
            async def cleanup(path):
                calls.append(path)
                return {'status': 'INCOMPLETE'}
            async def fail():
                raise RuntimeError('read failed after acceptance')
            with patch.object(cancellation, 'cleanup_owned', cleanup):
                result = await cancellation.bounded_trial(fail(), asyncio.Event(), 1, directory)
                assert len(calls) == 1 and result['accepted'] and result['turns'] and result['reason'] == 'RuntimeError'
                result = await cancellation.bounded_trial(asyncio.sleep(1), asyncio.Event(), 0.001, directory)
                assert len(calls) == 2 and result['reason'] == 'timeout'
                stopped = asyncio.Event(); stopped.set()
                result = await cancellation.bounded_trial(asyncio.sleep(1), stopped, 1, directory)
                assert len(calls) == 3 and result['reason'] == 'cancelled'
    asyncio.run(lifecycle())
    async def denied_cleanup():
        from . import adapters
        class Response:
            status_code = 401
            def raise_for_status(self):
                raise RuntimeError('login denied')
        class Client:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def post(self, *args, **kwargs): return Response()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); (directory / 'environment').mkdir()
            (directory / 'environment/metadata.json').write_text('{}')
            (directory / 'accepted.jsonl').write_text(json.dumps({'receipt': {'jobId': 'known', 'messageId': 'known-message'}}))
            with patch.object(adapters, 'environment', lambda p: (None, None, {'apiOrigin': 'http://local', 'origin': 'http://local', 'users': {'employee': {'username': 'test', 'password': 'test'}}})), patch('httpx.AsyncClient', Client):
                result = await cancellation.cleanup_owned(directory)
                assert result['status'] == 'INCOMPLETE' and result['jobs'][0]['job'] == 'known'
    asyncio.run(denied_cleanup())
    for slot in ('s0023', 's0024'):
        result = read(ROOT / f'artifacts/agent-eval/spec082-http-v2/trials/{slot}/result.json')
        assert sandbox(result)[0] == 'PASS'
        broken = copy.deepcopy(result)
        for e in broken['trace']:
            if e.get('table') == 'company_sandbox_execution':
                e['values'].update(state='failed', result={'error': 'expected succeeded, but failed'})
        assert sandbox(broken)[0] == 'FAIL'
        for e in broken['trace']:
            if e.get('table') == 'company_sandbox_execution':
                e['values']['state'] = 'queued'
        assert sandbox(broken)[0] == 'INCOMPLETE'
    case = {'input': {'mutationBounds': [{'workCreate': 0, 'workDelete': 0, 'workUpdate': 1}], 'allowedFields': [{'work': ['nextStep']}]}}
    def event(identifier, action, fields):
        return {'jobId': 'j', 'kind': 'database_commit', 'table': 'company_business_action', 'values': {'id': identifier, 'state': 'succeeded', 'action': action, 'result': {'objectType': 'work', 'changedFields': fields}}}
    result = {'turns': [{'receipt': {'jobId': 'j'}}], 'trace': [event('a', 'create_work', []), event('b', 'delete_work', [])], 'mutationEvidenceComplete': True}
    assert mutations(case, result, 0, 'work', 'work')[0]['status'] == 'FAIL'
    result['trace'] = [event('a', 'update_work', ['nextStep']), event('b', 'update_work', ['nextStep'])]
    assert mutations(case, result, 0, 'work', 'work')[0]['status'] == 'FAIL'
    result['trace'] = [event('a', 'update_work', ['status'])]
    assert mutations(case, result, 0, 'work', 'work')[1]['status'] == 'FAIL'
    result['trace'] = [event('a', 'update_work', [])]
    del result['trace'][0]['values']['result']['changedFields']
    assert mutations(case, result, 0, 'work', 'work')[1]['status'] == 'INCOMPLETE'
    result['trace'] = [event('a', 'restore_work', [])]
    assert mutations(case, result, 0, 'work', 'work')[0]['status'] == 'INCOMPLETE'
    result['trace'] = []; result.pop('mutationEvidenceComplete')
    assert mutations(case, result, 0, 'work', 'work')[0]['status'] == 'INCOMPLETE'
    case = {'expectedCheckIds': PERMISSION_IDS, 'requiredEvidence': ['http']}
    checks = [{'id': name, 'status': 'PASS', 'observed': True} for name in PERMISSION_IDS]
    for bad in (checks[:-1], checks + checks[:1], checks + [{'id': 'unknown', 'status': 'PASS', 'observed': True}]):
        assert any(r['status'] == 'INCOMPLETE' for r in contract_checks(case, {'checks': bad, 'evidenceAvailable': ['http']}))
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp); file = directory / 'download.txt'; file.write_text('original')
        import hashlib
        result = {'evidenceFiles': {'download.txt': hashlib.sha256(file.read_bytes()).hexdigest()}}
        verify_files(result, directory)
        file.write_text('changed')
        for remove in (False, True):
            if remove: file.unlink()
            try: verify_files(result, directory)
            except ValueError: pass
            else: raise AssertionError('Altered file was accepted')
    assert 'eval/support/agent/agent_eval_grading.py' in grader_source()
    print('PASS: exception/timeout/cancel partial evidence; structured sandbox; committed mutation bounds/fields; contract IDs; file integrity; shared grader fingerprint')


if __name__ == '__main__':
    check()
