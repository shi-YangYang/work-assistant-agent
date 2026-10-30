"""Escaped static reports and strict paired observations, never aggregate away failures."""
import html
from .evidence import read, verify, digest, verify_files
from .grading import overall, aggregate, deterministic


def report(run):
    manifest = verify(read(run / 'manifest.json'))
    rows = []
    for slot in manifest['slots']:
        directory = run / 'trials' / slot['id']
        result = verify(read(directory / 'result.json')) if (directory / 'result.json').exists() else None
        grades = sorted((run / 'grades').glob(slot['id'] + '-*.json'))
        grade = read(grades[-1]) if grades else {}
        reviews = sorted((run / 'reviews').glob(slot['id'] + '-*.json'))
        review = read(reviews[-1]) if reviews else None
        if grade and grade.get('evidenceSha256') != digest(result):
            raise ValueError('Grade evidence binding differs')
        if review and (review.get('evidenceSha256') != digest(result) or review.get('gradeSha256') != digest(grade)):
            review = None
        case = next(c for c in manifest['cases'] if c['id'] == slot['caseId'])
        verify_files(result, directory, case.get('requiredEvidence', []))
        status = overall(grade.get('assertions', []), grade.get('semantic'), review) if grade else 'INCOMPLETE'
        if case['execution'] == 'contract/replay':
            status = aggregate(r['status'] for r in deterministic(case, result))
        causes = []
        if (result or {}).get('error'):
            causes.append({'category': 'evaluator/environment', 'observed': result['error']})
        codes = sorted({node.get('errorCode') for row in (result or {}).get('turns', []) for node in (row.get('message', {}).get('job') or {}).get('nodes', []) if node.get('errorCode')})
        if codes:
            causes.append({'category': 'external-service' if all(code.startswith('provider_') for code in codes) else 'unknown', 'observedCodes': codes, 'limit': 'No network or pure-model attribution from duration alone; SSE error prose may be unavailable'})
        if grade.get('semantic', {}).get('status') == 'INCOMPLETE':
            causes.append({'category': 'offline-grader', 'observed': grade.get('semantic', {}).get('error', 'not graded')})
        rows.append({**slot, 'causes': causes, 'pendingHumanReview': not review or review.get('actorType') != 'human', 'status': status, 'seconds': (result or {}).get('seconds'), 'execution': 'finished' if result else 'started' if (directory / 'started.json').exists() else 'not_started', 'assertions': grade.get('assertions', []), 'semantic': grade.get('semantic'), 'review': review, 'evidence': str(directory.relative_to(run)), 'firstAttempt': True, 'cost': None, 'usage': (result or {}).get('usage'), 'providerRequests': (result or {}).get('providerRequests'), 'timing': (result or {}).get('timing')})
    return {'version': 1, 'run': str(run), 'planSha256': manifest['sha256'], 'suite': manifest['suite'], 'status': aggregate(r['status'] for r in rows), 'denominator': len(rows), 'distinctCases': len(manifest['cases']), 'rows': rows}


def render(value):
    rows = ''.join('<tr><td>' + html.escape(r['id']) + '</td><td>' + html.escape(r['caseId']) + '</td><td>' + r['status'] + '</td><td>' + str(r['seconds']) + '</td><td><a href="' + html.escape(r['evidence'], quote=True) + '/result.json">原始证据</a><details><summary>断言与复核</summary><pre>' + html.escape(__import__('json').dumps(r, ensure_ascii=False, indent=2)) + '</pre></details></td></tr>' for r in value['rows'])
    return '<!doctype html><meta charset="utf-8"><title>Agent evaluation</title><h1>' + value['status'] + '</h1><p>全部冻结槽位：' + str(value['denominator']) + '；未执行和待人工复核仍在分母。费用未知。</p><table><tr><th>槽位</th><th>用例</th><th>结果</th><th>秒</th><th>证据</th></tr>' + rows + '</table>'


def compare(a, b):
    if a.resolve() == b.resolve():
        raise ValueError('Baseline and candidate must be independent runs')
    ma, mb = verify(read(a / 'manifest.json')), verify(read(b / 'manifest.json'))
    for key in ('cases', 'slots', 'gradingVersion'):
        if ma[key] != mb[key]:
            raise ValueError('Unmatched comparison: ' + key)
    ca, cb = dict(ma['config']), dict(mb['config'])
    ca['environment'] = ca['environment']['profile']; cb['environment'] = cb['environment']['profile']
    if ca != cb:
        raise ValueError('Unmatched environment/model/comparison profile')
    def effective_grades(root):
        values = []
        for slot in ma['slots']:
            paths = sorted((root / 'grades').glob(slot['id'] + '-*.json'))
            if not paths:
                raise ValueError('Missing effective paired grade')
            grade = read(paths[-1])
            values.append({k: grade.get(k) for k in ('graderSha256', 'requirementsSha256')} | {'judge': grade.get('semantic', {}).get('model')})
        return values
    if effective_grades(a) != effective_grades(b):
        raise ValueError('Effective per-slot graders differ')
    if ma['config']['comparison'].get('sampleSize') != len(ma['slots']):
        raise ValueError('Frozen comparison sample size differs from slots')
    if ma['config']['comparison'].get('order') not in ('AB', 'BA'):
        raise ValueError('Comparison order/sample size must be frozen before runs')
    ra, rb = report(a), report(b)
    pairs = [{'slot': x['id'], 'baseline': x['status'], 'candidate': y['status'], 'baselineSeconds': x['seconds'], 'candidateSeconds': y['seconds'], 'bothPass': x['status'] == y['status'] == 'PASS'} for x, y in zip(ra['rows'], rb['rows'])]
    return {'sampleSize': len(pairs), 'pairs': pairs, 'qualityGate': ra['status'] == rb['status'] == 'PASS', 'claim': 'Descriptive observations only; no general speedup claim'}
