"""Release failure boundaries, without connecting to a server or touching real Docker data."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
RELEASE_ID = 'a' * 40 + '-123-1'
MOCK = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
tool = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['DEPLOY_TEST_LOG'], 'a') as output:
    output.write(json.dumps([tool, *args]) + '\\n')
if tool == 'uname':
    print('x86_64')
elif tool == 'mv':
    os.replace(args[-2], args[-1])
elif tool == 'readlink':
    print(Path(args[-1]).resolve())
elif tool == 'sha256sum':
    import hashlib
    for name in args:
        print(hashlib.sha256(Path(name).read_bytes()).hexdigest(), name)
elif tool == 'docker':
    if args[:1] == ['build']:
        target = args[args.index('--target') + 1]
        sys.exit(1 if os.environ.get('FAIL_AT') == 'build-' + target else 0)
    if args[:2] == ['image', 'inspect']:
        print('invalid-image' if os.environ.get('FAIL_AT') == 'image-id' else 'sha256:' + 'a' * 64)
        sys.exit(0)
    if args[:2] == ['volume', 'inspect']:
        sys.exit(0 if os.environ.get('EXISTING_VOLUME') else 1)
    if '--env-file' in args:
        index = args.index('--env-file') + 1
        env_file = Path(args[index])
        if not env_file.exists():
            sys.exit('Missing environment file')
    failure = os.environ.get('FAIL_AT')
    if failure == 'pull' and 'pull' in args:
        sys.exit(1)
    if failure == 'key' and 'run' in args and 'python' in args and 'api' in args:
        sys.exit(1)
    if 'run' in args and 'migrate' in args and failure == 'migrate':
        sys.exit(1)
    if 'exec' in args and 'postgres' in args:
        if failure == 'backup': sys.exit(1)
        print('database-backup')
    elif 'run' in args and 'cat' in args:
        sys.stdout.write('k' * 32)
    elif 'run' in args and 'tar -C /data/media -cf - .' in args:
        print('media-backup')
    elif 'images' in args:
        print('[]')
    elif 'exec' in args and 'api' in args:
        print('https://company.example')
elif tool == 'curl':
    if os.environ.get('FAIL_AT') == 'health': sys.exit(1)
    print('{"status":"ready"}' if args[-1].endswith('/health') else '<html></html>')
'''


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='paa-deploy-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.release = self.root / 'releases' / RELEASE_ID
        shutil.copytree(REPO / 'deploy/company', self.release / 'deploy/company')
        self.env_file = self.root / '.env.company'
        self.env_file.write_text(
            'POSTGRES_PASSWORD=test-password\nPAA_DOMAIN=company.example\n'
            f'PAA_MODEL_KEY_HOST_PATH={self.root}/key\n'
            'PAA_WEB_ORIGIN=https://company.example\n'
        )
        (self.root / 'key').write_bytes(b'k' * 32)
        self.manifest = ''.join(
            f'PAA_{name}_IMAGE=sha256:{"a" * 64}\n'
            for name in ('SERVICE', 'WORKER', 'WEB')
        )
        binaries = self.root / 'bin'
        binaries.mkdir()
        for name in ('docker', 'curl', 'uname', 'flock', 'sleep', 'mv', 'readlink', 'sha256sum'):
            path = binaries / name
            path.write_text(MOCK)
            path.chmod(0o755)
        self.log = self.root / 'commands.jsonl'
        self.env = {
            **os.environ,
            'PATH': str(binaries) + os.pathsep + os.environ['PATH'],
            'DEPLOY_TEST_LOG': str(self.log),
        }

    def run_release(self, failure=None):
        env = dict(self.env)
        if failure:
            env['FAIL_AT'] = failure
        command = ['bash', str(self.release / 'deploy/company/release.sh'), str(self.root), RELEASE_ID, 'domain']
        return subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def previous_release(self):
        self.env['EXISTING_VOLUME'] = '1'
        previous = self.root / 'releases' / 'old'
        shutil.copytree(REPO / 'deploy/company', previous / 'deploy/company')
        (previous / '.env.company').symlink_to(self.env_file)
        (previous / '.release.env').write_text(self.manifest + 'PAA_DEPLOY_MODE=domain\n')
        (self.root / 'current').symlink_to(previous)
        return previous

    def test_first_release_builds_and_pins_images_before_migration(self):
        result = self.run_release()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.commands()
        migrate = next(i for i, c in enumerate(commands) if 'run' in c and c[-1] == 'migrate')
        start = next(i for i, c in enumerate(commands) if 'up' in c and 'worker' in c)
        self.assertLess(migrate, start)
        builds = [c for c in commands if c[:2] == ['docker', 'build']]
        self.assertEqual([c[c.index('--target') + 1] for c in builds], ['service', 'worker', 'web'])
        self.assertTrue(all(commands.index(c) < migrate for c in builds))
        self.assertEqual([c[-1] for c in commands if 'pull' in c], ['postgres'])
        self.assertEqual((self.release / '.release.env').read_text(), self.manifest + 'PAA_DEPLOY_MODE=domain\n')
        self.assertEqual((self.root / 'current').resolve(), self.release)
        self.assertEqual((self.release / 'deployment-status').read_text().strip(), 'ready')

    def test_upgrade_keeps_writers_stopped_between_backup_and_migration(self):
        previous = self.previous_release()
        result = self.run_release()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'previous').resolve(), previous)
        commands = self.commands()
        backup = next(i for i, c in enumerate(commands) if 'pg_dump' in ' '.join(c))
        migrate = next(i for i, c in enumerate(commands) if 'run' in c and c[-1] == 'migrate')
        self.assertLess(backup, migrate)
        self.assertFalse(any('start' in c for c in commands[backup:migrate]))
        self.assertEqual(len(list((self.root / 'backups').glob('company-*/SHA256SUMS'))), 1)
        self.assertEqual(len(list((self.root / 'key-backups').glob('company-*/SHA256SUMS'))), 1)

    def test_preflight_failures_leave_previous_release_running(self):
        previous = self.previous_release()
        for failure in ('build-service', 'build-worker', 'build-web', 'image-id', 'pull', 'key'):
            with self.subTest(failure=failure):
                (self.release / '.release.env').unlink(missing_ok=True)
                (self.release / '.env.company').unlink(missing_ok=True)
                self.log.unlink(missing_ok=True)
                result = self.run_release(failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((self.root / 'current').resolve(), previous)
                self.assertFalse(any('stop' in c or 'migrate' in c for c in self.commands()))
                if failure.startswith('build-') or failure == 'image-id':
                    self.assertFalse((self.release / '.release.env').exists())
                    self.assertFalse((self.release / '.release.env.tmp').exists())

    def test_backup_failure_restores_previous_services_and_never_migrates(self):
        previous = self.previous_release()
        result = self.run_release('backup')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / 'current').resolve(), previous)
        self.assertTrue(any('start' in c for c in self.commands()))
        self.assertFalse(any('migrate' in c for c in self.commands()))

    def test_migration_failure_keeps_application_stopped_without_rollback(self):
        self.previous_release()
        result = self.run_release('migrate')
        self.assertNotEqual(result.returncode, 0)
        commands = self.commands()
        self.assertFalse(any('up' in c and 'api' in c for c in commands))
        self.assertFalse(any('start' in c for c in commands))
        self.assertTrue(any('stop' in c and 'worker' in c for c in commands))
        self.assertEqual((self.release / 'deployment-status').read_text().strip(), 'failed')

    def test_health_failure_does_not_report_success(self):
        result = self.run_release('health')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.release / 'deployment-status').read_text().strip(), 'failed')

    def test_missing_environment_or_reused_release_never_contacts_docker(self):
        self.env_file.unlink()
        self.assertNotEqual(self.run_release().returncode, 0)
        self.env_file.touch()
        (self.release / '.release.env').write_text(self.manifest)
        self.assertNotEqual(self.run_release().returncode, 0)
        self.assertFalse(any(c[0] == 'docker' for c in self.commands()))

    @unittest.skipUnless(shutil.which('docker'), 'Docker Compose CLI is unavailable')
    def test_real_compose_configuration_uses_only_images_and_supports_ip(self):
        for mode in ('domain', 'ip'):
            with self.subTest(mode=mode):
                (self.release / '.release.env').write_text(self.manifest + f'PAA_DEPLOY_MODE={mode}\n')
                (self.release / '.env.company').unlink(missing_ok=True)
                (self.release / '.env.company').symlink_to(self.env_file)
                result = subprocess.run(
                    ['sh', str(self.release / 'deploy/company/compose.sh'), 'config', '--format', 'json'],
                    env={**os.environ, 'PAA_COMPOSE_ROOT': str(self.release)},
                    capture_output=True, text=True, timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                config = json.loads(result.stdout)
                self.assertEqual(config['name'], 'paa-company')
                for name in ('migrate', 'api', 'worker', 'web'):
                    self.assertNotIn('build', config['services'][name])
                    self.assertEqual(config['services'][name]['image'], 'sha256:' + 'a' * 64)
                    self.assertEqual(config['services'][name]['pull_policy'], 'never')
                worker = config['services']['worker']
                self.assertEqual(float(worker['cpus']), 2.0)
                self.assertEqual(int(worker['mem_limit']), 3 * 1024 ** 3)
                self.assertEqual(int(worker['memswap_limit']), int(worker['mem_limit']))
                command = config['services']['web'].get('command')
                if mode == 'ip':
                    self.assertIn('/etc/caddy/Caddyfile.ip', command)
                else:
                    self.assertFalse(command)


if __name__ == '__main__':
    unittest.main()
