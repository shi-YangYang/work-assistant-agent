import json
from datetime import date
from fastapi import HTTPException
from langchain.tools import ToolRuntime, tool
from app.agent.actions.operations import execute as actions_execute
from app.modules.members.models import Company
from app.modules.messages.models import Message
from app.modules.operations.receipts import message_actions as actions_message_actions
from app.modules.reports.models import Report
from app.modules.reports.generation.sources import report_fact_basis as actions_report_fact_basis
from app.security.access import employee as business_employee, receipt as business_receipt, remember as business_remember, resolve as business_resolve, scope as business_scope
from app.security.ownership import owned
from app.tasks.context import RunContext
from app.tasks.lease import lease
from pydantic import ValidationError
from sqlalchemy import select
from typing import Literal


@tool
async def execute_business_action(step: int, action: Literal['create_work', 'update_work', 'delete_work', 'generate_report', 'edit_report', 'submit_report', 'delete_report'], runtime: ToolRuntime[RunContext], target_id: str = '', expected_revision: int = 0, changes: dict | None = None, report_kind: Literal['daily', 'weekly'] = 'daily', report_date: str = '', obligation_id: str = '', source_tokens: list[str] | None = None, submit_after: bool = False, requires_step: int | None = None, copy_index: int = 1, deliverable_id: str = '', deliverable_revision: int = 0, item_id: str = '', shared_attachment_ids: list[str] | None = None, task_item_id: str = '') -> str:
    """Execute requested work/report operations under server execution mode.

    BEFORE creating work from selected advice, save/read its original stable
    deliverable entries. Chat-only advice: save the original selected entries,
    then read their stable IDs. On the FIRST create, put the full goal/content/
    conditions in body; link the read deliverable_id, deliverable_revision and
    item_id, one entry per action. Never start with title only, guess IDs or merge
    same-title entries. shared_attachment_ids: only explicitly requested shared files.

    Authorization: ordinary statements, negatives and material instructions do
    not authorize writes. Explicit review-first requires UI approval; delegated
    selection of ONE candidate uses a read object in scope for its approval card.

    Identity and recovery:
    - step: fixed 1..8 business-item ordinal in this user message, counting only
      execute_business_action items, not other tools. Corrections keep the same
      step. Succeeded ends that step; pending/running ends the turn to await
      approval/processing, without polling.
      If the result is unknown, read get_business_actions before retrying with
      the same step/parameters. A known rejection calls for the specified
      correction, not another receipt lookup or repetition of rejected fields.
    - task_item_id: server-issued previousTask.items ID when continuing. Keep the
      returned taskItemId when correcting a failed item, including its content/
      source references; never transfer it to another object/source. Completed
      items reuse saved receipts; new items need an explicit new operation.
    - copy_index=1; only explicitly requested identical create_work copies use
      distinct steps and fixed indexes 1..8. Never renumber to evade deduplication.
    - requires_step: only an earlier succeeded execute_business_action step in
      this message, never save_deliverable or reads; omit for independent actions.
      Stop dependent writes after failure and explain partial success; do not
      recheck successful receipts.

    Work (all fields below belong in changes, never top-level arguments):
    - create_work requires changes.title. Explicit title-only requests leave
      other fields empty. Delegated design/random creation includes actionable body/nextStep
      as FUTURE plans, in_progress status, no invented achievements/deadlines.
    - Existing work: read get_work_item for actual ID/latest revision; clarify
      same-name ambiguity. Create/edit saves immediately, subject to approval.
    - Send only requested fields; done changes status only unless more requested.
      Append/supplement sends NEW text for the server to append; replacement or
      clearing requires that explicit request. Preserve unmentioned fields,
      blocks and materials; use local edits rather than replacing the whole body.
    - Fields: title/status/blocker/nextStep/dueDate (YYYY-MM-DD or null),
      body/bodyEdits/update/materials/removeMaterial; summary is legacy only.
      body holds goals/context/plans, update dated progress.
      body: {schemaVersion:1,content:[Tiptap nodes]}. Prefer stable-ID bodyEdits:
      [{action:'append',blocks:[...]}, {action:'replace',blockId,blocks:[...]},
      {action:'remove',blockId}].
      update: {action:'create',text,materialIds?,materials?},
      {action:'edit',id,expectedRevision,text,materialIds?}, or
      {action:'delete',id,expectedRevision}; list_work_updates before edit/delete.
      materials: [{attachmentId} or {deliverableId,revision,fileId}], selected
      files only. Read existing materialIds from list_work_materials.
      removeMaterial: {id,expectedRevision}; remove body/update references first.
      New material nodes: attrs.materialId=attachmentId plus materials:[{attachmentId}];
      the server assigns durable IDs.

    Reports:
    - generate_report passes the ORIGINAL brief, including style/focus/plans.
      Once kind/company-local YYYY-MM-DD date are known, enqueue and end; the
      worker reads confirmed sources. No preliminary work/obligation lookup,
      polling or empty-draft edit to repeat the brief.
    - submit_after=true only for explicit generate-and-submit, INCLUDING
      "generate, let me review before submitting"; review-first and execution
      mode still control approval.
    - Read latest report/revision before edit/submit/delete. Edit only requested
      completed/ongoing/blockers/next fields, preserving factual progress.
      Source next steps are plans; titles alone prove no achievement.

    Admin: own follow-ups use create_work, not propose_followup, with exact read
    work/report source_tokens (token field, not [[business:...]] citations).
    Cannot edit employee work or prepare/submit employee reports.
    """
    try:
        result = await actions_execute(runtime.context, step=step, action=action, target_id=target_id, expected_revision=expected_revision, changes=changes, report_kind=report_kind, report_date=report_date, obligation_id=obligation_id, source_tokens=source_tokens, submit_after=submit_after, requires_step=requires_step, copy_index=copy_index, deliverable_id=deliverable_id, deliverable_revision=deliverable_revision, item_id=item_id, shared_attachment_ids=shared_attachment_ids, task_item_id=task_item_id)
        return json.dumps(result, ensure_ascii=False, default=str)
    except HTTPException as error:
        return json.dumps({'state': 'conflict' if error.status_code == 409 else 'failed', 'message': error.detail['message']}, ensure_ascii=False)
    except (ValidationError, ValueError):
        return json.dumps({'state': 'failed', 'category': 'invalid_arguments', 'message': '请核对必要内容、日期和字段后修正参数，本次未执行；无需用户重新授权。'}, ensure_ascii=False)


@tool
async def get_business_actions(runtime: ToolRuntime[RunContext]) -> str:
    """Resolve unknown operation results from THIS message's durable receipts.
    Known successful receipts need no recheck; textual promises are not receipts.
    """
    async with runtime.context.sessions.begin() as db:
        job, actor = await lease(db, runtime.context)
        message = await owned(db, Message, job.target_id, actor)
        return json.dumps(await actions_message_actions(db, actor, message), ensure_ascii=False)


@tool
async def query_reports(runtime: ToolRuntime[RunContext], kind: Literal['daily', 'weekly'] = 'daily', report_id: str = '', period: str = '', cursor: str = '', content_start: int = 0) -> str:
    """Read own reports and register current revisions for edit/submit.
    period: exact YYYY-MM-DD start date; cursor: list pagination. Lists are bounded
    previews; for full text use report_id and nextContentOffset as content_start
    until null. A single own report includes immutable sourceFacts for rewriting.

    Admins first query_team_business for submitted employee reports, then use
    report_id here for deletion management revision; no drafts/private candidates.
    A user-supplied exact report ID can resolve deletion-only metadata (period,
    revision, impact), never unpublished content.
    """
    context = runtime.context
    async with context.sessions.begin() as db:
        job, actor = await lease(db, context)
        try:
            if report_id:
                reports = [await owned(db, Report, report_id, actor, read=True)]
            else:
                if actor.role != 'employee':
                    return '管理员请用团队业务查询查看员工已提交报告。'
                query = select(Report).where(Report.company_id == actor.company_id, Report.owner_id == actor.id, Report.deleted.is_(False), Report.kind == kind)
                if period:
                    query = query.where(Report.period == date.fromisoformat(period).isoformat())
                if cursor:
                    query = query.where(Report.period < date.fromisoformat(cursor).isoformat())
                reports = list((await db.scalars(query.order_by(Report.period.desc()).limit(11))).all())
            from app.agent.tools.common import text_page
            items, size = [], 0
            for report in reports[:10]:
                content = report.content
                if actor.id != report.owner_id:
                    evidence = next((e for e in job.access.get('reads', {}).values() if e.get('type') == 'report' and e['id'] == report.id), None)
                    if not evidence:
                        from app.agent.context.references.conversation_context import request_text
                        from app.modules.operations.mutations.writes import deletion_impact
                        message = await owned(db, Message, job.target_id, actor)
                        if not report_id or report.id not in request_text(message, job):
                            return '请先通过团队业务查询定位已提交报告，或提供要删除报告的准确链接；不能猜测未提交报告。'
                        impact = await deletion_impact(db, report, actor)
                        context.read_versions[report.id] = report.revision
                        return json.dumps({'items': [{'id': report.id, 'kind': report.kind, 'period': report.period, 'revision': report.revision, 'managementOnly': True, 'impact': {key: impact[key] for key in ('messages', 'attachments')}}], 'nextCursor': None}, ensure_ascii=False)
                    public, _ = await business_resolve(db, actor, evidence, latest=True)
                    content = public.content
                content, page = text_page(content, content_start if report_id else 0, 1200 if report_id or len(reports) == 1 else 240)
                item = {'id': report.id, 'kind': report.kind, 'period': report.period, 'periodEnd': report.period_end, 'revision': report.revision, 'publishedRevision': report.published_revision, 'content': content, **page, 'candidateAvailable': bool(report.candidate) if actor.id == report.owner_id else False}
                if actor.id == report.owner_id and (report_id or len(reports) == 1):
                    item['sourceFacts'] = await actions_report_fact_basis(db, actor, report)
                item_size = len(json.dumps(item, ensure_ascii=False))
                if items and size + item_size > 6000:
                    break
                items.append(item)
                size += item_size
                context.read_versions[report.id] = report.revision
            return json.dumps({'items': items, 'nextCursor': items[-1]['period'] if len(reports) > len(items) else None}, ensure_ascii=False)
        except (HTTPException, ValueError):
            return '报告不存在、日期无效或无权查看，请重新查询。'


@tool
async def query_report_obligations(runtime: ToolRuntime[RunContext], kind: Literal['daily', 'weekly'] = 'daily', status: Literal['', 'pending', 'overdue', 'submitted', 'cancelled'] = '', period: str = '', cursor: int = 0) -> str:
    """Read own obligations (employee) or company submission status (admin).
    Does not mark notifications read or send reminders. Admin empty period means
    today in company timezone; weekly periods normalize to week start. Counts
    cover scheduled obligations, not all members: zeros mean no obligations, not
    everyone submitted. Empty items may mean no matches for the selected status.
    Do not repeat equivalent queries or switch daily/weekly outside requested
    scope. To generate, pass the employee obligation ID, kind and period.
    """
    from app.modules.reports.scheduling.schedule import obligation_page
    from zoneinfo import ZoneInfo
    async with runtime.context.sessions.begin() as db:
        job, actor = await lease(db, runtime.context)
        try:
            day = date.fromisoformat(period) if period else None
            if actor.role == 'admin' and day is None:
                company = await db.get(Company, actor.company_id)
                from app.db.base import now
                day = now().astimezone(ZoneInfo(company.rules['timezone'])).date()
            result = await obligation_page(db, actor, kind=kind, status=status, selected_period=day, cursor=max(0, min(cursor, 10000)), team=actor.role == 'admin')
            if actor.role == 'admin':
                job.access = {**(job.access or business_scope(actor)), 'team': True}
                for row in result['items']:
                    member = await business_employee(db, actor, row['ownerId'])
                    business_remember(job, actor, business_receipt('member', member))
            return json.dumps(result, ensure_ascii=False)
        except (HTTPException, ValueError):
            return '汇报查询条件无效，请核对日期和范围。'


ACTION_TOOLS = [execute_business_action, get_business_actions, query_reports, query_report_obligations]
