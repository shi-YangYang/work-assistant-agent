import asyncio
import io
import json
import os
from pathlib import Path
import sys
import zipfile
import pytest
from pypdf import PdfWriter
from paa_server.document_parser import MAX_EXPANDED, extract
from paa_server.documents import parse_process
from document_samples import samples, pdf_bytes

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('suffix', ['pdf', 'docx', 'pptx', 'txt', 'json', 'md', 'csv'])
async def test_real_parsers_preserve_locations(tmp_path, suffix):
    path = tmp_path / ('sample.' + suffix)
    path.write_bytes(samples()['演示项目.' + suffix])
    result = await parse_process(path, '.' + suffix)
    assert result['status'] == 'ready', result
    assert all(row['location'] and row['text'] for row in result['chunks'])
    text = '\n'.join(row['text'] for row in result['chunks'])
    expected = {'pdf': 'Later page', 'docx': '样本核对', 'pptx': '演讲备注', 'txt': '后半部分标记', 'json': '周五讨论', 'md': '<script>', 'csv': '=1+1'}
    assert expected[suffix] in text
    if suffix == 'docx':
        assert [row['location'].split(' · ')[0] for row in result['chunks']] == ['段落 1', '表格 1', '表格 1', '段落 2']
    if suffix == 'json':
        assert any(row['location'] == 'JSON /项目/安排/1' for row in result['chunks'])
    if suffix == 'pptx':
        assert any(row['location'] == '幻灯片 2 · 演讲备注' for row in result['chunks'])


@pytest.mark.parametrize('case', ['scan', 'encrypted', 'damaged', 'json', 'encoding', 'zip', 'entity'])
async def test_invalid_documents_cannot_succeed(tmp_path, case):
    suffix = '.pdf'
    if case in ('scan', 'encrypted'):
        writer = PdfWriter(); writer.add_blank_page(width=600, height=800)
        if case == 'encrypted': writer.encrypt('sample-password')
        output = io.BytesIO(); writer.write(output); data = output.getvalue()
    elif case == 'damaged': data = b'%PDF-1.7\ninvalid'
    elif case == 'json': suffix, data = '.json', b'{broken'
    elif case == 'encoding': suffix, data = '.txt', b'\x80\xfe\x88'
    else:
        suffix = '.docx'
        original = zipfile.ZipFile(io.BytesIO(samples()['演示项目.docx']))
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for entry in original.infolist():
                raw = original.read(entry)
                if case == 'entity' and entry.filename == 'word/document.xml':
                    raw = b'<!DOCTYPE x [<!ENTITY ext SYSTEM "file:///etc/passwd">]><x>&ext;</x>'
                archive.writestr(entry.filename, raw)
            if case == 'zip': archive.writestr('oversized.xml', b'X' * (17 * 1024 * 1024))
        data = output.getvalue()
    path = tmp_path / 'sample'; path.write_bytes(data)
    result = await parse_process(path, suffix)
    assert result['status'] == 'failed', result
    assert result['chunks'] == [] and result['info']['error']


async def test_partial_limits_and_blank_pages_are_explicit(tmp_path):
    path = tmp_path / 'text'; path.write_text('中' * 200_001)
    result = await parse_process(path, '.txt')
    assert result['status'] == 'partial' and result['info']['characters'] == 200_000
    path.write_bytes(pdf_bytes(['First', '']))
    result = await parse_process(path, '.pdf')
    assert result['status'] == 'partial' and '2' in result['info']['warnings'][0]
    path.write_bytes(pdf_bytes(['Page'] * 101))
    result = await parse_process(path, '.pdf')
    assert result['status'] == 'partial' and len(result['chunks']) == 100


async def test_timeout_reaps_real_child_and_resource_guard(tmp_path):
    parser_path = Path(__file__).parents[2] / 'services/company/src/paa_server/document_parser.py'
    runner = tmp_path / 'runner.py'
    marker = tmp_path / 'child.json'
    runner.write_text('import sys, os, time, json, runpy, resource\n'
        + f"module = runpy.run_path({str(parser_path.resolve())!r})\nmodule['resource_limits']()\n"
        + "with open(sys.argv[1], 'w') as out: json.dump({'pid': os.getpid(), 'limit': resource.getrlimit(resource.RLIMIT_AS)[0]}, out)\n"
        + 'time.sleep(10)\n')
    result = await parse_process(marker, '.txt', timeout=0.5, entrypoint=runner)
    assert result['status'] == 'failed' and '60 秒' in result['info']['error']
    state = json.loads(marker.read_text()); assert (sys.platform == 'darwin' or state['limit'] == 512 * 1024 * 1024)
    with pytest.raises(ProcessLookupError): os.kill(state['pid'], 0)
    runner.write_text('import json, runpy, socket, time\n' + f"module = runpy.run_path({str(parser_path.resolve())!r}); module['resource_limits']()\n"
        + "try:\n socket.socket()\nexcept PermissionError:\n network = 'denied'\n"
        + "try:\n value = bytearray(600 * 1024 * 1024); time.sleep(2)\nexcept MemoryError:\n memory = 'bounded'\n"
        + "print(json.dumps({'network': network, 'memory': memory}))\n")
    result = await parse_process(marker, '.txt', entrypoint=runner)
    if sys.platform == 'darwin':
        assert result['status'] == 'failed' and '资源' in result['info']['error']
    else:
        assert result == {'network': 'denied', 'memory': 'bounded'}, result


async def test_cancellation_reaps_child(tmp_path):
    runner = tmp_path / 'runner.py'; marker = tmp_path / 'pid'
    runner.write_text("import sys, os, time\nopen(sys.argv[1], 'w').write(str(os.getpid()))\ntime.sleep(10)\n")
    task = asyncio.create_task(parse_process(marker, '.txt', entrypoint=runner))
    for _ in range(50):
        if marker.exists(): break
        await asyncio.sleep(.01)
    pid = int(marker.read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    with pytest.raises(ProcessLookupError): os.kill(pid, 0)


async def test_pdf_decompression_is_bounded(tmp_path):
    import zlib
    from pypdf.generic import EncodedStreamObject, NameObject
    writer = PdfWriter(io.BytesIO(pdf_bytes(('Text',))))
    page = writer.pages[0]
    stream = EncodedStreamObject()
    stream._data = zlib.compress(b' ' * (MAX_EXPANDED + 1))
    stream[NameObject('/Filter')] = NameObject('/FlateDecode')
    page[NameObject('/Contents')] = writer._add_object(stream)
    path = tmp_path / 'compressed.pdf'; writer.write(path)
    result = await parse_process(path, '.pdf')
    assert result['status'] == 'failed' and '解压' in result['info']['error'], result


@pytest.mark.parametrize('assign_ok', [True, False])
async def test_windows_job_object_limits_and_fail_closed(monkeypatch, assign_ok):
    """API contract only; does not claim a real Windows kernel execution."""
    import ctypes
    from types import SimpleNamespace
    from paa_server.document_parser import windows_resource_limits
    calls = []
    class Function:
        def __init__(self, callback): self.callback = callback
        def __call__(self, *args): return self.callback(*args)
    def configure(handle, information_class, pointer, size):
        limits = pointer._obj
        assert handle == 101 and information_class == 9
        assert limits.ProcessMemoryLimit == 512 * 1024 * 1024
        assert limits.BasicLimitInformation.PerProcessUserTimeLimit == 450_000_000
        assert limits.BasicLimitInformation.ActiveProcessLimit == 1
        assert limits.BasicLimitInformation.LimitFlags == 0x210A
        assert size == (144 if ctypes.sizeof(ctypes.c_void_p) == 8 else 112)
        calls.append('configured')
        return True
    kernel = SimpleNamespace(CreateJobObjectW=Function(lambda *args: 101), SetInformationJobObject=Function(configure), AssignProcessToJobObject=Function(lambda *args: calls.append('assigned') or assign_ok), GetCurrentProcess=Function(lambda: 202), CloseHandle=Function(lambda *args: calls.append('closed') or True))
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *args, **kwargs: kernel, raising=False)
    if assign_ok:
        windows_resource_limits()
        assert calls == ['configured', 'assigned']
    else:
        with pytest.raises(OSError, match='资源限制'): windows_resource_limits()
        assert calls == ['configured', 'assigned', 'closed']
