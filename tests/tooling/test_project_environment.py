"""Disposable test environment guards fail before destructive actions."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[2] / 'scripts/company/web-acceptance/environment.py'
spec = importlib.util.spec_from_file_location('project_environment', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Guards(unittest.TestCase):
    def test_redis_inheritance_disabled_and_namespaces_isolated(self):
        inherited = {'PAA_REPLY_STREAM_REDIS_URL': 'redis://daily.invalid:6379/0', 'PAA_REPLY_STREAM_NAMESPACE': 'daily'}
        self.assertEqual(module.redis_environment(inherited, 'one')['PAA_REPLY_STREAM_REDIS_URL'], '')
        explicit = {**inherited, 'PAA_REPLY_STREAM_TEST_URL': 'redis://127.0.0.1:62379/0'}
        one = module.redis_environment(explicit, 'one')
        two = module.redis_environment(explicit, 'two')
        self.assertNotEqual(one['PAA_REPLY_STREAM_NAMESPACE'], two['PAA_REPLY_STREAM_NAMESPACE'])
        for target in ['redis://daily.invalid:6379/0', 'redis://127.0.0.1/0', 'http://127.0.0.1:6379/0']:
            with self.assertRaises(RuntimeError):
                module.redis_environment({'PAA_REPLY_STREAM_TEST_URL': target}, 'one')

    def test_direct_wrappers_reject_remote_redis_before_prepare(self):
        import subprocess
        import sys
        for wrapper in ('web-run.py', 'server-run.py'):
            with tempfile.TemporaryDirectory() as tmp:
                env = {**os.environ, 'PROJECT_TEST_OUTPUT': tmp,
                       'PAA_REPLY_STREAM_TEST_URL': 'redis://unowned.invalid:6379/0'}
                env.pop('PROJECT_TEST_OWNED_GROUP', None)
                result = subprocess.run([sys.executable, str(path.parents[2] / 'testing' / wrapper)], env=env, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('explicit loopback Redis', result.stderr)
                self.assertFalse(Path(tmp, 'environment.json').exists())

    def test_wrong_database_and_nonlocal_host_rejected(self):
        for url in ['postgresql://test@127.0.0.1/paa_company', 'postgresql://test@company.example/paa_company_test']:
            with self.assertRaises(RuntimeError): module.checked_url(url)

    def test_private_run_mismatch_rejected_before_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp, 'environment.json')
            private.write_text(json.dumps({'runId':'different'})); private.chmod(0o600)
            manifest = Path(tmp, 'manifest.json')
            manifest.write_text(json.dumps({'privateDirectory':tmp, 'secretFile':str(private), 'runId':'owned'}))
            with patch.object(module, 'create_engine') as engine:
                with self.assertRaisesRegex(RuntimeError, 'identity mismatch'): module.load_environment(manifest)
                engine.assert_not_called()

    def test_permissions_rejected_before_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp, 'environment.json'); private.write_text('{}'); private.chmod(0o644)
            manifest = Path(tmp, 'manifest.json'); manifest.write_text(json.dumps({'secretFile':str(private)}))
            with patch.object(module, 'create_engine') as engine:
                with self.assertRaisesRegex(RuntimeError, '0600'): module.load_environment(manifest)
                engine.assert_not_called()

if __name__ == '__main__': unittest.main()
