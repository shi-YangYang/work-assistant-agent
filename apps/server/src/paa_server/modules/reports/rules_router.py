from fastapi import APIRouter
from paa_server.core.versions import version
from paa_server.db.base import now
from paa_server.http.dependencies import ADMIN, AUTH, DB
from paa_server.modules.members.models import Company
from paa_server.modules.reports.schedule import effective_periods as reporting_effective_periods, save_schedule as reporting_save_schedule
from paa_server.modules.reports.schemas import Rules
from sqlalchemy import select

router = APIRouter()


@router.get('/api/v1/settings/report-rules')
async def get_rules(actor=AUTH, db=DB):
    company = await db.get(Company, actor.company_id)
    return {**company.rules, 'revision': company.revision, 'effectivePeriods': await reporting_effective_periods(db, company)}


@router.put('/api/v1/settings/report-rules')
async def save_rules(body: Rules, actor=ADMIN, db=DB):
    company = await db.scalar(select(Company).where(Company.id == actor.company_id).with_for_update())
    version(company, body.expectedRevision)
    company.rules, company.rules_effective_at = body.model_dump(exclude={'expectedRevision'}), now()
    company.revision += 1
    await reporting_save_schedule(db, company)
    return {**company.rules, 'revision': company.revision, 'effectivePeriods': await reporting_effective_periods(db, company)}
