"""Verify actual provider HTTP history carries bounded saved-report receipts."""
import argparse
import hashlib
import json
from pathlib import Path


def build(phase):
    target = phase / 'report-inputs.json'
    if target.exists():
        raise RuntimeError('Refusing to overwrite observed receipt evidence')
    facts = json.loads((phase / 'facts.json').read_text())
    events = [json.loads(line) for line in (phase / 'trace.jsonl').open() if line.strip()]
    cases = []
    for case in facts['caseResults']:
        turns = []
        for turn in case['turns']:
            jobs = set(turn['associatedJobs'])
            start = min(event['time'] for event in events if event.get('jobId') == turn['jobId'])
            requests = [event for event in events if event.get('jobId') in jobs and event['time'] >= start
                        and event['kind'] == 'upstream_http_start' and isinstance(event.get('input'), dict)
                        and event['input'].get('model')]
            reports = {report['id']: report for report in (turn.get('publishedReports') or {}).get('items', [])}
            observations = []
            for request in requests:
                for index, message in enumerate(request['input']['messages']):
                    for part in message.get('parts', []):
                        text = part.get('text', '')
                        marker = text.find('服务端复核的当前操作状态')
                        if marker < 0 or 'reportSnapshot' not in text:
                            continue
                        cards, _ = json.JSONDecoder().raw_decode(text[text.index('[', marker):])
                        for card in cards:
                            snapshot = card.get('reportSnapshot')
                            if snapshot is None:
                                continue
                            report = reports.get(card.get('objectId'))
                            observations.append({'observationId': request['observationId'], 'jobId': request.get('jobId'),
                                                 'messageIndex': index, 'role': message['role'],
                                                 'messageSha256': hashlib.sha256(text.encode()).hexdigest(),
                                                 'truncated': part.get('truncated'), 'card': card,
                                                 'matchesFinalSavedRevisionAndContent': bool(report and snapshot.get('revision') == report['revision'] and snapshot.get('content') == report['content']),
                                                 'matchesFinalPublishedRevision': bool(report and snapshot.get('publishedRevision') == report['publishedRevision'])})
            turns.append({'turn': turn['turn'], 'parentJobId': turn['jobId'],
                          'actualProviderHttpRequests': len(requests), 'observations': observations,
                          'submitSnapshotMatchesSavedAndPublished': any(row['card']['action'] == 'submit_report'
                              and row['matchesFinalSavedRevisionAndContent'] and row['matchesFinalPublishedRevision']
                              for row in observations)})
        cases.append({'case': case['case'], 'turns': turns})
    target.write_text(json.dumps({'source': 'Actual upstream_http_start input, not prepared context or mocked requests',
                                 'selection': 'Historical/current confirmed-operation assistant message cards',
                                 'cases': cases}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': str(target), 'cases': len(cases)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', type=Path, required=True)
    build(parser.parse_args().phase.resolve())
