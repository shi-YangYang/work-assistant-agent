from langgraph.checkpoint.base import BaseCheckpointSaver


class GuardedSaver(BaseCheckpointSaver):
    def __init__(self, saver, context):
        super().__init__(serde=saver.serde)
        self.saver, self.context = saver, context

    @property
    def config_specs(self):
        return self.saver.config_specs

    def get_next_version(self, current, channel):
        return self.saver.get_next_version(current, channel)

    async def _call(self, name, *args, **kwargs):
        from app.tasks.lease import lease
        async with self.context.sessions.begin() as db:
            await lease(db, self.context)
            return await getattr(self.saver, name)(*args, **kwargs)

    async def aget_tuple(self, config):
        return await self._call('aget_tuple', config)

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await self._call('aput', config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=''):
        return await self._call('aput_writes', config, writes, task_id, task_path)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        from app.tasks.lease import lease
        async with self.context.sessions.begin() as db:
            await lease(db, self.context)
            async for checkpoint in self.saver.alist(config, filter=filter, before=before, limit=limit):
                yield checkpoint
