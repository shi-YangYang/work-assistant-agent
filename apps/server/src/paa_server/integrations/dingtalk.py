import httpx
import json
from dataclasses import dataclass


def numeric_error_code(value):
    # Error fields are vendor-controlled. Keep only bounded numeric codes,
    # never arbitrary strings that could include identities or credentials.
    if type(value) is int and 0 <= value <= 9999999999:
        return value
    if isinstance(value, str) and 1 <= len(value) <= 10 and value.isascii() and value.isdigit():
        return int(value)
    return None


class DingTalkError(ValueError):
    def __init__(self, reason='denied', *, stage='unknown', http_status=None, vendor_code=None, vendor_sub_code=None):
        self.reason = reason if reason in ('denied', 'unavailable', 'permission', 'conflict') else 'denied'
        self.diagnostics = {
            'stage': stage if stage in ('user_token', 'personal_identity', 'enterprise_token', 'union_lookup', 'member_detail') else 'unknown',
            'httpStatus': http_status if type(http_status) is int and 100 <= http_status <= 599 else None,
            'vendorCode': numeric_error_code(vendor_code),
            'vendorSubCode': numeric_error_code(vendor_sub_code),
        }
        super().__init__('钉钉身份或公司成员资格无法核验，请检查授权范围后重试')


@dataclass(frozen=True)
class VerifiedMember:
    union_id: str
    user_id: str
    name: str


class DingTalkProvider:
    def __init__(self, transport=None):
        self.transport = transport

    async def verify(self, corp_id, client_id, secret, code):
        stage, http_status, vendor_code, vendor_sub_code = 'unknown', None, None, None

        def failure(reason='denied'):
            return DingTalkError(reason, stage=stage, http_status=http_status, vendor_code=vendor_code, vendor_sub_code=vendor_sub_code)

        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=httpx.Timeout(12, connect=5), trust_env=False, follow_redirects=False, headers={'Accept-Encoding': 'identity'}) as client:
                async def call(operation, method, url, **kwargs):
                    nonlocal stage, http_status, vendor_code, vendor_sub_code
                    stage, http_status, vendor_code, vendor_sub_code = operation, None, None, None
                    async with client.stream(method, url, **kwargs) as response:
                        http_status = response.status_code
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 256 * 1024:
                                raise failure()
                            chunks.append(chunk)
                        try:
                            data = json.loads(b''.join(chunks))
                        except (ValueError, UnicodeError):
                            raise failure('unavailable' if http_status == 200 else 'denied') from None
                        if isinstance(data, dict):
                            vendor_code = numeric_error_code(data.get('errcode', data.get('code')))
                            vendor_sub_code = numeric_error_code(data.get('sub_code'))
                            if 60011 in (vendor_code, vendor_sub_code):
                                raise failure('permission')
                        if http_status != 200 or not isinstance(data, dict) or data.get('errcode', 0) != 0 or 'code' in data:
                            raise failure()
                        return data

                token = await call('user_token', 'POST', 'https://api.dingtalk.com/v1.0/oauth2/userAccessToken', json={'clientId': client_id, 'clientSecret': secret, 'code': code, 'grantType': 'authorization_code'})
                if token.get('corpId') != corp_id or not token.get('accessToken'):
                    raise failure()
                person = await call('personal_identity', 'GET', 'https://api.dingtalk.com/v1.0/contact/users/me', headers={'x-acs-dingtalk-access-token': token['accessToken']})
                union_id = person.get('unionId')
                if not isinstance(union_id, str) or not 1 <= len(union_id) <= 256:
                    raise failure()
                enterprise = await call('enterprise_token', 'POST', 'https://api.dingtalk.com/v1.0/oauth2/accessToken', json={'appKey': client_id, 'appSecret': secret})
                access_token = enterprise.get('accessToken')
                if not isinstance(access_token, str) or not access_token:
                    raise failure()
                mapped = await call('union_lookup', 'POST', 'https://oapi.dingtalk.com/topapi/user/getbyunionid', data={'access_token': access_token, 'unionid': union_id})
                mapped = mapped.get('result', {})
                user_id = mapped.get('userid')
                if mapped.get('contact_type') != 0 or not isinstance(user_id, str) or not 1 <= len(user_id) <= 256:
                    raise failure()
                # This corporate-token API applies the application's directory
                # data scope; admins must align it with the permitted login
                # audience. Workbench visibility is not treated as an API scope.
                # Missing permission/out-of-scope errors fail closed.
                member = await call('member_detail', 'POST', 'https://oapi.dingtalk.com/topapi/v2/user/get', data={'access_token': access_token, 'userid': user_id, 'language': 'zh_CN'})
                member = member.get('result', {})
                if member.get('userid') != user_id or member.get('unionid') != union_id or member.get('active') is not True:
                    raise failure()
                name = member.get('name')
                return VerifiedMember(union_id, user_id, name.strip()[:80] if isinstance(name, str) and name.strip() else '钉钉成员')
        except DingTalkError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
            raise failure('unavailable') from None
