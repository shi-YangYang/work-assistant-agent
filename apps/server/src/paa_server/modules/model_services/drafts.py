import hashlib
import json
from paa_server.core.errors import problem
from paa_server.core.versions import version
from paa_server.integrations.models.transport import normalize_url
from paa_server.modules.model_services.parameters import request_options
from paa_server.modules.model_services.service import current_revision, get_service
from paa_server.security.secrets import decrypt


async def draft_config(db, actor, body, settings):
    url = normalize_url(body.baseUrl, settings)
    key = body.apiKey
    row = None
    if body.serviceId:
        row = await get_service(db, actor.company_id, body.serviceId)
        version(row, body.expectedRevision)
    if not key:
        if not row or url != row.base_url:
            problem(422, '请为当前服务地址输入密钥')
        rev = await current_revision(db, row)
        key = decrypt(settings.model_key_file, rev.credential, actor.company_id, row.id, rev.revision)
    payload = body.model_dump(exclude={'apiKey'})
    # Fingerprint uses a digest, never plaintext credential or reusable token.
    payload['credentialDigest'] = hashlib.sha256(key.encode()).hexdigest()
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    model = next((m.model_dump() for m in body.models if m.id == body.modelId), None)
    config = None
    if model:
        config = {'baseUrl': url, 'model': model['model'], 'protocol': model['protocol'], 'streaming': model['streaming'] if model['protocol'] == 'chat' else False, 'parameters': request_options(model), 'language': model['language']}
    return config, key, fingerprint
