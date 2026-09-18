"""Exercise the actual rsync transfer with SSH redirected to a temporary local host."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
RSYNC = shutil.which('rsync')
MODERN_RSYNC = RSYNC and re.search(
    r'rsync\s+version\s+3\.',
    subprocess.check_output([RSYNC, '--version'], text=True),
)


@unittest.skipUnless(MODERN_RSYNC, 'The deployment runner requires rsync 3')
class UploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='paa-upload-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        (self.source / 'deploy/company').mkdir(parents=True)
        (self.source / 'package.json').write_text('{}')
        (self.source / 'deploy/company/Dockerfile').write_text('FROM scratch\n')
        (self.source / 'model.bin').write_bytes(os.urandom(256 * 1024))
        (self.source / 'app.txt').write_text('before')
        (self.source / 'deleted.txt').write_text('obsolete')
        (self.source / 'run.sh').write_text('#!/bin/sh\nexit 0\n')
        (self.source / 'run.sh').chmod(0o755)
        (self.source / 'model-link').symlink_to('model.bin')
        self.host = self.root / 'server'
        binaries = self.root / 'bin'
        binaries.mkdir()
        ssh = binaries / 'ssh'
        ssh.write_text('''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
while args[0].startswith('-'):
    args = args[2:]
assert args.pop(0) in ('tester@example.test', 'example.test')
if len(args) == 1:
    os.execv('/bin/sh', ['sh', '-c', args[0]])
os.execvp(args[0], args)
''')
        ssh.chmod(0o755)
        rsync = binaries / 'rsync'
        rsync.write_text(f'''#!/usr/bin/env python3
import os, sys
if os.getenv('FAIL_UPLOAD') == '1': sys.exit(23)
os.execv({RSYNC!r}, [{RSYNC!r}, *sys.argv[1:]])
''')
        rsync.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(binaries) + os.pathsep + os.environ['PATH']}

    def upload(self, attempt, fail=False):
        release_id = 'a' * 40 + f'-{attempt}-1'
        destination = self.host / 'releases' / release_id
        result = subprocess.run(
            ['bash', str(REPO / 'deploy/company/upload.sh'), str(self.source),
             'tester@example.test', str(self.host), release_id, '-p', '22'],
            env={**self.env, 'FAIL_UPLOAD': '1' if fail else '0'},
            capture_output=True, text=True, timeout=20,
        )
        return result, destination

    def test_full_then_incremental_reuses_legacy_source_and_preserves_old_release(self):
        first, previous = self.upload(1)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn('uploading the first copy', first.stdout)
        self.assertTrue((previous / '.source-complete').exists())
        self.assertEqual(previous.stat().st_mode & 0o777, 0o700)
        self.assertEqual((previous / 'model.bin').read_bytes(), (self.source / 'model.bin').read_bytes())
        # Migrate from archive-based releases without copying credentials or generated files.
        (previous / '.source-complete').unlink()
        (previous / '.release.env').write_text('generated manifest')
        (previous / '.env.company').write_text('server-only configuration')
        incomplete = self.host / 'releases' / ('b' * 40 + '-3-1')
        shutil.copytree(self.source, incomplete, symlinks=True)
        (incomplete / 'model.bin').write_bytes(b'incomplete')
        os.utime(incomplete, (2000000000, 2000000000))
        (self.source / 'deleted.txt').unlink()
        (self.source / 'app.txt').write_text('after!')
        (self.source / 'added.txt').write_text('new')
        # Git archive changes mtimes even when the model contents remain identical.
        os.utime(self.source / 'model.bin', (1900000000, 1900000000))
        # Equal size and timestamp must not hide a real content change.
        stamp = (previous / 'app.txt').stat().st_mtime
        os.utime(self.source / 'app.txt', (stamp, stamp))
        result, current = self.upload(2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Reusing source files from ' + previous.name, result.stdout)
        self.assertIn('Number of regular files transferred: 2', result.stdout)
        self.assertIn('Literal data: 9 bytes', result.stdout)
        self.assertEqual((current / 'app.txt').read_text(), 'after!')
        self.assertEqual((previous / 'app.txt').read_text(), 'before')
        self.assertTrue((previous / 'deleted.txt').exists())
        for name in ('deleted.txt', '.env.company', '.release.env'):
            self.assertFalse((current / name).exists())
        self.assertEqual((current / 'model.bin').read_bytes(), (previous / 'model.bin').read_bytes())
        self.assertNotEqual((current / 'model.bin').stat().st_ino, (previous / 'model.bin').stat().st_ino)
        self.assertEqual(os.readlink(current / 'model-link'), 'model.bin')
        self.assertEqual((current / 'run.sh').stat().st_mode & 0o777, 0o755)

    def test_interrupted_transfer_is_not_marked_complete(self):
        result, destination = self.upload(1, fail=True)
        self.assertEqual(result.returncode, 23)
        self.assertFalse((destination / '.source-complete').exists())
        self.assertNotIn('Source upload complete', result.stdout)

    def test_existing_release_cannot_be_overwritten(self):
        first, destination = self.upload(1)
        self.assertEqual(first.returncode, 0, first.stderr)
        (self.source / 'app.txt').write_text('changed')
        second, _ = self.upload(1)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual((destination / 'app.txt').read_text(), 'before')


if __name__ == '__main__':
    unittest.main()
