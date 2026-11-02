"""Run desktop tests with a progress watchdog, not one deadline for the entire suite."""
import faulthandler
from pathlib import Path
import unittest
import os
import json


def run_tests(suite=None, *, timeout=120):
    def progress():
        faulthandler.dump_traceback_later(timeout, exit=True)

    cases = []

    class ProgressResult(unittest.TextTestResult):
        def addSuccess(self, test):
            cases.append({"id": test.id(), "status": "passed"})
            super().addSuccess(test)

        def addFailure(self, test, err):
            cases.append({"id": test.id(), "status": "failed"})
            super().addFailure(test, err)

        def addError(self, test, err):
            cases.append({"id": test.id(), "status": "failed"})
            super().addError(test, err)

        def addSkip(self, test, reason):
            cases.append({"id": test.id(), "status": "skipped", "reason": reason})
            super().addSkip(test, reason)

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
        result = unittest.TextTestRunner(
            verbosity=2, resultclass=ProgressResult, durations=10,
        ).run(suite)
        if os.environ.get("PROJECT_TEST_OUTPUT"):
            Path(os.environ["PROJECT_TEST_OUTPUT"], "results.json").write_text(json.dumps({"cases": cases, "complete": result.testsRun == len(cases)}))
        return result
    finally:
        faulthandler.cancel_dump_traceback_later()


if __name__ == '__main__':
    raise SystemExit(not run_tests().wasSuccessful())
