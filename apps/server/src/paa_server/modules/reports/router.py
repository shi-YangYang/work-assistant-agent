from .commands import adopt_candidate_command, submit_command
from .queries import get_report_query, report_sources_query, reports_query
from fastapi import APIRouter, Header, Query
from paa_server.core.schemas import Revision
from paa_server.db.idempotency import idem_begin, idem_save
from paa_server.http.dependencies import AUTH, DB, SETTINGS
from paa_server.modules.operations.writes import deletion_impact as writes_deletion_impact, remove_record as writes_remove_record
from paa_server.modules.reports.models import Report
from paa_server.modules.reports.queries import report_dto
from paa_server.modules.reports.schemas import GenerateReport, ReportEdit
from paa_server.modules.reports.service import edit_report as writes_edit_report, ensure_report
from paa_server.security.ownership import owned
from paa_server.tasks.cleanup import finish_deletion
from typing import Annotated

router = APIRouter()


@router.get('/api/v1/reports')
async def reports(kind: str = 'daily', cursor: str | None = None, actor=AUTH, db=DB):
    return await reports_query(kind, cursor, actor, db)


@router.get('/api/v1/reports/{identifier}')
async def get_report(identifier: str, revision: int | None = Query(None, ge=1), actor=AUTH, db=DB):
    return await get_report_query(identifier, revision, actor, db)


@router.get('/api/v1/reports/{identifier}/sources')
async def report_sources(identifier: str, revision: int | None = Query(None, ge=1), actor=AUTH, db=DB):
    return await report_sources_query(identifier, revision, actor, db)


@router.post('/api/v1/reports/generate', status_code=202)
async def generate_report(body: GenerateReport, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB):
    prior, digest = await idem_begin(db, actor, 'generate-report', idempotency_key, body.model_dump(mode='json'))
    if prior:
        return prior
    report, job = await ensure_report(db, actor, body.kind, body.date)
    return idem_save(db, actor, 'generate-report', idempotency_key, digest, {'reportId': report.id, 'jobId': job.id})


@router.patch('/api/v1/reports/{identifier}')
async def edit_report(identifier: str, body: ReportEdit, actor=AUTH, db=DB):
    report = await writes_edit_report(db, actor, identifier, body.expectedRevision, body.content.model_dump())
    return await report_dto(db, report, actor)


@router.post('/api/v1/reports/{identifier}/candidate')
async def adopt_candidate(identifier: str, body: Revision, actor=AUTH, db=DB):
    return await adopt_candidate_command(identifier, body, actor, db)


@router.post('/api/v1/reports/{identifier}/submit')
async def submit(identifier: str, body: Revision, idempotency_key: Annotated[str | None, Header()] = None, actor=AUTH, db=DB):
    return await submit_command(identifier, body, idempotency_key, actor, db)


@router.get('/api/v1/reports/{identifier}/deletion')
async def report_deletion(identifier: str, actor=AUTH, db=DB):
    item = await owned(db, Report, identifier, actor, read=True)
    impact = await writes_deletion_impact(db, item, actor)
    return {key: impact[key] for key in ('messages', 'attachments', 'revision')}


@router.delete('/api/v1/reports/{identifier}')
async def delete_report(identifier: str, body: Revision, actor=AUTH, db=DB, settings=SETTINGS):
    item = await writes_remove_record(db, actor, 'report', identifier, body.expectedRevision)
    return await finish_deletion(db, item.owner_id, settings)
