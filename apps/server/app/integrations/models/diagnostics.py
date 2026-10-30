"""Failure-only upstream evidence for internal logs, never public error messages."""
import json
import logging
import re
from uuid import uuid4

import httpx


log = logging.getLogger('paa.model_diagnostics')
MAX_DETAIL_CHARS = 8192
REQUEST_ID_HEADERS = ('x-request-id', 'x-dashscope-request-id', 'x-acs-request-id')
REQUEST_ID_PATTERN = re.compile(r'(?:[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|req_[A-Za-z0-9_-]{8,120}|[0-9a-fA-F]{16,128})')
SECRET_FIELD = re.compile(r'authorization|cookie|password|secret|credential|apikey|accesskey|token', re.I)
SECRET_TEXT = re.compile(r'''(?i)(\b(?:api[_-]?key|access[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|authorization|cookie)\b["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;&<>]+)''')
AUTH_TEXT = re.compile(r'(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+')
OMITTED_FIELDS = frozenset(('messages', 'prompt', 'input', 'output', 'request', 'response', 'body', 'headers',
                            'choices', 'delta', 'content', 'tools', 'toolcalls', 'arguments',
                            'reasoning', 'reasoningcontent', 'reasoningdetails', 'thinking', 'encryptedcontent'))


def response_metadata(response):
    """Only fixed media types and recognizable opaque request identifiers leave HTTP."""
    content_type = response.headers.get('content-type', '').partition(';')[0].strip().lower()
    fields = {'http_status': response.status_code,
              'content_type': content_type if content_type in (
                  'application/json', 'application/problem+json', 'text/event-stream',
                  'text/html', 'text/plain', 'application/octet-stream') else 'other' if content_type else None}
    for header in REQUEST_ID_HEADERS:
        value = response.headers.get(header, '')
        if len(value) <= 128 and REQUEST_ID_PATTERN.fullmatch(value):
            fields.update(provider_request_id=value, provider_request_id_header=header)
            break
    return fields


def _detail(payload, key):
    """Bound work and redact before truncating, including keys echoed in prose."""
    remaining = 128

    def clean_text(value):
        if key:
            value = value.replace(key, '[redacted]')
        return SECRET_TEXT.sub(r'\1[redacted]', AUTH_TEXT.sub('[redacted]', value))

    def clean(value, depth=0):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 6:
            return '[omitted]'
        if isinstance(value, dict):
            result = {}
            for field, item in value.items():
                if remaining < 0:
                    result['...'] = '[omitted]'
                    break
                normalized = re.sub(r'[^a-z0-9]', '', field.lower())
                name = clean_text(field)[:128]
                if SECRET_FIELD.search(normalized):
                    result[name] = '[redacted]'
                    remaining -= 1
                elif normalized in OMITTED_FIELDS:
                    result[name] = '[omitted]'
                    remaining -= 1
                else:
                    result[name] = clean(item, depth + 1)
            return result
        if isinstance(value, list):
            return [clean(item, depth + 1) for item in value[:32]]
        if isinstance(value, str):
            return clean_text(value)
        return value

    # Serialize to a single bounded string so a truncated object is never
    # mistaken for a complete provider response. The outer log stays valid JSON.
    detail = json.dumps(clean(payload), ensure_ascii=False, separators=(',', ':'))
    return detail[:MAX_DETAIL_CHARS], len(detail) > MAX_DETAIL_CHARS


def upstream_error(error, payload, *, source, key='', metadata=None, on_timing=None):
    detail, truncated = _detail(payload, key)
    metadata = {name: value.replace(key, '[redacted]') if key and isinstance(value, str) else value
                for name, value in (metadata or {}).items()}
    diagnostic = {'diagnostic_id': str(uuid4()), 'source': source, 'error_code': error.code,
                  **metadata, 'detail': detail, 'truncated': truncated}
    # Exception args/str remain the safe public message. Only internal consumers
    # explicitly read this separate attribute; usage/job DTOs never serialize it.
    error.upstream_diagnostic = diagnostic
    log.warning('model.upstream_error %s', json.dumps(diagnostic, ensure_ascii=False, separators=(',', ':')))
    if on_timing:
        on_timing('model.upstream_error', diagnostic_id=diagnostic['diagnostic_id'], **metadata)
    return error


def http_error(error, response, *, on_timing=None):
    try:
        authorization = response.request.headers.get('authorization', '')
        key = authorization.partition(' ')[2]
    except RuntimeError:  # Standalone response without an originating request.
        key = ''
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    except httpx.ResponseNotRead:
        payload = '[response body not read]'
    return upstream_error(error, payload, source='http', key=key,
                          metadata=response_metadata(response), on_timing=on_timing)
