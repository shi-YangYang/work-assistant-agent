"""Remaining destructive-branch assertions from the acceptance inventory."""
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.db.idempotency import Idempotency
from app.modules.reports.models import Report
from _support.http.company import keyed
from _support.http.core_scope_coverage import snapshot

pytestmark = pytest.mark.asyncio


async def test_unknown_progress_action_is_rejected_before_mutation(setup):
    _, sessions, users, clients = setup
    companies = [users['employee'].company_id]
    before = await snapshot(sessions, companies)
    response = await clients['employee'].post('/api/v1/progress-drafts/unrecognized',
        json={'items': [{'id': str(uuid4()), 'expectedRevision': 1}]}, headers=keyed())
    assert response.status_code == 404 and response.json()['error']['message'] == '操作不存在'
    assert await snapshot(sessions, companies) == before


async def test_report_deletion_removes_only_matching_submit_and_generation_idempotency(setup):
    _, sessions, users, clients = setup
    owner = users['employee']
    async with sessions.begin() as db:
        reports = [Report(company_id=owner.company_id, owner_id=owner.id, kind='weekly',
                          period=day, period_end=day, timezone='Asia/Shanghai')
                   for day in ('2026-01-01', '2026-01-02')]
        db.add_all(reports)
        await db.flush()
        target, other = reports
        identifiers = [target.id, other.id]
        for row in reports:
            for action in ('generate-report', 'submit:' + row.id):
                db.add(Idempotency(company_id=owner.company_id, owner_id=owner.id, action=action,
                    key=uuid4().hex, digest='0' * 64, response={'reportId': row.id}))
        # A different action with the same JSON reference and another owner's
        # matching-looking keys must survive the targeted deletion predicate.
        db.add(Idempotency(company_id=owner.company_id, owner_id=owner.id, action='other-action',
            key=uuid4().hex, digest='0' * 64, response={'reportId': target.id}))
        db.add(Idempotency(company_id=owner.company_id, owner_id=users['peer'].id, action='submit:' + target.id,
            key=uuid4().hex, digest='0' * 64, response={'reportId': target.id}))
    response = await clients['employee'].request('DELETE', '/api/v1/reports/' + identifiers[0], json={'expectedRevision': 1})
    assert response.status_code == 200, response.text
    async with sessions() as db:
        rows = (await db.scalars(select(Idempotency).where(Idempotency.company_id == owner.company_id))).all()
        assert {(row.owner_id, row.action, row.response['reportId']) for row in rows} == {
            (owner.id, 'generate-report', identifiers[1]),
            (owner.id, 'submit:' + identifiers[1], identifiers[1]),
            (owner.id, 'other-action', identifiers[0]),
            (users['peer'].id, 'submit:' + identifiers[0], identifiers[0]),
        }
        assert (await db.get(Report, identifiers[0])).deleted
        assert not (await db.get(Report, identifiers[1])).deleted
