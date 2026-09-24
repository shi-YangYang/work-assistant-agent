from fastapi import HTTPException


def problem(status, message, code=None):
    raise HTTPException(status_code=status, detail={'code': code or {404: 'not_found', 409: 'conflict', 403: 'forbidden'}.get(status, 'invalid_request'), 'message': message})
