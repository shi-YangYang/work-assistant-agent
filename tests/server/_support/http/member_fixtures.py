"""Construct historical disabled accounts without exposing a retired HTTP operation."""
from app.modules.auth.sessions import revoke_member
from app.modules.members.models import Member
from app.modules.reports.scheduling.schedule import eligibility_changed
from app.security.locks import company_lock


async def set_legacy_active(sessions, member, active=False):
    async with sessions.begin() as db:
        await company_lock(db, member.company_id)
        stored = await db.get(Member, member.id)
        stored.active = active
        await eligibility_changed(db, stored)
        if not active:
            await revoke_member(db, stored.id)
