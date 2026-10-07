"""Explicit upgrade command; never run from application startup."""
from types import SimpleNamespace

from sqlalchemy import select

from app.modules.members.commands import delete_member_command
from app.modules.members.models import Company, Member
from app.modules.voiceprints.cleanup import drain, summary
from app.security.locks import company_lock


async def cleanup_inactive_members(sessions, settings, *, company_ids=None):
    result = {'deleted': 0, 'skipped': 0, 'failed': 0, 'remaining': 0,
              'cleanupPending': 0, 'cleanupFailed': 0, 'cleanupErrors': 0, 'failures': []}
    async with sessions() as db:
        companies = select(Company.id)
        if company_ids is not None:
            companies = companies.where(Company.id.in_(company_ids))
        scope = (await db.scalars(companies)).all()
        candidates = (await db.execute(select(Member.id, Member.company_id).where(
            Member.company_id.in_(scope), Member.role == 'employee',
            Member.active.is_(False), Member.deleted.is_(False),
        ).order_by(Member.created_at, Member.id))).all()
    for member_id, company_id in candidates:
        try:
            async with sessions.begin() as db:
                # Match account mutations' lock order and recheck after waiting.
                await company_lock(db, company_id)
                await db.scalar(select(Company).where(Company.id == company_id).with_for_update())
                member = await db.scalar(select(Member).where(
                    Member.id == member_id, Member.company_id == company_id,
                    Member.role == 'employee', Member.active.is_(False),
                    Member.deleted.is_(False),
                ).with_for_update())
                if member is None:
                    result['skipped'] += 1
                    continue
                await delete_member_command(member_id, SimpleNamespace(company_id=company_id, role='admin'), db)
            result['deleted'] += 1
        except Exception:
            result['failed'] += 1
            result['failures'].append({'memberId': member_id, 'message': '账号清理失败，请重新执行'})
    # Retry previously committed file intents even when no inactive accounts remain.
    for company_id in scope:
        try:
            await drain(sessions, settings, company_id=company_id)
            async with sessions() as db:
                files = await summary(db, company_id)
                result['cleanupPending'] += files['pending']
                result['cleanupFailed'] += files['failed']
        except Exception:
            result['cleanupErrors'] += 1
            result['failures'].append({'companyId': company_id, 'message': '文件清理状态未完成核对，请重新执行'})
    async with sessions() as db:
        result['remaining'] = len((await db.scalars(select(Member.id).where(
            Member.company_id.in_(scope), Member.role == 'employee',
            Member.active.is_(False), Member.deleted.is_(False),
        ))).all())
    return result
