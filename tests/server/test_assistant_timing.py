import json
from app.tasks.timing import Timing


def test_metadata_only_monotonic_intervals_and_bound(caplog):
    now = [1.0]
    timing = Timing('job', 2, 3, clock=lambda: now[0])
    with caplog.at_level('INFO', logger='paa.latency'):
        with timing.span('tool', call='call', kind='web_fetch', body='private', key='credential'):
            now[0] += .2
            timing.mark('model.send', kind='authorization')
        for _ in range(600):
            timing.mark('event')
    rows = [json.loads(row.message.removeprefix('latency ')) for row in caplog.records]
    assert len(rows) == 512
    assert rows[0]['at_ms'] == 0 and rows[2]['elapsed_ms'] == 200
    assert rows[1]['kind'] == 'authorization'
    assert 'private' not in caplog.text and 'credential' not in caplog.text
    assert all(row['job'] == 'job' and row['attempt'] == 2 and row['fence'] == 3 for row in rows)


def test_long_stream_sampling_preserves_terminal_timings(caplog):
    timing = Timing('long')
    with caplog.at_level('INFO', logger='paa.latency'):
        for _ in range(1000):
            timing.mark('publish.start')
            timing.mark('publish.end')
            timing.mark('source_check.start')
            timing.mark('source_check.end')
        timing.mark('model.end')
        timing.mark('persist.end')
    rows = [json.loads(row.message.removeprefix('latency ')) for row in caplog.records]
    assert len(rows) == 130
    assert [row['event'] for row in rows[-2:]] == ['model.end', 'persist.end']


def test_parent_spans_and_wall_clock_do_not_replace_monotonic_durations():
    now = [10.0]
    timing = Timing('task', clock=lambda: now[0])
    with timing.span('tool', call='tool-call', kind='read_work'):
        now[0] += .2
        nested = timing.mark('model.send', call='model-call', kind='authorization')
    terminal = timing.mark('task.end')
    assert nested['parent_call'] == 'tool-call' and nested['parent_kind'] == 'read_work'
    assert nested['at_ms'] == 200 and nested['at_unix_ms'] > 0
    assert terminal['at_ms'] == 200 and 'parent_call' not in terminal
