"""Read only complete persisted job, provider usage and mutation evidence."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from environment import load_environment


async def main(args):
    metadata, private = load_environment(args.metadata)
    os.environ.update(private['environment'])
    from app.core.config import Settings
    from app.db import registry
    from app.db.session import database
    from app.tasks.models import Job
    from app.modules.model_services.models import ModelUsage
    from app.modules.operations.models import BusinessAction
    from app.modules.work.models import WorkItem, WorkRevision
    from app.modules.reports.models import Report, ReportRevision
    from app.modules.memories.models import AssistantMemory
    from app.modules.deliverables.models import Deliverable, DeliverableRevision
    from app.modules.executions.models import SandboxExecution
    from sqlalchemy import select, text
    engine, sessions = database(Settings())
    try:
        output = {}
        async with sessions() as db:
            await db.execute(text('SET TRANSACTION READ ONLY'))
            for model in (Job, ModelUsage, BusinessAction, WorkItem, WorkRevision, Report, ReportRevision, AssistantMemory, Deliverable, DeliverableRevision, SandboxExecution):
                rows = list(await db.scalars(select(model)))
                output[model.__name__] = [{column.key: getattr(row, column.key) for column in model.__table__.columns} for row in rows]
        target = Path(args.output)
        if target.exists():
            raise RuntimeError('Refusing to overwrite readback')
        target.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str))
        print(json.dumps({key: len(value) for key, value in output.items()}))
    finally:
        await engine.dispose()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--metadata', required=True)
    p.add_argument('--output', required=True)
    asyncio.run(main(p.parse_args()))
