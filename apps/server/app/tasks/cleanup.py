from app.core.errors import problem


async def finish_deletion(db, owner_id, settings):
    from app.modules.operations.deletion import clean_files
    # Commit the durable tombstones before touching files. A failed cleanup
    # remains hidden, is retried by maintenance and by the same DELETE URL.
    await db.commit()
    try:
        await clean_files(db, settings, owner_id)
    except OSError:
        problem(503, '记录已移除，附件清理尚未完成，请重试删除', 'cleanup_pending')
    return {'ok': True}
