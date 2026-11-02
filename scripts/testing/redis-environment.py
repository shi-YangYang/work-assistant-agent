"""Explicit test Redis configuration shared by all project test entrypoints."""
import json
import os
import re
import sys
from urllib.parse import urlsplit


def redis_environment(source, run_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
        raise RuntimeError('Invalid test run identity')
    target = source.get('PAA_REPLY_STREAM_TEST_URL', '')
    if target:
        url = urlsplit(target)
        if (url.scheme not in ('redis', 'rediss') or
                url.hostname not in ('localhost', '127.0.0.1', '::1') or
                not url.port or url.query or url.fragment or
                not re.fullmatch(r'/[0-9]+', url.path)):
            raise RuntimeError('PAA_REPLY_STREAM_TEST_URL requires explicit loopback Redis port/database')
    return {'PAA_REPLY_STREAM_REDIS_URL': target,
            'PAA_REPLY_STREAM_NAMESPACE': 'project:test:' + run_id}


if __name__ == '__main__':
    print(json.dumps(redis_environment(os.environ, sys.argv[1])))
