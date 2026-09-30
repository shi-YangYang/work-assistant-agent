"""Private execution protocol; no provider/model keys are sent to the sandbox."""
import asyncio
import hashlib
import httpx
from app.integrations.models.transport import ProviderError


class SandboxClient:
    def __init__(self, settings):
        self.url = settings.sandbox_url.rstrip('/')
        self.token = settings.sandbox_token
        if not self.url or not self.token:
            raise ValueError('代码执行服务尚未启用；可以继续普通问答、写作和联网研究')

    async def request(self, method, path, body=None):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5), follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, self.url + path, json=body, headers={'Authorization': 'Bearer ' + self.token})
            if response.status_code == 404:
                return None
            if response.status_code in (401, 403):
                raise ValueError('代码执行服务认证配置有误，请联系管理员')
            if response.status_code == 409:
                raise ValueError('执行身份与输入不一致，已停止此次执行')
            if response.status_code in (400, 422):
                raise ValueError('执行协议或参数不受支持；请核对参数，并确认沙盒控制服务和执行镜像均已更新')
            if response.status_code == 429:
                raise ValueError('代码执行队列已满，请稍后重试')
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as error:
            raise ProviderError('network', '代码执行服务暂时无法连接，请稍后重试') from error

    async def submit(self, body):
        return await self.request('POST', '/executions', body)

    async def read(self, identifier):
        return await self.request('GET', '/executions/' + identifier)

    async def cancel(self, identifier):
        return await self.request('POST', '/executions/' + identifier + '/cancel')

    async def release(self, identifier):
        return await self.request('DELETE', '/executions/' + identifier)

    async def file(self, identifier, metadata):
        try:
            data = bytearray()
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                async with client.stream('GET', self.url + '/executions/' + identifier + '/files/' + metadata['id'], headers={'Authorization': 'Bearer ' + self.token}) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > min(metadata['size'], 32 * 1024 * 1024):
                            raise ValueError('生成文件超过大小限制')
            if len(data) != metadata['size'] or hashlib.sha256(data).hexdigest() != metadata['sha256']:
                raise ValueError('生成文件校验失败')
            return bytes(data)
        except httpx.HTTPError as error:
            raise ProviderError('network', '生成文件传输失败，请稍后重试') from error

    async def best_effort(self, operation, identifier):
        try:
            async with asyncio.timeout(8):
                await getattr(self, operation)(identifier)
        except Exception:
            pass
