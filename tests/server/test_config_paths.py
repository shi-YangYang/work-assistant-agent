"""App-local configuration must not relocate existing persistent data."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from app.core import config


def test_environment_loading_is_independent_of_cwd_and_keeps_process_overrides(tmp_path):
    package = tmp_path / 'apps/server/app/core'
    package.mkdir(parents=True)
    shutil.copyfile(config.__file__, package / 'config.py')
    (tmp_path / 'apps/server/.env.web').write_text(
        'PAA_WEB_ORIGIN=https://file.example\nPAA_WORKER_CONCURRENCY=2\n'
        'PAA_MEDIA_DIR=data/company/media\nPAA_MODEL_KEY_FILE=data/company/model-master.key\n'
    )
    # Neither the legacy root file nor the desktop configuration may supply server secrets.
    (tmp_path / '.env.company').write_text('PAA_WORKER_CONCURRENCY=7\n')
    script = (
        'import json; from app.core.config import Settings; s=Settings(); '
        'print(json.dumps([s.web_origin,s.worker_concurrency,str(s.media_dir),str(s.model_key_file)]))'
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith('PAA_')}
    env.update(PYTHONPATH=str(tmp_path / 'apps/server'), PAA_WEB_ORIGIN='https://process.example')
    for cwd in (tmp_path, tmp_path / 'apps/server'):
        output = subprocess.check_output([sys.executable, '-c', script], cwd=cwd, env=env, text=True)
        assert json.loads(output) == [
            'https://process.example', 2,
            str(tmp_path / 'data/company/media'), str(tmp_path / 'data/company/model-master.key'),
        ]


def test_absolute_persistent_paths_are_preserved(monkeypatch, tmp_path):
    monkeypatch.setenv('PAA_MEDIA_DIR', str(tmp_path / 'media'))
    monkeypatch.setenv('PAA_MODEL_KEY_FILE', str(tmp_path / 'private.key'))
    settings = config.Settings()
    assert settings.media_dir == tmp_path / 'media'
    assert settings.model_key_file == tmp_path / 'private.key'
