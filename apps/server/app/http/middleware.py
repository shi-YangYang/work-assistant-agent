import asyncio
import errno
import json
import logging
import shutil
import tempfile
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from app.core.errors import problem
from app.core.attachment_limits import MAX_UPLOAD_BODY_BYTES, MAX_REQUEST_BODY_BYTES, MAX_CONCURRENT_UPLOADS
from app.http.errors import http_error
from app.modules.auth.desktop import NATIVE_WRITES
from sqlalchemy.exc import SQLAlchemyError
from starlette.datastructures import MutableHeaders
from starlette.requests import ClientDisconnect
from starlette.formparsers import MultiPartException
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
            elif isinstance(error, OSError) and error.errno in (errno.ENOSPC, errno.EDQUOT):
                response = JSONResponse({'error': {'code': 'storage_full', 'message': '文件存储空间不足，请稍后重试或联系管理员', 'requestId': request.state.request_id}}, status_code=507)
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
        self.uploads = 0

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        upload = scope['method'] == 'POST' and scope['path'] == '/api/v1/uploads'
        maximum = MAX_UPLOAD_BODY_BYTES if upload else MAX_REQUEST_BODY_BYTES
        request = Request(scope)
        async def reject(status, code, message):
            response = JSONResponse({'error': {'code': code, 'message': message, 'requestId': getattr(request.state, 'request_id', None)}}, status_code=status,
                                    headers={'Retry-After': '2'} if status == 429 else None)
            await response(scope, receive, send)
        message = f'单次请求不能超过 {maximum // (1024 * 1024)} MB'
        length = request.headers.get('content-length', '')
        if length.isdecimal() and int(length) > maximum:
            return await reject(413, 'upload_too_large', message)
        if upload:
            # Reject before multipart spooling; waiting here would retain large
            # bodies/connections. The normal client uploads only two at a time.
            if self.uploads >= MAX_CONCURRENT_UPLOADS:
                return await reject(429, 'upload_busy', '上传服务繁忙，请稍后重试')
            if shutil.disk_usage(tempfile.gettempdir()).free < MAX_UPLOAD_BODY_BYTES + 512 * 1024 * 1024:
                return await reject(507, 'storage_full', '文件存储空间不足，请稍后重试或联系管理员')
            self.uploads += 1
        size, exceeded = 0, False
        async def bounded():
            nonlocal size, exceeded
            packet = await receive()
            size += len(packet.get('body', b''))
            if size > maximum:
                if request.headers.get('content-type', '').startswith('multipart/form-data'):
                    exceeded = True
                    # Starlette closes partial spooled files on this exception.
                    raise MultiPartException(message)
                problem(413, message)
            return packet
        async def bounded_send(packet):
            if not exceeded:
                await send(packet)
        try:
            await self.app(scope, bounded, bounded_send)
            if exceeded:
                await reject(413, 'upload_too_large', message)
        finally:
            if upload:
                self.uploads -= 1
