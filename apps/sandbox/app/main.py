"""Private authenticated control plane. Run exactly one process per state directory."""
from contextlib import asynccontextmanager
import hmac
import os
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from .schemas import ExecutionRequest, MAX_INPUT_BYTES, execution_id
from .service import Service

service = Service()


@asynccontextmanager
async def lifespan(app):
    if len(os.environ.get('SANDBOX_TOKEN', '')) < 32:
        raise RuntimeError('A private SANDBOX_TOKEN of at least 32 characters is required')
    await service.start()
    try:
        yield
    finally:
        await service.stop()


async def authenticated(request: Request):
    expected = os.environ.get('SANDBOX_TOKEN', '')
    if not expected or not hmac.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + expected):
        raise HTTPException(401, 'Unauthorized')


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None, dependencies=[Depends(authenticated)])


@app.middleware('http')
async def body_limit(request, call_next):
    from starlette.responses import JSONResponse
    if request.method == 'POST':
        maximum = MAX_INPUT_BYTES * 4 // 3 + 128 * 1024
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > maximum:
                return JSONResponse({'detail': 'Input too large'}, status_code=413)
        request._body = bytes(data)
    return await call_next(request)


@app.get('/health')
async def health():
    await service.runtime.check()
    return {'ready': True, 'runtime': 'runsc', 'concurrency': service.concurrency}


@app.post('/executions')
async def submit(body: ExecutionRequest):
    try:
        return service.submit(body)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    except OverflowError as error:
        raise HTTPException(429, str(error)) from error


@app.get('/executions/{identifier}')
async def read(identifier: str):
    try:
        row = service.get(identifier)
    except ValueError as error:
        raise HTTPException(404, 'Execution not found') from error
    if not row:
        raise HTTPException(404, 'Execution not found')
    return row


@app.post('/executions/{identifier}/cancel')
async def cancel(identifier: str):
    await read(identifier)
    await service.cancel(identifier)
    return service.get(identifier)


@app.delete('/executions/{identifier}')
async def release(identifier: str):
    await read(identifier)
    await service.release(identifier)
    return {'released': True}


@app.get('/executions/{identifier}/files/{file_id}')
async def file(identifier: str, file_id: str):
    row = await read(identifier)
    if row['state'] != 'succeeded' or not any(item['id'] == file_id for item in row['files']):
        raise HTTPException(404, 'File unavailable')
    return FileResponse(service.directory(identifier) / execution_id(file_id), media_type='application/octet-stream')
