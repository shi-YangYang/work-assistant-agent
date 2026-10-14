"""Run desktop tests with a progress watchdog, not one deadline for the entire suite."""
import faulthandler
from pathlib import Path
import unittest


def run_tests(suite=None, *, timeout=120):
    def progress():
        faulthandler.dump_traceback_later(timeout, exit=True)

    class ProgressResult(unittest.TextTestResult):
        def startTest(self, test):
            progress()
            super().startTest(test)

        def stopTest(self, test):
            super().stopTest(test)
            # Class/module setup and cleanup run between tests and also need a deadline.
            progress()

    progress()
    try:
        if suite is None:
            root = Path(__file__).resolve().parents[2]
            suite = unittest.defaultTestLoader.discover(str(root / 'tests/core'))
        return unittest.TextTestRunner(
            verbosity=2, resultclass=ProgressResult, durations=10,
        ).run(suite)
    finally:
        faulthandler.cancel_dump_traceback_later()


if __name__ == '__main__':
    raise SystemExit(not run_tests().wasSuccessful())
