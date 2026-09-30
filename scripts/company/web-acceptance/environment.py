"""Opt-in isolated environments for Web acceptance; never mutates business DBs.

prepare writes public metadata plus a mode-0600 environment/account file. Commands
run through exec inherit only the isolated DB, media, key and external-service
settings. Cleanup verifies the exact schema's ownership marker before dropping it.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'apps/server'), str(ROOT / 'packages/voiceprint-engine/src')]
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema


def checked_url(raw):
    url = make_url(raw).set(drivername='postgresql+psycopg')
    if url.database != 'paa_company_test' or url.host not in ('localhost', '127.0.0.1', '::1'):
        raise RuntimeError('Acceptance requires local dedicated paa_company_test')
    return url


def private_json(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def load_environment(path):
    path = Path(path).resolve()
    metadata = json.loads(path.read_text())
    secret = Path(metadata['secretFile']).resolve()
    if secret.stat().st_mode & 0o077:
        raise RuntimeError('Private environment must have mode 0600')
    values = json.loads(secret.read_text())
    url = checked_url(values['environment']['DATABASE_URL'])
    schema = metadata['schema']
    if not re.fullmatch(r'spec044_[a-z]+_[a-f0-9]{12}', schema):
        raise RuntimeError('Unexpected acceptance schema')
    if url.query.get('options') != '-csearch_path=' + schema:
        raise RuntimeError('Schema mismatch')
    engine = create_engine(url)
    with engine.connect() as connection:
        marker = connection.scalar(text("SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname=:schema"), {'schema': schema})
    engine.dispose()
    if marker != 'spec044:' + metadata['runId']:
        raise RuntimeError('Ownership marker mismatch')
    return metadata, values


async def seed():
    from app.core.config import Settings
    from app.db.session import database
    from app.db import registry
    from app.modules.members.models import Company, Member
    from app.modules.work.models import WorkItem, WorkRevision
    from pwdlib import PasswordHash
    settings = Settings()
    engine, sessions = database(settings)
    password = secrets.token_urlsafe(18)
    hashed = PasswordHash.recommended().hash(password)
    accounts, companies = {}, {}
    async with sessions.begin() as db:
        for label in ('primary', 'other', 'real'):
            company = Company(name='Spec044 合成公司 ' + label, environment_models=False)
            db.add(company)
            await db.flush()
            companies[label] = company.id
            roles = ('admin', 'employee', 'peer', 'disabled', 'deleted') if label == 'primary' else (('other_admin', 'outsider') if label == 'other' else ('realAdmin', 'realEmployee'))
            for role in roles:
                member = Member(company_id=company.id, username='spec044_' + role.lower() + '_' + uuid4().hex[:6], name='合成测试 ' + role, role='admin' if role.lower().endswith('admin') else 'employee', password_hash=hashed, active=role not in ('disabled', 'deleted'), deleted=role == 'deleted')
                db.add(member)
                await db.flush()
                accounts[role] = {'id': member.id, 'companyId': company.id, 'username': member.username, 'password': password, 'role': member.role}
                if role in ('employee', 'peer', 'admin'):
                    content = {'title': '合成验收工作 ' + role, 'summary': '仅用于独立验收环境', 'status': 'in_progress', 'blocker': '', 'nextStep': '核对测试结果'}
                    work = WorkItem(company_id=company.id, owner_id=member.id, title=content['title'], content=content)
                    db.add(work)
                    await db.flush()
                    db.add(WorkRevision(company_id=company.id, owner_id=member.id, work_id=work.id, revision=1, content=content, source_ids=[]))
    await engine.dispose()
    return companies, accounts


def prepare(args):
    defaults = dotenv_values(ROOT / 'apps/server/.env.web')
    base = checked_url(os.environ.get('DATABASE_TEST_URL') or defaults.get('DATABASE_TEST_URL', ''))
    run_id = uuid4().hex
    schema = 'spec044_' + args.purpose + '_' + run_id[:12]
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or (output.parent / 'credentials.json').exists():
        raise RuntimeError('Refusing to overwrite an existing environment manifest or credentials')
    directory = Path(tempfile.mkdtemp(prefix=schema + '_')).resolve()
    scoped = base.update_query_dict({'options': '-csearch_path=' + schema}).render_as_string(hide_password=False)
    env = {
        'DATABASE_URL': scoped, 'DATABASE_TEST_URL': scoped,
        'PYTHONPATH': str(ROOT / 'apps/server') + os.pathsep + str(ROOT / 'packages/voiceprint-engine/src'),
        'PAA_MEDIA_DIR': str(directory / 'media'), 'PAA_MODEL_KEY_FILE': str(directory / 'master.key'),
        'PAA_WEB_ORIGIN': args.web_origin, 'PAA_COOKIE_SECURE': 'false', 'PAA_LOGIN_COMPANY_ID': '',
        'PAA_AGENT_BASE_URL': '', 'PAA_AGENT_API_KEY': '', 'PAA_ASR_BASE_URL': '', 'PAA_ASR_API_KEY': '',
        'PAA_SANDBOX_URL': '', 'PAA_SANDBOX_TOKEN': '', 'PAA_MODEL_ALLOWED_ORIGINS': '',
        'PAA_WORKER_CONCURRENCY': '3', 'SPEC044_RUN_ID': run_id,
    }
    metadata = {'runId': run_id, 'purpose': args.purpose, 'database': 'paa_company_test', 'schema': schema,
                'apiUrl': args.api_url, 'webUrl': args.web_origin, 'apiOrigin': args.api_url, 'origin': args.web_origin, 'privateDirectory': str(directory),
                'secretFile': str(directory / 'environment.json'), 'secretEnvFile': str(directory / 'environment.env'),
                'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(), 'processes': []}
    engine = create_engine(base)
    try:
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema))
            connection.execute(text(f"COMMENT ON SCHEMA {schema} IS 'spec044:{run_id}'"))
        os.environ.update(env)
        with output.with_suffix('.setup.log').open('w') as log:
            subprocess.run([sys.executable, '-m', 'app.cli', 'migrate'], cwd=ROOT, env={**os.environ, **env}, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=90)
            subprocess.run([sys.executable, '-m', 'app.cli', 'model-key'], cwd=ROOT, env={**os.environ, **env}, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=30)
        companies, accounts = asyncio.run(seed())
        metadata['companies'] = companies
        metadata['accounts'] = {key: {field: value for field, value in account.items() if field != 'password'} for key, account in accounts.items()}
        private_json(directory / 'environment.json', {'runId': run_id, 'environment': env, 'accounts': accounts})
        credentials = output.parent / 'credentials.json'
        private_json(credentials, {'runId': run_id, 'origin': args.web_origin, 'apiOrigin': args.api_url, 'schema': schema, 'password': next(iter(accounts.values()))['password'], 'users': accounts, 'ids': companies})
        metadata['credentialsFile'] = str(credentials)
        import shlex
        descriptor = os.open(directory / 'environment.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            for key, value in env.items():
                stream.write(f'export {key}={shlex.quote(value)}\n')
        output.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'metadata': str(output), 'schema': schema, 'secretFile': metadata['secretFile'], 'secretEnvFile': metadata['secretEnvFile']}))
    except BaseException:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        shutil.rmtree(directory)
        raise
    finally:
        engine.dispose()


def cleanup(args):
    metadata, private = load_environment(args.metadata)
    directory = Path(metadata['privateDirectory']).resolve()
    credentials = Path(metadata['credentialsFile']).resolve() if metadata.get('credentialsFile') else None
    if not (directory.name.startswith(metadata['schema'] + '_') and directory.parent == Path(tempfile.gettempdir()).resolve()):
        raise RuntimeError('Refusing cleanup of unexpected private directory')
    if credentials and credentials != Path(args.metadata).resolve().parent / 'credentials.json':
        raise RuntimeError('Refusing cleanup of unexpected credentials file')
    engine = create_engine(checked_url(private['environment']['DATABASE_URL']))
    with engine.begin() as connection:
        connection.execute(DropSchema(metadata['schema'], cascade=True))
    engine.dispose()
    shutil.rmtree(directory)
    if credentials:
        credentials.unlink(missing_ok=True)
    metadata['cleaned'] = True
    Path(args.metadata).write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'cleaned': metadata['schema']}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--purpose', choices=['web', 'baseline', 'load', 'recovery'], required=True)
    prep.add_argument('--output', required=True)
    prep.add_argument('--web-origin', default='http://127.0.0.1:5196')
    prep.add_argument('--api-url', default='http://127.0.0.1:8016')
    execute = sub.add_parser('exec')
    execute.add_argument('--metadata', required=True)
    execute.add_argument('args', nargs=argparse.REMAINDER)
    clean = sub.add_parser('cleanup')
    clean.add_argument('--metadata', required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args)
    elif args.command == 'cleanup':
        cleanup(args)
    else:
        metadata, private = load_environment(args.metadata)
        command = args.args[1:] if args.args[:1] == ['--'] else args.args
        if not command:
            parser.error('exec requires a command after --')
        os.execvpe(command[0], command, {**os.environ, **private['environment']})


if __name__ == '__main__':
    main()
