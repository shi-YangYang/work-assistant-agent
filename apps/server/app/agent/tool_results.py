"""Shared machine-readable tool failures, independent of public error prose."""


def http_failure(error):
    """Keep the HTTP boundary's authority; an unavailable ID is not a retry grant."""
    detail = error.detail if isinstance(error.detail, dict) else {'message': str(error.detail)}
    status = error.status_code
    category = ('permission_denied' if status in (401, 403, 404) else
                'conflict' if status == 409 else 'invalid_arguments' if status in (400, 422) else
                'transient_failure' if status in (408, 429) or status >= 500 else 'unknown')
    owner = 'assistant' if category in ('conflict', 'invalid_arguments') else 'system'
    # Explicit domain recovery always wins over a generic HTTP classification.
    recovery = detail.get('recovery') or {'owner': owner, 'nextAction': 'repair' if owner == 'assistant' else 'stop'}
    return {'state': 'conflict' if status == 409 else 'failed',
            'category': category, 'code': detail.get('code', f'http_{status}'),
            'httpStatus': status, 'message': detail.get('message', '操作暂时无法完成'), 'recovery': recovery}


def layers(result):
    """Only descend into error envelopes, never into untrusted business content."""
    values = [result]
    error = result.get('error')
    if isinstance(error, dict):
        values.append(error)
    return values


def result_state(result):
    return result.get('state', result.get('status'))


def failed_result(result):
    return any(value.get('category') in ('invalid_arguments', 'permission_denied', 'missing_info', 'conflict', 'transient_failure')
               or result_state(value) in ('failed', 'conflict', 'invalid_reference', 'unavailable', 'clarification', 'not_found', 'not_requested', 'not_executed', 'unknown', 'retryable', 'cancelled', 'interrupted')
               or 'error' in value for value in layers(result))


def recoverable_result(result):
    """Allow bounded fact repair only with positive, assistant-owned evidence.

    A generic failure says nothing about whether more exploration can repair it.
    Terminal/authority signals win even when a wrapper also says "conflict".
    """
    values = layers(result)
    for value in values:
        recovery = value.get('recovery') or {}
        if (value.get('category') in ('permission_denied', 'missing_info', 'not_requested')
                or result_state(value) in ('cancelled', 'interrupted', 'unknown', 'not_requested', 'not_executed')
                or value.get('httpStatus') in (401, 403, 404)
                or value.get('errorCode', value.get('code')) in ('http_401', 'http_403', 'blocked_url', 'forbidden', 'permission_denied', 'unauthorized')
                or recovery.get('nextAction') in ('stop', 'ask')
                or recovery.get('owner') in ('user', 'system', 'none')):
            return False
    return any(value.get('category') in ('conflict', 'invalid_arguments')
               or result_state(value) == 'conflict'
               or value.get('recovery', {}).get('owner') == 'assistant'
               and value.get('recovery', {}).get('nextAction') in ('repair', 'refresh')
               for value in values)
