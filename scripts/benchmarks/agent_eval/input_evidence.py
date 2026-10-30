"""Project saved wire context, never assistant assertions or privileged prompts."""
from .evidence import digest


def model_input_evidence(result):
    result = result or {}
    trace = result.get('trace') or []
    turns = {}
    for index, row in enumerate(result.get('turns') or []):
        job = (row.get('message') or {}).get('job') or {}
        if job.get('id'):
            turns.setdefault(job['id'], []).append(index)
    entries, issues = [], []
    starts = {(e.get('jobId'), e.get('providerRequestId')) for e in trace
              if e.get('kind') == 'provider_request_start' and e.get('jobId') in turns and e.get('providerRequestId')}
    captured = set()
    for index, event in enumerate(trace):
        if event.get('kind') != 'upstream_http_start':
            continue
        pair = (event.get('jobId'), event.get('providerRequestId'))
        path = f'trace[{index}].input.messages'
        if pair not in starts or len(turns.get(pair[0], [])) != 1:
            issues.append({'path': path, 'reason': 'Unbound or ambiguous job/provider request; input excluded'})
            continue
        wire = event.get('input')
        messages = wire.get('messages') if isinstance(wire, dict) else None
        if not isinstance(messages, list) or not messages:
            issues.append({'path': path, 'reason': 'Actual wire messages missing or invalid'})
            continue
        captured.add(pair)
        provenance = {key: event[key] for key in ('jobId', 'providerRequestId', 'captureId', 'observationId', 'modelAttemptId', 'requestBodySha256', 'attempt') if key in event}
        provenance.update(turnIndex=turns[pair[0]][0], traceIndex=index)
        found = False
        for message_index, message in enumerate(messages):
            if not isinstance(message, dict):
                issues.append({'path': f'{path}[{message_index}]', 'reason': 'Invalid message'})
                continue
            role = message.get('role')
            if role not in ('user', 'tool'):
                continue
            found = True
            location = f'{path}[{message_index}].content'
            origin = {**provenance, 'role': role, 'messageIndex': message_index,
                      'scope': 'Saved request context; may include history, not proof of current-turn delivery'}
            if role == 'tool':
                origin.update({key: message[key] for key in ('tool_call_id', 'name') if isinstance(message.get(key), str)})
            content = message.get('content')
            blocks = [(location, content)] if isinstance(content, str) else [
                (f'{location}[{i}]', block) for i, block in enumerate(content)] if isinstance(content, list) else []
            if not blocks:
                issues.append({'path': location, 'reason': 'Source content missing or empty block list'})
            for block_path, block in blocks:
                text = block if isinstance(block, str) else block.get('text') if isinstance(block, dict) and block.get('type') in ('text', 'input_text') else None
                if isinstance(text, str):
                    entries.append({'path': block_path + ('.text' if isinstance(block, dict) else ''),
                                    'kind': 'model-input-context' if role == 'user' else 'model-input-tool-data',
                                    'text': text, 'provenance': origin})
                else:
                    # Do not forward URLs/base64, private fields, or pretend pixels were read.
                    issues.append({'path': block_path, 'reason': 'Non-text or invalid source block not supplied to judge; contents unknown',
                                   'blockSha256': digest(block), 'provenance': origin})
        if not found:
            issues.append({'path': path, 'reason': 'No allowlisted user/tool source messages captured'})
    for job, request in sorted(starts - captured):
        issues.append({'jobId': job, 'providerRequestId': request, 'reason': 'Started request lacks usable captured input'})
    if not starts:
        issues.append({'reason': 'No provider start bound to an observed turn job; actual source input unavailable'})
    # Keep occurrences, even repeated text: positions and provider/turn versions matter.
    return {'entries': entries, 'limitations': issues}
