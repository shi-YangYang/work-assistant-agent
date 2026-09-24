from sqlalchemy import text


async def company_lock(db, company_id):
    await db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))'), {'scope': 'business:' + company_id})
