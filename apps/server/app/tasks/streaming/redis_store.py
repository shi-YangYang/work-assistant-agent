"""Atomic bounded snapshot/cursor handoff. Redis is disposable, never authoritative."""
import json
from app.tasks.streaming.protocol import MAX_SNAPSHOT_BYTES, MAX_STREAM_BYTES, MAX_EVENT_BYTES, MAX_EVENTS, TTL_SECONDS

# The byte ledger includes serialized event values and a conservative per-entry
# overhead; snapshot + stream budgets leave 64 KiB for Redis key/index overhead.
WRITE = '''
local previous = redis.call('GET', KEYS[1])
if previous then
  local old = cjson.decode(previous)
  if old.closed or (old.sealed and old.generation >= tonumber(ARGV[2])) or old.generation > tonumber(ARGV[2]) or
     (old.generation == tonumber(ARGV[2]) and old.seq >= tonumber(ARGV[3])) then return 0 end
end
local size = string.len(ARGV[4]) + 256
local budget = tonumber(ARGV[6])
local used = tonumber(redis.call('GET', KEYS[3]) or '0')
while redis.call('XLEN', KEYS[2]) >= tonumber(ARGV[5]) or used + size > budget do
  local first = redis.call('XRANGE', KEYS[2], '-', '+', 'COUNT', 1)
  if #first == 0 then used = 0; break end
  used = used - string.len(first[1][2][2]) - 256
  redis.call('XDEL', KEYS[2], first[1][1])
end
local cursor = redis.call('XADD', KEYS[2], '*', 'event', ARGV[4])
-- Preserve the exact UTF-8 byte budget (cjson would additionally escape '/').
local snapshot = string.sub(ARGV[1], 1, -2) .. ',"cursor":"' .. cursor .. '"}'
redis.call('SET', KEYS[1], snapshot, 'EX', ARGV[7])
redis.call('SET', KEYS[3], used + size, 'EX', ARGV[7])
redis.call('EXPIRE', KEYS[2], ARGV[7])
return cursor
'''
SEAL = '''
local raw = redis.call('GET', KEYS[1])
if raw then
  local value = cjson.decode(raw)
  if ARGV[2] == '0' and value.generation > tonumber(ARGV[3]) then return 0 end
  value.sealed = true
  value.closed = value.closed or ARGV[2] == '1'
  value.generation = math.max(value.generation, tonumber(ARGV[3]))
  value.text = ''
  value.state = 'withdrawn'
  redis.call('SET', KEYS[1], cjson.encode(value), 'EX', ARGV[1])
else
  redis.call('SET', KEYS[1], cjson.encode({sealed=true, closed=ARGV[2] == '1', generation=tonumber(ARGV[3]), seq=0, text='', state='withdrawn'}), 'EX', ARGV[1])
end
redis.call('DEL', KEYS[2], KEYS[3])
return 1
'''
FREEZE = '''
local raw = redis.call('GET', KEYS[1])
if raw then
  local value = cjson.decode(raw)
  if not value.closed then
    -- Preserve the existing bytes, identity, cursor and expiration exactly.
    redis.call('SET', KEYS[1], string.sub(raw, 1, -2) .. ',"closed":true}', 'KEEPTTL')
  end
else
  redis.call('SET', KEYS[1], cjson.encode({sealed=true, closed=true, generation=0, seq=0, text='', state='withdrawn'}), 'EX', ARGV[1])
end
return 1
'''


class StreamUnavailable(Exception):
    pass


class RedisReplyStore:
    def __init__(self, url, *, namespace='paa:reply:v2', client=None):
        self.namespace = namespace
        if client is not None:
            self.client = client
        elif url:
            from redis.asyncio import Redis
            self.client = Redis.from_url(url, decode_responses=True, socket_connect_timeout=.5, socket_timeout=2)
        else:
            self.client = None

    def keys(self, identity):
        base = f'{self.namespace}:{{{identity.key}}}'
        return [base + suffix for suffix in (':snapshot', ':events', ':bytes')]

    async def call(self, operation, *args, **kwargs):
        if self.client is None:
            raise StreamUnavailable('reply_stream_not_configured')
        try:
            return await getattr(self.client, operation)(*args, **kwargs)
        except Exception as error:
            raise StreamUnavailable(type(error).__name__) from None

    async def publish(self, identity, snapshot, event):
        raw = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'))
        encoded_event = json.dumps(event, ensure_ascii=False, separators=(',', ':'))
        if len(raw.encode()) > MAX_SNAPSHOT_BYTES - 128 or len(encoded_event.encode()) > MAX_EVENT_BYTES:
            raise StreamUnavailable('reply_stream_capacity')
        return await self.call('eval', WRITE, 3, *self.keys(identity), raw, snapshot['generation'], snapshot['seq'],
                               encoded_event, MAX_EVENTS, MAX_STREAM_BYTES, TTL_SECONDS)

    async def snapshot(self, identity):
        raw = await self.call('get', self.keys(identity)[0])
        return json.loads(raw) if raw else None

    async def read(self, identity, cursor):
        values = await self.call('xread', {self.keys(identity)[1]: cursor}, count=64, block=400)
        return [(position, json.loads(fields['event'])) for _, rows in values for position, fields in rows]

    async def seal(self, identity, *, closed=True, generation=0):
        # A short-lived tombstone prevents late writes recreating a cancelled run.
        await self.call('eval', SEAL, 3, *self.keys(identity), TTL_SECONDS, int(closed), generation)

    async def freeze(self, identity):
        # A failed database save must not destroy the only authorized prefix.
        # closed rejects writes, while sealed remains reserved for revocation.
        await self.call('eval', FREEZE, 1, self.keys(identity)[0], TTL_SECONDS)

    async def close(self):
        if self.client is not None:
            await self.client.aclose()


_stores = {}


def store_for(settings):
    url = getattr(settings, 'reply_stream_redis_url', '')
    namespace = getattr(settings, 'reply_stream_namespace', 'paa:reply:v2')
    key = (url, namespace)
    if key not in _stores:
        _stores[key] = RedisReplyStore(url, namespace=namespace)
    return _stores[key]


async def close_stores():
    stores = list(_stores.values())
    _stores.clear()
    for store in stores:
        await store.close()
