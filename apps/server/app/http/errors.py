from fastapi.responses import JSONResponse
from app.http.validation import validation_detail
from app.integrations.models.transport import ProviderError
from app.modules.members.schemas import member_validation_errors


async def http_error(request, error):
    request.state.exception_type = type(error).__name__
    detail = error.detail if isinstance(error.detail, dict) else {'code': 'invalid_request', 'message': str(error.detail)}
    return JSONResponse({'error': {**detail, 'requestId': request.state.request_id}}, status_code=error.status_code, headers=error.headers)


async def model_error(request, error):
    request.state.exception_type = type(error).__name__
    return JSONResponse({'error': {'code': getattr(error, 'code', 'secret_unavailable'), 'message': str(error), 'requestId': request.state.request_id}}, status_code=422 if isinstance(error, ProviderError) else 503)


async def validation_error(request, error):
    request.state.exception_type = type(error).__name__
    errors = error.errors()
    detail = {**validation_detail(errors), 'requestId': request.state.request_id}
    reset = request.url.path.startswith('/api/v1/members/') and request.url.path.endswith('/reset-password')
    if request.url.path == '/api/v1/members' or reset:
        fields = member_validation_errors(errors, reset=reset)
        if fields:
            detail.update(message='请检查标记的输入项', fieldErrors=fields)
    return JSONResponse({'error': detail}, status_code=422)
