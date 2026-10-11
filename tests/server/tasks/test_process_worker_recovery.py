"""Opt-in SIGKILL + actual 90-second lease expiry; no provider or fake clock."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from sqlalchemy import func, select

from app.db.idempotency import Idempotency
from app.modules.messages.models import Message
from app.modules.work.models import WorkItem
from app.tasks.models import Job
from _support.agent.process_worker_recovery import test_owned_worker_sigkill_before_write_after_commit_and_after_delivery as owned_worker_sigkill_before_write_after_commit_and_after_delivery

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.getenv('SPEC044_PROCESS_RECOVERY') != '1', reason='Opt-in process fault test; 90-second real lease expiry')]


async def test_owned_worker_sigkill_before_write_after_commit_and_after_delivery(setup, tmp_path):
    await owned_worker_sigkill_before_write_after_commit_and_after_delivery(setup, tmp_path)
