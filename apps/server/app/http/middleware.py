import asyncio
import json
import logging
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from app.core.errors import problem
from app.http.errors import http_error
from app.modules.auth.desktop import NATIVE_WRITES
from sqlalchemy.exc import SQLAlchemyError
from starlette.datastructures import MutableHeaders
from starlette.requests import ClientDisconnect
from time import perf_counter
from uuid import uuid4

request_log = logging.getLogger('uvicorn.error.paa_requests')


class Boundaries:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request = Request(scope, receive)
        request.state.request_id = str(uuid4())
        request.state.exception_type = None
        started, status = perf_counter(), None

        async def correlated_send(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                headers = MutableHeaders(scope=message)
                headers.setdefault('Cache-Control', 'no-store')
                headers.setdefault('Referrer-Policy', 'same-origin')
                headers.update({'X-Content-Type-Options': 'nosniff', 'X-Request-ID': request.state.request_id})
            await send(message)

        try:
            native = request.url.path in NATIVE_WRITES and request.headers.get('origin') is None
            if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('origin') != request.app.state.settings.web_origin and not native:
                response = JSONResponse({'error': {'code': 'origin_rejected', 'message': '请求来源不被允许', 'requestId': request.state.request_id}}, status_code=403)
                await response(scope, receive, correlated_send)
            else:
                await self.app(scope, receive, correlated_send)
        except asyncio.CancelledError:
            request.state.exception_type = 'CancelledError'
            raise
        except ClientDisconnect:
            request.state.exception_type = 'ClientDisconnect'
        except Exception as error:
            request.state.exception_type = type(error).__name__
            if status is not None:
                # Headers are already on the wire. Leave a failed stream
                # incomplete so the server closes it, without forwarding
                # private exceptions to its traceback logger or pretending
                # that the response body completed successfully.
                return
            if isinstance(error, HTTPException):
                response = await http_error(request, error)
            elif isinstance(error, SQLAlchemyError):
                response = JSONResponse({'error': {'code': 'service_unavailable', 'message': '服务暂不可用，请稍后重试', 'requestId': request.state.request_id}}, status_code=503)
            else:
                response = JSONResponse({'error': {'code': 'internal_error', 'message': '服务处理失败，请稍后重试', 'requestId': request.state.request_id}}, status_code=500)
            await response(scope, receive, correlated_send)
        finally:
            request_log.info('request %s', json.dumps({
                'requestId': request.state.request_id,
                'route': getattr(scope.get('route'), 'path', '<unmatched>'),
                'status': status,
                'durationMs': round((perf_counter() - started) * 1000, 2),
                'exceptionType': request.state.exception_type,
            }, ensure_ascii=True))


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        size = 0
        async def bounded():
            nonlocal size
            message = await receive()
            size += len(message.get('body', b''))
            if size > 25 * 1024 * 1024:
                problem(413, '上传总大小不能超过 25 MiB')
            return message
        await self.app(scope, bounded, send)
