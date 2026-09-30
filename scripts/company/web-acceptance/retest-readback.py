"""Read durable evidence for already submitted retest jobs; no model calls/writes."""
import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--manifest', default='artifacts/spec044/environment/manifest.json')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    run = Path(args.run)
    target = run / 'durable-readback.json'
    if target.exists():
        raise RuntimeError('Refusing to overwrite durable evidence')
    submitted = [json.loads(line) for line in (run / 'submitted.jsonl').read_text().splitlines() if line.strip()]
    if not submitted or len(submitted) > 12:
        raise RuntimeError('Expected bounded retest submissions')
    spec = importlib.util.spec_from_file_location('acceptance_environment', Path(__file__).with_name('environment.py'))
    environment = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(environment)
    metadata, private = environment.load_environment(Path(args.manifest))
    sys.path[:0] = [str(root / 'apps/server'), str(root / 'packages/voiceprint-engine/src')]
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.db import registry
    from app.tasks.models import Job
    from app.modules.executions.models import SandboxExecution
    from app.modules.model_services.models import ModelUsage
    from app.modules.operations.models import BusinessAction
    engine = create_async_engine(private['environment']['DATABASE_URL'], pool_size=1, max_overflow=0)
    sessions = async_sessionmaker(engine)
    result = []
    try:
        async with sessions.begin() as db:
            await db.execute(text('SET TRANSACTION READ ONLY'))
            for row in submitted:
                receipt = row['receipt']
                job = await db.get(Job, receipt['jobId'])
                if not job or job.target_id != receipt['messageId']:
                    raise RuntimeError('Retest receipt does not match durable job')
                executions = (await db.scalars(select(SandboxExecution).where(SandboxExecution.job_id == job.id).order_by(SandboxExecution.created_at))).all()
                actions = (await db.scalars(select(BusinessAction).where(BusinessAction.message_id == receipt['messageId']).order_by(BusinessAction.step))).all()
                usage = (await db.scalars(select(ModelUsage).where(ModelUsage.job_id == job.id).order_by(ModelUsage.created_at))).all()
                relevant = {key: job.result[key] for key in ('deliveryRepairs', 'responseRepairComplete', 'completionRepairAttempted', 'completionIssue', 'taskInterpretation', 'documentReads', 'sandboxSources', 'operationFeedback') if key in job.result}
                pending = job.result.get('pendingReply', {})
                relevant['delivery'] = pending.get('delivery')
                result.append({'case': row['case'], 'turn': row['turn'], 'jobId': job.id, 'messageId': receipt['messageId'],
                               'state': job.state, 'error': job.error, 'result': relevant,
                               'businessActions': [{'id': action.id, 'action': action.action, 'state': action.state, 'params': action.params, 'result': action.result} for action in actions],
                               'sandboxExecutions': [{'id': execution.id, 'state': execution.state, 'sources': execution.sources,
                                                       'inputRefs': execution.result.get('inputRefs', []), 'stdout': execution.result.get('stdout', ''),
                                                       'stderr': execution.result.get('stderr', '')} for execution in executions],
                               'modelUsage': [{'kind': item.kind, 'status': item.status, 'input': item.actual_input_tokens,
                                               'output': item.actual_output_tokens, 'errorCode': item.error_code} for item in usage]})
    finally:
        await engine.dispose()
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'jobs': len(result), 'modelRequests': sum(len(row['modelUsage']) for row in result)}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
