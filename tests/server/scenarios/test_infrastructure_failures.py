"""Opt-in faults target a private TCP proxy and temporary media, never shared services."""
import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
import errno
import os
from pathlib import Path
import re
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.idempotency import Idempotency
from app.main import create_app
from app.modules.attachments.models import Attachment
from app.modules.work.models import WorkItem, WorkRevision
from _support.http.full_system_acceptance import evidence
from _support.agent.infrastructure_failures import assert_private_failure, database_proxy, isolated_url, test_database_disconnect_rolls_back_partial_write_and_recovers as database_disconnect_rolls_back_partial_write_and_recovers, test_media_write_failure_leaves_no_file_or_row_and_recovers as media_write_failure_leaves_no_file_or_row_and_recovers

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    os.getenv('SPEC044_INFRASTRUCTURE_TEST') != '1',
    reason='Opt-in infrastructure faults require an owned acceptance schema',
)]


async def test_database_disconnect_rolls_back_partial_write_and_recovers(setup, caplog):
    await database_disconnect_rolls_back_partial_write_and_recovers(setup, caplog)


@pytest.mark.parametrize('fault', ['permission', 'capacity'])
async def test_media_write_failure_leaves_no_file_or_row_and_recovers(setup, monkeypatch, caplog, fault):
    await media_write_failure_leaves_no_file_or_row_and_recovers(setup, monkeypatch, caplog, fault)
