import asyncio
import getpass
from pathlib import Path
import sys
from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pwdlib import PasswordHash
from sqlalchemy import select
from .config import Settings
from .db import database
from .models import Company, Member


async def checkpoints():
    async with AsyncPostgresSaver.from_conn_string(Settings().checkpoint_url) as saver:
        await saver.setup()


async def bootstrap():
    company_name = input('公司名称：').strip()
    username = input('管理员账号（字母、数字、._@-）：').strip().lower()
    name = input('管理员姓名：').strip()
    password = getpass.getpass('管理员密码（至少 12 位）：')
    if password != getpass.getpass('再次输入密码：'):
        raise SystemExit('两次密码不一致')
    from .schemas import MemberCreate
    data = MemberCreate(username=username, name=name, password=password, role='admin')
    engine, sessions = database(Settings())
    async with sessions.begin() as db:
        if await db.scalar(select(Company.id).limit(1)):
            raise SystemExit('公司已经初始化，请使用管理员页面添加成员')
        company = Company(name=company_name or '我的公司')
        db.add(company)
        await db.flush()
        db.add(Member(company_id=company.id, username=data.username, name=data.name, password_hash=PasswordHash.recommended().hash(data.password), role='admin', must_change_password=False))
    await engine.dispose()
    print('管理员已创建。请打开 Web 登录。')


async def prepare_model_key():
    from .model_secrets import initialize_key, SecretUnavailable
    from .models import ModelServiceRevision
    settings = Settings()
    if not settings.model_key_file.exists():
        engine, sessions = database(settings)
        try:
            async with sessions() as db:
                if await db.scalar(select(ModelServiceRevision.id).where(ModelServiceRevision.credential != '').limit(1)):
                    raise SecretUnavailable()
        finally:
            await engine.dispose()
    initialize_key(settings.model_key_file)


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ''
    if action == 'migrate':
        config = Config()
        config.set_main_option('script_location', str(Path(__file__).parent / 'migrations'))
        command.upgrade(config, 'head')
        asyncio.run(checkpoints())
        print('公司数据库与任务状态表已初始化。')
    elif action == 'model-key':
        asyncio.run(prepare_model_key())
        print('模型主密钥文件已就绪；请单独备份并供 API 与 worker 读取。')
    elif action == 'bootstrap-admin':
        asyncio.run(bootstrap())
    else:
        raise SystemExit('Usage: python -m paa_server.cli migrate | bootstrap-admin')


if __name__ == '__main__':
    main()
