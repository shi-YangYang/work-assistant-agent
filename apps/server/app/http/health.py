from fastapi import APIRouter
from app.http.dependencies import DB
from app.modules.members.models import Company
from sqlalchemy import select

router = APIRouter()


@router.get('/api/v1/health')
async def health(db=DB):
    await db.scalar(select(Company.id).limit(1))
    return {'status': 'ready'}
