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
    if args[:2] == ['login', 'ghcr.io']:
        assert args == ['login', 'ghcr.io', '--username', 'deployment-test', '--password-stdin']
        assert sys.stdin.read().strip() == 'controlled-registry-token'
        config = Path(os.environ['DOCKER_CONFIG'])
        assert config.stat().st_mode & 0o777 == 0o700
        (config / 'config.json').write_text('controlled-registry-token')
        Path(os.environ['REGISTRY_CONFIG_MARKER']).write_text(str(config))
        sys.exit(17 if os.environ.get('FAIL_AT') == 'login' else 0)
    if os.environ.get('REQUIRE_REGISTRY_AUTH'):
        assert (Path(os.environ['DOCKER_CONFIG']) / 'config.json').read_text() == 'controlled-registry-token'
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
            f'PAA_{name}_IMAGE=ghcr.io/example/app-{name.lower()}@sha256:{"a" * 64}\n'
            for name in ('SERVICE', 'WORKER', 'WEB')
        )
        (self.release / '.release.env').write_text(self.manifest)
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

    def run_release(self, failure=None, private=False):
        env = dict(self.env)
        if failure:
            env['FAIL_AT'] = failure
        command = ['bash', str(self.release / 'deploy/company/release.sh'), str(self.root), RELEASE_ID, 'domain']
        if private:
            env['REQUIRE_REGISTRY_AUTH'] = '1'
            command = ['bash', str(REPO / 'deploy/company/with-registry-auth.sh'), 'deployment-test', *command]
        return subprocess.run(
            command, input='controlled-registry-token\n' if private else None,
            env=env, capture_output=True, text=True, timeout=20,
        )

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

    def test_first_release_pulls_digests_and_migrates_before_start(self):
        result = self.run_release()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.commands()
        migrate = next(i for i, c in enumerate(commands) if 'run' in c and c[-1] == 'migrate')
        start = next(i for i, c in enumerate(commands) if 'up' in c and 'worker' in c)
        self.assertLess(migrate, start)
        self.assertFalse(any('--build' in c for c in commands))
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
        for failure in ('pull', 'key'):
            with self.subTest(failure=failure):
                (self.release / '.release.env').write_text(self.manifest)
                (self.release / '.env.company').unlink(missing_ok=True)
                self.log.unlink(missing_ok=True)
                result = self.run_release(failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((self.root / 'current').resolve(), previous)
                self.assertFalse(any('stop' in c or 'migrate' in c for c in self.commands()))

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

    def test_missing_environment_or_invalid_manifest_never_contacts_docker(self):
        self.env_file.unlink()
        self.assertNotEqual(self.run_release().returncode, 0)
        self.env_file.touch()
        (self.release / '.release.env').write_text('PAA_SERVICE_IMAGE=unsafe:latest\n')
        self.assertNotEqual(self.run_release().returncode, 0)
        self.assertFalse(any(c[0] == 'docker' for c in self.commands()))

    def test_private_release_uses_temporary_credentials_even_for_older_releases(self):
        existing_config = self.root / 'docker-config'
        existing_config.mkdir()
        (existing_config / 'config.json').write_text('existing-login')
        marker = self.root / 'registry-config-path'
        self.env.update(DOCKER_CONFIG=str(existing_config), REGISTRY_CONFIG_MARKER=str(marker))
        # A selected historical revision may not contain the authentication wrapper.
        (self.release / 'deploy/company/with-registry-auth.sh').unlink()
        result = self.run_release(private=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(Path(marker.read_text()).exists())
        self.assertEqual((existing_config / 'config.json').read_text(), 'existing-login')
        self.assertNotIn('controlled-registry-token', result.stdout + result.stderr + self.log.read_text())
        self.assertEqual((self.release / 'deployment-status').read_text().strip(), 'ready')

    def test_private_release_cleans_credentials_on_login_pull_or_migration_failure(self):
        marker = self.root / 'registry-config-path'
        self.env['REGISTRY_CONFIG_MARKER'] = str(marker)
        for failure in ('login', 'pull', 'migrate'):
            with self.subTest(failure=failure):
                (self.release / '.release.env').write_text(self.manifest)
                (self.release / '.env.company').unlink(missing_ok=True)
                self.log.unlink(missing_ok=True)
                result = self.run_release(failure, private=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(Path(marker.read_text()).exists())
                self.assertNotIn('controlled-registry-token', result.stdout + result.stderr + self.log.read_text())
                if failure == 'login':
                    self.assertEqual(result.returncode, 17)
                    self.assertEqual(len(self.commands()), 1)
                elif failure == 'pull':
                    self.assertFalse(any('stop' in c or 'migrate' in c for c in self.commands()))

    def test_private_command_receives_no_token_on_stdin_and_cleans_up_on_termination(self):
        marker = self.root / 'registry-config-path'
        result = subprocess.run(
            ['bash', str(REPO / 'deploy/company/with-registry-auth.sh'), 'deployment-test',
             'bash', '-c', 'test -z "$(cat)" || exit 18; kill -TERM "$PPID"'],
            input='controlled-registry-token\n',
            env={**self.env, 'REGISTRY_CONFIG_MARKER': str(marker)},
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 143, result.stderr)
        self.assertFalse(Path(marker.read_text()).exists())
        self.assertNotIn('controlled-registry-token', result.stdout + result.stderr + self.log.read_text())

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
                    self.assertIn('@sha256:', config['services'][name]['image'])
                command = config['services']['web'].get('command')
                if mode == 'ip':
                    self.assertIn('/etc/caddy/Caddyfile.ip', command)
                else:
                    self.assertFalse(command)


if __name__ == '__main__':
    unittest.main()
