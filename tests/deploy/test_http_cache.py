"""Check the production Caddy rules over HTTP without company data or services."""
from http.client import RemoteDisconnected
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

REPO = Path(__file__).resolve().parents[2]
IMMUTABLE = 'public, max-age=31536000, immutable'


@unittest.skipUnless(shutil.which('docker'), 'Docker is unavailable')
class HttpCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def docker(*args):
            result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=45)
            if result.returncode:
                raise RuntimeError(result.stderr)
            return result.stdout.strip()

        directory = tempfile.TemporaryDirectory(prefix='noria-http-cache-')
        cls.addClassCleanup(directory.cleanup)
        cls.root = Path(directory.name)
        cls.html = b'<!doctype html><html>Noria cache fixture</html>'
        files = {
            'index.html': cls.html,
            'favicon-32.png': b'png fixture',
            'assets/main-Ab12_cd3.js': b'console.log("versioned asset");',
            'assets/main-Ab12_cd3.css': b'body { color: black; }',
            'assets/bear-Ab12_cd3.png': b'versioned image',
            'assets/font-Ab12_cd3.woff2': b'versioned font',
            'assets/unversioned.js': b'console.log("unversioned");',
            'pdfjs/wasm/openjpeg.wasm': b'wasm fixture',
            'pdfjs/cmaps/Adobe-GB1-UCS2.bcmap': b'cmap fixture',
        }
        for name, data in files.items():
            path = cls.root / 'www' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        # The actual production edge proxies to a separate listener in this owned container.
        (cls.root / 'Caddyfile').write_text('''{
    admin off
    auto_https off
}
:80 {
    import /etc/caddy/Caddyfile.app
}
:8000 {
    header Cache-Control no-store
    handle /api/v1/events {
        header Cache-Control "no-store, no-transform"
        header Content-Type text/event-stream
        respond "data: ready"
    }
    handle /api/v1/file {
        header Cache-Control "private, no-store"
        respond "private file"
    }
    handle /api/v1/missing {
        respond "missing API record" 404
    }
    handle {
        header Content-Type application/json
        respond `{"status":"ready"}`
    }
}
''')
        name = 'noria-http-cache-' + uuid4().hex[:10]
        cls.container = name
        network = docker('network', 'create', name)
        cls.addClassCleanup(docker, 'network', 'rm', network)
        # A failed docker run can leave a created container; clean up only our unique name.
        cls.addClassCleanup(subprocess.run, ['docker', 'rm', '-f', name],
                            capture_output=True, timeout=30)
        docker('run', '-d', '--name', name, '--network', network, '--network-alias', 'api',
               '-p', '127.0.0.1::80',
               '-v', f'{cls.root / "www"}:/srv',
               '-v', f'{cls.root / "Caddyfile"}:/etc/caddy/Caddyfile:ro',
               '-v', f'{REPO / "deploy/company/Caddyfile.app"}:/etc/caddy/Caddyfile.app:ro',
               'caddy:2.10.2-alpine')
        cls.origin = 'http://' + docker('port', name, '80/tcp')
        cls.client = build_opener(ProxyHandler({}))
        for _ in range(50):
            try:
                with cls.client.open(cls.origin + '/', timeout=1):
                    return
            except (URLError, TimeoutError, RemoteDisconnected):
                time.sleep(.1)
        raise RuntimeError('Caddy did not start: ' + docker('logs', name)[-2000:])

    def request(self, path, headers=None, method='GET'):
        request = Request(self.origin + path, headers=headers or {}, method=method)
        try:
            response = self.client.open(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def test_html_routes_revalidate_and_detect_a_new_version(self):
        for path in ('/', '/index.html', '/assistant', '/work/example', '/settings/account?tab=profile'):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertEqual(body, self.html)
                self.assertEqual(headers['Cache-Control'], 'no-cache')
                self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
                status, cached, _ = self.request(path, {'If-None-Match': headers['ETag']})
                self.assertEqual(status, 304)
                self.assertEqual(cached['Cache-Control'], 'no-cache')
        def replace_html(content):
            # Write inside Docker to avoid host bind-mount propagation delays on macOS.
            subprocess.run(['docker', 'exec', '-i', self.container, 'sh', '-c', 'cat > /srv/index.html'],
                           input=content, capture_output=True, timeout=10, check=True)

        replace_html(self.html + b'<!-- new release -->')
        try:
            status, updated, body = self.request('/settings/account', {'If-None-Match': headers['ETag']})
            self.assertEqual(status, 200)
            self.assertNotEqual(updated['ETag'], headers['ETag'])
            self.assertIn(b'new release', body)
        finally:
            replace_html(self.html)

    def test_hashed_assets_are_immutable_including_conditional_and_range_responses(self):
        for name in ('main-Ab12_cd3.js', 'main-Ab12_cd3.css', 'bear-Ab12_cd3.png', 'font-Ab12_cd3.woff2'):
            with self.subTest(name=name):
                status, headers, _ = self.request('/assets/' + name)
                self.assertEqual(status, 200)
                self.assertEqual(headers['Cache-Control'], IMMUTABLE)
                status, cached, _ = self.request('/assets/' + name, {'If-None-Match': headers['ETag']})
                self.assertEqual(status, 304)
                self.assertEqual(cached['Cache-Control'], IMMUTABLE)
        status, headers, body = self.request('/assets/main-Ab12_cd3.js', {'Range': 'bytes=0-6'})
        self.assertEqual(status, 206)
        self.assertEqual(body, b'console')
        self.assertEqual(headers['Cache-Control'], IMMUTABLE)

    def test_fixed_filenames_revalidate(self):
        for path in ('/favicon-32.png?v=noria-2', '/assets/unversioned.js',
                     '/pdfjs/wasm/openjpeg.wasm', '/pdfjs/cmaps/Adobe-GB1-UCS2.bcmap'):
            with self.subTest(path=path):
                status, headers, _ = self.request(path)
                self.assertEqual(status, 200)
                self.assertEqual(headers['Cache-Control'], 'no-cache')

    def test_missing_assets_are_uncached_404_responses_not_html(self):
        for path in ('/assets/removed-Ab12_cd3.js', '/assets/missing', '/pdfjs/missing',
                     '/missing.png', '/missing.js'):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 404)
                self.assertEqual(headers['Cache-Control'], 'no-store')
                self.assertNotIn(b'<html', body)
                self.assertNotIn('text/html', headers.get('Content-Type', ''))

    def test_api_private_files_and_stream_headers_are_preserved(self):
        for path, status, policy in (
            ('/api/v1/health', 200, 'no-store'),
            ('/api/v1/file', 200, 'private, no-store'),
            ('/api/v1/events', 200, 'no-store, no-transform'),
            ('/api/v1/missing', 404, 'no-store'),
        ):
            with self.subTest(path=path):
                actual, headers, body = self.request(path)
                self.assertEqual(actual, status)
                self.assertEqual(headers['Cache-Control'], policy)
                self.assertNotEqual(body, self.html)


if __name__ == '__main__':
    unittest.main()
