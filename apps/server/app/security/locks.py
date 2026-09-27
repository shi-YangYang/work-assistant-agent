from sqlalchemy import text


async def company_lock(db, company_id, *, shared=False):
    transaction = db.sync_session.get_transaction()
    read_scope = db.info.get('business_read_scope')
    scopes = read_scope[1] if read_scope and read_scope[0] is transaction else set()
    if company_id in scopes and not shared:
        raise RuntimeError('A read-only company transaction cannot upgrade to a write lock')
    function = 'pg_advisory_xact_lock_shared' if shared else 'pg_advisory_xact_lock'
    # Reacquire rather than cache "held": a nested transaction rollback can
    # release a PostgreSQL advisory lock while the outer session stays alive.
    await db.execute(text(f'SELECT {function}(hashtextextended(:scope, 0))'), {'scope': 'business:' + company_id})
    if shared:
        scopes.add(company_id)
        db.info['business_read_scope'] = (db.sync_session.get_transaction(), scopes)
