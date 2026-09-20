from datetime import timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.engine import Engine

from paa_server.models import Job, ReportRevision
from test_team_workspace import DAY, report

pytestmark = pytest.mark.asyncio


async def test_report_lists_batch_queries_preserve_history_and_private_boundaries(setup):
    _, sessions, users, clients = setup
    rows = []
    async with sessions.begin() as db:
        for index in range(55):
            rows.append(await report(db, users['employee'], (DAY + timedelta(days=index)).date().isoformat()))
        await report(db, users['peer'], '2026-09-12')
        await report(db, users['outsider'], '2026-09-12')
        latest = rows[-1]
        latest.published_revision, latest.revision = 2, 3
        latest.content = {'completed': '本人未提交修改', 'ongoing': '', 'blockers': '', 'next': ''}
        latest.candidate = {'content': {'completed': '本人候选结果'}, 'sourceIds': []}
        db.add(ReportRevision(company_id=latest.company_id, owner_id=latest.owner_id, report_id=latest.id, revision=2, content={'completed': '已提交最终版本', 'ongoing': '', 'blockers': '', 'next': ''}, source_ids=[], created_at=DAY + timedelta(days=56)))
        db.add(Job(company_id=latest.company_id, owner_id=latest.owner_id, kind='report', target_id=latest.id, state='failed', created_at=DAY))
        job = Job(company_id=latest.company_id, owner_id=latest.owner_id, kind='report', target_id=latest.id, state='queued', created_at=DAY + timedelta(days=57))
        db.add(job)
    async def counted(client, path):
        statements = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(Engine, 'before_cursor_execute', capture)
        try:
            response = await client.get(path)
        finally:
            event.remove(Engine, 'before_cursor_execute', capture)
        assert response.status_code == 200, response.text
        revisions = [s for s in statements if 'FROM company_report_revision' in s]
        jobs = [s for s in statements if 'FROM company_job' in s]
        assert len(revisions) == 1
        assert len(jobs) == (1 if client == clients['employee'] else 0)
        assert len(statements) <= 9, len(statements)
        print(f'{path}: {len(statements)} SQL statements for 50 reports')
        return response.json()
    own = await counted(clients['employee'], '/api/v1/reports')
    assert len(own['items']) == 50 and own['nextCursor']
    first = own['items'][0]
    assert first['id'] == latest.id and first['content'] == latest.content
    assert first['candidate'] == latest.candidate and first['job']['id'] == job.id
    assert first['job']['state'] == 'queued'
    assert [r['revision'] for r in first['revisions']] == [2, 1]
    assert first['ownerName'] == users['employee'].name
    page2 = (await clients['employee'].get('/api/v1/reports', params={'cursor': own['nextCursor']})).json()
    assert len(page2['items']) == 5 and page2['nextCursor'] is None
    assert {r['id'] for r in own['items'] + page2['items']} == {r.id for r in rows}
    path = '/api/v1/team/members/' + users['employee'].id + '/reports'
    public = await counted(clients['admin'], path)
    first = public['items'][0]
    assert first['content']['completed'] == '已提交最终版本'
    assert first['candidate'] is None and first['job'] is None
    assert first['revision'] == 2 and first['managementRevision'] == 3
    assert '本人未提交修改' not in str(public) and '本人候选结果' not in str(public)
    assert (await clients['peer'].get('/api/v1/reports/' + latest.id)).status_code == 404
    assert (await clients['admin'].get('/api/v1/team/members/' + users['outsider'].id + '/reports')).status_code == 404
    historic = (await clients['admin'].get('/api/v1/reports/' + latest.id + '?revision=1')).json()
    assert historic['content']['completed'] == '已提交内容' and historic['historical']
