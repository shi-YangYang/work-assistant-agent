"""Single control process, durable receipts, fair bounded queue, no shared workdir."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from .runtime import Runtime
from .schemas import ExecutionRequest, execution_id

TERMINAL = {'succeeded', 'failed', 'cancelled'}


class Service:
    def __init__(self):
        self.root = Path(os.environ.get('SANDBOX_STATE_DIR', '/state')).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.runtime = Runtime()
        self.concurrency = int(os.environ.get('SANDBOX_CONCURRENCY', '1'))
        if not 1 <= self.concurrency <= 8:
            raise ValueError('Invalid sandbox concurrency')
        self.tasks = {}
        self.rows = {}
        self.owner_order = []
        self.stopping = False
        self.loop_task = None

    def directory(self, identifier):
        return self.root / execution_id(identifier)

    def persist(self, row):
        path = self.directory(row['id'])
        path.mkdir(mode=0o700, exist_ok=True)
        temp = path / 'receipt.tmp'
        temp.write_text(json.dumps(row, ensure_ascii=False))
        temp.replace(path / 'receipt.json')
        self.rows[row['id']] = row

    async def start(self):
        await self.runtime.check()
        await self.runtime.verify()
        # Restart never executes an uncertain operation a second time.
        for path in self.root.glob('*/receipt.json'):
            row = json.loads(path.read_text())
            if row['state'] not in TERMINAL:
                await self.runtime.remove(row['id'])
                row.update(state='failed', error='执行服务重启，此次运行已终止，请修正或重新发起任务', files=[])
            self.persist(row)
            (path.parent / 'request.json').unlink(missing_ok=True)
        self.loop_task = asyncio.create_task(self.schedule())

    async def stop(self):
        self.stopping = True
        if self.loop_task:
            self.loop_task.cancel()
            await asyncio.gather(self.loop_task, return_exceptions=True)
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def submit(self, request):
        request.validate_inputs()
        serialized = request.serialized()
        fingerprint = hashlib.sha256(serialized.encode()).hexdigest()
        old = self.rows.get(request.id)
        if old:
            if old['fingerprint'] != fingerprint:
                raise ValueError('Execution ID already belongs to different input')
            old['touchedAt'] = time.time()
            self.persist(old)
            return old
        used = sum(path.stat().st_size for path in self.root.glob('*/*') if path.is_file())
        if used + len(serialized.encode()) + 32 * 1024 * 1024 > 512 * 1024 * 1024:
            raise OverflowError('执行服务临时存储已满，请稍后重试')
        pending = [r for r in self.rows.values() if r['state'] not in TERMINAL]
        if len(pending) >= 32 or sum(r['owner'] == request.owner for r in pending) >= 4:
            raise OverflowError('执行队列已满，请稍后重试')
        row = {'id': request.id, 'owner': request.owner, 'fingerprint': fingerprint, 'state': 'queued',
               'createdAt': time.time(), 'touchedAt': time.time(), 'files': []}
        self.persist(row)
        (self.directory(request.id) / 'request.json').write_text(serialized)
        return row

    def get(self, identifier):
        row = self.rows.get(execution_id(identifier))
        if row:
            row['touchedAt'] = time.time()
            self.persist(row)
        return row

    async def cancel(self, identifier):
        row = self.rows.get(execution_id(identifier))
        if not row:
            return
        task = self.tasks.get(identifier)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if row['state'] not in TERMINAL:
            row.update(state='cancelled', files=[])
            self.persist(row)
            (self.directory(identifier) / 'request.json').unlink(missing_ok=True)

    async def release(self, identifier):
        await self.cancel(identifier)
        row = self.rows.get(identifier)
        if row:
            # Retain small tombstone so a delayed duplicate cannot run again.
            for file in self.directory(identifier).iterdir():
                if file.name != 'receipt.json':
                    if file.is_file() or file.is_symlink():
                        file.unlink()
            row.update(files=[], released=True)
            self.persist(row)

    async def execute(self, row):
        try:
            request = ExecutionRequest.model_validate_json((self.directory(row['id']) / 'request.json').read_text())
            row['state'] = 'running'
            self.persist(row)
            result = await self.runtime.run(request, self.directory(row['id']))
            row.update(result)
        except asyncio.CancelledError:
            row.update(state='cancelled', error='执行已中断', files=[])
        except TimeoutError:
            row.update(state='failed', error='代码执行超过时间限制', files=[])
        except ValueError as error:
            row.update(state='failed', error=str(error)[:500], files=[])
        except Exception:
            row.update(state='failed', error='执行失败或触及文件、资源及隔离限制', files=[])
        finally:
            self.persist(row)
            (self.directory(row['id']) / 'request.json').unlink(missing_ok=True)
            self.tasks.pop(row['id'], None)

    async def schedule(self):
        while not self.stopping:
            current = time.time()
            # Caller heartbeats via query; orphan code is stopped within its timeout.
            for row in list(self.rows.values()):
                if row['state'] not in TERMINAL and current - row['touchedAt'] > 45:
                    await self.cancel(row['id'])
                if row['state'] in TERMINAL and not row.get('released') and current - row['touchedAt'] > 3600:
                    await self.release(row['id'])
                if row.get('released') and current - row['createdAt'] > 7 * 86400:
                    shutil.rmtree(self.directory(row['id']))
                    self.rows.pop(row['id'], None)
            pending = sorted((row for row in self.rows.values() if row['state'] == 'queued'), key=lambda row: row['createdAt'])
            while pending and len(self.tasks) < self.concurrency:
                owners = list(dict.fromkeys(item['owner'] for item in pending))
                self.owner_order = [owner for owner in self.owner_order if owner in owners]
                self.owner_order.extend(owner for owner in owners if owner not in self.owner_order)
                owner = self.owner_order.pop(0)
                self.owner_order.append(owner)
                row = next(item for item in pending if item['owner'] == owner)
                pending.remove(row)
                # Mark synchronously; schedule() can never start a second copy.
                row['state'] = 'running'
                self.persist(row)
                self.tasks[row['id']] = asyncio.create_task(self.execute(row))
            await asyncio.sleep(.1)
