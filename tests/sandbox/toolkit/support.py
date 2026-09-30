import os
from pathlib import Path
import tempfile
import unittest


class Workspace(unittest.TestCase):
    def setUp(self):
        self.previous = Path.cwd()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for name in ('inputs', 'output', 'tmp'):
            (self.root / name).mkdir()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.previous)
        self.temporary.cleanup()
