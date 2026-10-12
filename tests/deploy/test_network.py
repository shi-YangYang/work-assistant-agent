"""Exercise production address allocation with owned, lightweight Docker containers."""
import ipaddress
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from uuid import uuid4

REPO = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which('docker'), 'Docker is unavailable')
class ProxyNetworkTests(unittest.TestCase):
    def test_api_first_start_and_upgrade_leave_caddy_address_available(self):
        def docker(*args):
            result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.strip()

        project = 'noria-network-test-' + uuid4().hex[:10]
        network = project + '-proxy'
        with tempfile.TemporaryDirectory(prefix=project) as directory:
            root = Path(directory)
            shutil.copytree(REPO / 'deploy/company', root / 'deploy/company')
            (root / 'apps/server').mkdir(parents=True)
            env = root / 'apps/server/.env.web'
            # Let Docker choose a free subnet so the test can coexist with a local deployment.
            docker('network', 'create', network)
            fixture = root / 'network.json'
            compose = ('compose', '-p', project, '-f', str(fixture))
            try:
                info = json.loads(docker('network', 'inspect', network))[0]
                subnet = ipaddress.ip_network(info['IPAM']['Config'][0]['Subnet'])
                web_ip, api_ip = str(subnet[2]), str(subnet[3])
                env.write_text(
                    'POSTGRES_PASSWORD=test-password\nPAA_DOMAIN=company.example\n'
                    f'PAA_MODEL_KEY_HOST_PATH={root}/unused-key\n'
                    f'PAA_PROXY_SUBNET={subnet}\nPAA_PROXY_IP={web_ip}\nPAA_API_PROXY_IP={api_ip}\n'
                )
                resolved = json.loads(docker(
                    'compose', '--env-file', str(env), '-f', str(root / 'deploy/company/compose.yml'),
                    'config', '--format', 'json',
                ))
                services = {}
                for name in ('api', 'worker', 'web'):
                    services[name] = {
                        'image': 'redis:7.4.2-alpine',
                        'entrypoint': ['sleep', '300'],
                        # Only image/process is replaced; network attachments come from production.
                        'networks': resolved['services'][name].get('networks', {'default': {}}),
                    }
                services['web']['depends_on'] = ['api']
                fixture.write_text(json.dumps({
                    'services': services,
                    'networks': {'default': {}, 'proxy': {'external': True, 'name': network}},
                }))
                docker(*compose, 'up', '-d', 'api')
                docker(*compose, 'up', '-d', 'web')

                def assert_addresses():
                    endpoints = json.loads(docker('network', 'inspect', network))[0]['Containers']
                    addresses = {value['Name']: value['IPv4Address'].split('/')[0]
                                 for value in endpoints.values()}
                    self.assertEqual(addresses, {
                        project + '-api-1': api_ip, project + '-web-1': web_ip,
                    })

                assert_addresses()
                # Upgrade preflight must work while the live API already holds its address.
                docker(*compose, 'run', '--rm', '--no-deps', '-T', '--entrypoint', 'true', 'worker')
                assert_addresses()
                docker(*compose, 'up', '-d', '--force-recreate', 'api', 'web')
                assert_addresses()
            finally:
                try:
                    if fixture.exists():
                        docker(*compose, 'down', '--timeout', '1')
                finally:
                    docker('network', 'rm', network)


if __name__ == '__main__':
    unittest.main()
