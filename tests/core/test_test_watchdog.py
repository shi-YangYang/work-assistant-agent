"""Exercise the test watchdog in owned subprocesses; no models, devices or user data."""
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


RUNNER = Path(__file__).resolve().parents[2] / 'scripts/desktop/test-python.py'


class TestWatchdogTests(unittest.TestCase):
    def run_fixture(self, source, *, timeout=1):
        code = (
            'import runpy, time, unittest\n'
            f'run_tests = runpy.run_path({str(RUNNER)!r})["run_tests"]\n'
            + textwrap.dedent(source)
            + '\nsuite = unittest.defaultTestLoader.loadTestsFromTestCase(Fixture)\n'
            + f'result = run_tests(suite, timeout={timeout!r})\n'
            + 'raise SystemExit(not result.wasSuccessful())\n'
        )
        return subprocess.run(
            [sys.executable, '-c', code], capture_output=True, text=True, timeout=15,
        )

    def test_successful_progress_can_outlast_one_watchdog_window(self):
        result = self.run_fixture('''
            class Fixture(unittest.TestCase):
                def test_first(self): time.sleep(.4)
                def test_second(self): time.sleep(.4)
                def test_third(self): time.sleep(.4)
        ''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Ran 3 tests', result.stderr)
        self.assertNotIn('Timeout', result.stderr)

    def test_stalled_test_and_class_fixtures_still_fail_with_a_traceback(self):
        for phase in ('test_stalled', 'setUpClass', 'tearDownClass'):
            with self.subTest(phase=phase):
                decorator = '' if phase == 'test_stalled' else '    @classmethod\n'
                source = (
                    'class Fixture(unittest.TestCase):\n'
                    '    def test_stalled(self): pass\n'
                    + decorator
                    + f'    def {phase}(self): time.sleep(10)\n'
                )
                result = self.run_fixture(source, timeout=.2)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('Timeout', result.stderr)
                self.assertIn(phase, result.stderr)

    def test_assertion_failures_keep_a_nonzero_exit_status(self):
        result = self.run_fixture('''
            class Fixture(unittest.TestCase):
                def test_failure(self): self.fail('fixture failure')
        ''')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('fixture failure', result.stderr)
        self.assertIn('FAILED (failures=1)', result.stderr)
        self.assertNotIn('Timeout', result.stderr)


if __name__ == '__main__':
    unittest.main()
