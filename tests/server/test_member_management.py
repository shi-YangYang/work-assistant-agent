import pytest
from sqlalchemy import select

from app.modules.auth.models import Session
from app.modules.members.models import Member
from app.modules.reports.models import ReportEligibility

pytestmark = pytest.mark.asyncio


async def test_member_list_exposes_created_date_only_on_list_and_name_update_preserves_access(setup, monkeypatch):
    _, sessions, users, clients = setup
    employee = users['employee']
    result = await clients['admin'].get('/api/v1/members')
    items = result.json()['items']
    assert {item['id'] for item in items} == {employee.id, users['peer'].id}
    item = next(item for item in items if item['id'] == employee.id)
    assert item['createdAt'] == employee.created_at.isoformat()
    assert 'createdAt' not in (await clients['employee'].get('/api/v1/auth/me')).json()['member']
    async with sessions() as db:
        session_ids = (await db.scalars(select(Session.id).where(Session.member_id == employee.id))).all()
        eligibility_ids = (await db.scalars(select(ReportEligibility.id).where(ReportEligibility.owner_id == employee.id))).all()
    async def forbidden(*args):
        pytest.fail('name editing must not recalculate eligibility or revoke sessions')
    monkeypatch.setattr('app.modules.members.commands.reporting_eligibility_changed', forbidden)
    monkeypatch.setattr('app.modules.members.commands.revoke_member', forbidden)
    response = await clients['admin'].patch('/api/v1/members/' + employee.id, json={'name': '  新姓名  '})
    assert response.status_code == 200, response.text
    assert response.json()['name'] == '新姓名'
    async with sessions() as db:
        stored = await db.get(Member, employee.id)
        assert stored.name == '新姓名'
        for field in ('username', 'company_id', 'role', 'active', 'password_hash', 'created_at'):
            assert getattr(stored, field) == getattr(employee, field)
        assert (await db.scalars(select(Session.id).where(Session.member_id == employee.id))).all() == session_ids
        assert (await db.scalars(select(ReportEligibility.id).where(ReportEligibility.owner_id == employee.id))).all() == eligibility_ids
    assert (await clients['employee'].get('/api/v1/auth/me')).status_code == 200


@pytest.mark.parametrize('body', [{}, {'name': None}, {'name': ''}, {'name': '  '}, {'name': 'x' * 81}, {'active': False}, {'name': '合法', 'active': True}, {'name': '合法', 'role': 'admin'}])
async def test_name_patch_rejects_invalid_and_retired_fields(setup, body):
    _, sessions, users, clients = setup
    response = await clients['admin'].patch('/api/v1/members/' + users['employee'].id, json=body)
    assert response.status_code == 422, response.text
    if 'active' not in body and 'role' not in body:
        assert 'name' in response.json()['error']['fieldErrors']
    async with sessions() as db:
        stored = await db.get(Member, users['employee'].id)
        assert stored.name == users['employee'].name and stored.active


async def test_member_name_patch_enforces_role_company_and_deleted_boundaries(setup):
    _, _, users, clients = setup
    path = '/api/v1/members/' + users['employee'].id
    assert (await clients['employee'].patch(path, json={'name': '禁止'})).status_code == 403
    for target in ('admin', 'outsider'):
        assert (await clients['admin'].patch('/api/v1/members/' + users[target].id, json={'name': '禁止'})).status_code == 404
    assert (await clients['admin'].delete(path)).status_code == 200
    assert (await clients['admin'].patch(path, json={'name': '禁止'})).status_code == 404
