import json
from datetime import date
from fastapi import HTTPException
from app.agent.tool_results import http_failure
from app.agent.tools.common import clip
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
    """Perform the user's settled business operation; execution mode and server
    authorization apply; explicit review-first always waits for approval.

    step: stable 1..8 business-action ordinal for this message (not other tools).
    Corrections keep step and returned taskItemId. task_item_id may reuse only
    the same previousTask item/object/workScope; new remaining items leave it empty.
    Pending/running waits, succeeded is not replayed. Unknown results use
    get_business_actions; known failure follows recovery. requires_step is an
    earlier successful business step, omitted for independent actions.
    copy_index=1; only explicitly requested identical copies use fixed 1..8 indexes.

    Work fields go in changes:
    title, status, blocker, nextStep, dueDate (YYYY-MM-DD/null), body/bodyEdits,
    update, materials, removeMaterial; summary is legacy.
    create_work requires title. Title-only leaves other fields empty; delegated
    design includes actionable future plans, never invented achievements/deadlines.
    Create ALL supplied content in one operation. Existing edits require the
    actual read ID/latest expected_revision. Only requested fields change;
    append supplies NEW content, explicit replacement/clearing supplies full value.
    body is {schemaVersion:1,content:[Tiptap nodes]}; prefer local bodyEdits:
    - {action:'append',blocks:[...]}
    - {action:'replace',blockId,blocks:[...]} or {action:'remove',blockId}
    - {action:'append_checklist',items:[{text,checked?:false}],blockId?:taskListId}
      (omit blockId for new list; use a read top-level taskList ID otherwise)
    - {action:'replace_checklist',blockId,items} only for requested conversion
    - {action:'set_checked',itemId,checked,blockId?} using read taskItem.attrs.id;
      optional blockId is that item's taskList. Do not rewrite lists to toggle.
    Checklist plus note example: changes={title:'今日待办',bodyEdits:[
      {action:'append_checklist',items:[{text:'收周报'}]},
      {action:'append',blocks:[{type:'paragraph',content:[{type:'text',text:'保留备注'}]}]}]}.
    Batch requested items and notes together; body/bodyEdits are exclusive.
    Preserve order, conditions and compound items. Default unchecked; partial
    completion is not entire item completion; checklist completion does not set
    work status. Same-text items in different sections need user selection unless
    all matches were explicitly selected.
    update: {action:'create',text,materialIds?,materials?},
      {action:'edit',id,expectedRevision,text,materialIds?}, or
      {action:'delete',id,expectedRevision}; list_work_updates before edit/delete.
    materials: [{attachmentId} or {deliverableId,revision,fileId}], only selected
    NEW files to append; existing materials are retained by the server. Known IDs
    need no content reread or plan conversion. Read saved IDs via list_work_materials.
    removeMaterial:{id,expectedRevision}; remove body/update references first.
    New material nodes use attrs.materialId=attachmentId plus materials:[{attachmentId}].
    Advice entries use read deliverable_id/deliverable_revision/item_id, one entry
    per work, preserving full goals/content/conditions. Files may share one work;
    shared_attachment_ids only for explicitly shared files.

    Reports: generate_report uses report_kind and company-local report_date
    (YYYY-MM-DD), omits changes/source_tokens. The server reads sources and copies
    the original brief: enqueue and end, no preliminary work/obligation lookup,
    polling or extra edit. submit_after=true only for generate-and-submit,
    including review-before-submit; review-first/mode still control approval.
    edit/submit/delete require current report/revision. Edit requested
    completed/ongoing/blockers/next only; source plans/titles are not achievements.
    reportSnapshot is the saved/candidate revision; emptyFields were not written.
    Admin own follow-ups use create_work with actual source_tokens (not citation
    syntax); cannot edit employee work or generate/submit employee reports.
    """
    try:
        result = await actions_execute(runtime.context, step=step, action=action, target_id=target_id, expected_revision=expected_revision, changes=changes, report_kind=report_kind, report_date=report_date, obligation_id=obligation_id, source_tokens=source_tokens, submit_after=submit_after, requires_step=requires_step, copy_index=copy_index, deliverable_id=deliverable_id, deliverable_revision=deliverable_revision, item_id=item_id, shared_attachment_ids=shared_attachment_ids, task_item_id=task_item_id)
        from app.tasks.feedback.report_waits import completion_wait
        result = {**result, **completion_wait(result, submit_after=submit_after)}
        from app.tasks.feedback.public import model_result
        return json.dumps(model_result(result), ensure_ascii=False, default=str)
    except HTTPException as error:
        return json.dumps(http_failure(error), ensure_ascii=False)
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
                    return clip({'state': 'failed', 'category': 'invalid_arguments', 'message': '管理员请用团队业务查询查看员工已提交报告。'})
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
                            return clip({'state': 'failed', 'category': 'invalid_arguments', 'message': '请先通过团队业务查询定位已提交报告，或提供要删除报告的准确链接；不能猜测未提交报告。'})
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
        except HTTPException as error:
            return clip(http_failure(error))
        except ValueError:
            return clip({'state': 'failed', 'category': 'invalid_arguments', 'message': '报告日期或分页位置无效，请修正后重试。'})


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
        except HTTPException as error:
            return clip(http_failure(error))
        except ValueError:
            return clip({'state': 'failed', 'category': 'invalid_arguments', 'message': '汇报查询条件无效，请核对日期和范围。'})


ACTION_TOOLS = [execute_business_action, get_business_actions, query_reports, query_report_obligations]
