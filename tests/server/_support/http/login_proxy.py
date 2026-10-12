"""Run current API code behind the production Caddy rules in owned containers."""
from contextlib import asynccontextmanager
import asyncio
import os
from pathlib import Path
import socket
import subprocess
from uuid import uuid4

import httpx
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[4]


def docker(*args):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr[:2000])
    return result.stdout.strip()


@asynccontextmanager
async def login_proxy(settings, company_id, directory):
    prefix = 'noria-login-test-' + uuid4().hex[:10]
    network, backend, api, web = (prefix + suffix for suffix in ('-proxy', '-backend', '-api', '-web'))
    proxy_ip = '172.30.254.2'
    with socket.socket() as port:
        port.bind(('127.0.0.1', 0))
        number = port.getsockname()[1]
    origin = f'http://127.0.0.1:{number}'
    db_url = make_url(settings.database_url)
    if db_url.database != 'paa_company_test':
        raise RuntimeError('Refusing proxy rehearsal outside paa_company_test')
    # Docker Desktop forwards this host-only PostgreSQL port without publishing
    # the test API itself. The application source and fixtures are read-only.
    db_url = db_url.set(host='host.docker.internal')
    env = directory / 'api.env'
    values = {
        'DATABASE_URL': db_url.render_as_string(hide_password=False),
        'PAA_TEST_LOGIN_PROXY': '1', 'PAA_WEB_ORIGIN': origin,
        'PAA_LOGIN_COMPANY_ID': company_id, 'PAA_COOKIE_SECURE': 'false',
        'PAA_MODEL_KEY_FILE': '/test/master.key', 'PAA_MEDIA_DIR': '/tmp/login-media',
        'PAA_AGENT_API_KEY': '', 'PAA_AGENT_BASE_URL': '', 'PAA_ASR_API_KEY': '',
        'PAA_ASR_BASE_URL': '', 'PAA_SANDBOX_URL': '', 'PAA_REPLY_STREAM_REDIS_URL': '',
        'FORWARDED_ALLOW_IPS': proxy_ip,
        'PYTHONPATH': '/app/apps/server:/app/packages/voiceprint-engine/src:/app/tests/server:/app/tests/server/probes',
    }
    env.write_text(''.join(f'{k}={v}\n' for k, v in values.items()))
    env.chmod(0o600)
    caddy = directory / 'Caddyfile'
    caddy.write_text(':80 {\n import /etc/caddy/Caddyfile.app\n}\n')
    created, networks = [], []
    try:
        docker('network', 'create', '--subnet', '172.30.254.0/29', network)
        networks.append(network)
        docker('network', 'create', backend)
        networks.append(backend)
        image = os.environ['PAA_TEST_LOGIN_PROXY_IMAGE']
        args = ['run', '-d', '--name', api, '--network', backend, '--env-file', str(env),
                '--user', f'{os.getuid()}:{os.getgid()}']
        for local, remote in [
            (ROOT / 'apps/server/app', '/app/apps/server/app'),
            (ROOT / 'packages', '/app/packages'),
            (ROOT / 'tests/server', '/app/tests/server'),
            (settings.model_key_file, '/test/master.key'),
        ]:
            args += ['-v', f'{local}:{remote}:ro']
        docker(*args, '--entrypoint', 'python', image, '-m', 'uvicorn', 'login_proxy_probe:app',
               '--host', '0.0.0.0', '--port', '8000')
        created.append(api)
        docker('network', 'connect', '--ip', '172.30.254.3', '--alias', 'api', network, api)
        docker('run', '-d', '--name', web, '--network', network, '--ip', proxy_ip,
               '-p', f'127.0.0.1:{number}:80', '-v', f'{caddy}:/etc/caddy/Caddyfile:ro',
               '-v', f'{ROOT / "deploy/company/Caddyfile.app"}:/etc/caddy/Caddyfile.app:ro',
               'caddy:2.10.2-alpine')
        created.append(web)
        async with httpx.AsyncClient(base_url=origin, timeout=3, trust_env=False) as client:
            for _ in range(100):
                try:
                    ready = await client.get('/api/v1/health')
                    if ready.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(.1)
            else:
                raise RuntimeError('Owned API did not start: ' + docker('logs', api)[-1500:])
        yield origin, proxy_ip
    finally:
        for name in reversed(created):
            docker('rm', '-f', name)
        for name in reversed(networks):
            docker('network', 'rm', name)
        env.unlink(missing_ok=True)
