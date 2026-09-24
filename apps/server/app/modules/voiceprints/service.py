import logging
import math
from app.core.errors import problem
from app.modules.members.models import Member
from app.modules.voiceprints.models import Voiceprint
from paa_voiceprints import DIMENSION, MODEL_ID
from sqlalchemy import select


async def member(db, actor, identifier):
    found = await db.scalar(select(Member).where(Member.id == identifier, Member.company_id == actor.company_id, Member.deleted.is_(False)))
    if not found:
        problem(404, '成员不存在或已停用')
    return found


async def enrollment(db, actor, identifier):
    target = await member(db, actor, identifier)
    item = await db.scalar(select(Voiceprint).where(Voiceprint.company_id == actor.company_id, Voiceprint.member_id == target.id))
    return target, item


MAX_BYTES = 20 * 1024 * 1024


log = logging.getLogger(__name__)


def valid_templates(value):
    return isinstance(value, list) and 1 <= len(value) <= 12 and all(
        isinstance(row, list) and len(row) == DIMENSION and
        all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in row) and
        .98 <= math.sqrt(sum(n * n for n in row)) <= 1.02 for row in value)


def private_path(settings, identifier):
    # File names originate solely from our random IDs, never client input.
    return settings.media_dir / 'voiceprints' / identifier


def dto(item, member):
    incompatible = bool(item and item.templates and (item.model_id != MODEL_ID or not valid_templates(item.templates)))
    return {'memberId': member.id, 'name': member.name, 'role': member.role,
            'active': member.active, 'state': 'incompatible' if incompatible and item.state not in ('queued', 'processing') else item.state if item else 'empty', 'revision': item.revision if item else 0,
            'ready': bool(item and item.templates and not incompatible), 'filename': item.filename if item else '',
            'error': '声纹版本不兼容，请重新上传登记录音' if incompatible else item.error if item else '', 'speechSeconds': item.speech_seconds if item else 0,
            'updatedAt': item.updated_at.isoformat() if item else None}
