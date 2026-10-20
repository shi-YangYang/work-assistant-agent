"""Disposable Office supervisor. Fixed operation, not an Agent code runtime."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time

# -I intentionally excludes the working directory and PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from document_parser import ParseFailure, office_check, MAX_OFFICE_OUTPUT, MAX_OFFICE_WORKSPACE
from formats import OFFICE_TARGETS
from office_validation import inspect, verify_formula_caches

PROFILE = '''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting">
<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>
<prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>
<prop oor:name="SecureURL" oor:op="fuse"><value/></prop></item>
<item oor:path="/org.openoffice.Office.Writer/Content/Update">
<prop oor:name="Link" oor:op="fuse"><value>0</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Content/Update">
<prop oor:name="Link" oor:op="fuse"><value>0</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Formula/Load">
<prop oor:name="ODFRecalcMode" oor:op="fuse"><value>0</value></prop>
<prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>
</oor:items>'''
FILTERS = {'.docx': 'Office Open XML Text', '.xlsx': 'Calc Office Open XML', '.pptx': 'Impress MS PowerPoint 2007 XML'}
MAX_OUTPUT = MAX_OFFICE_OUTPUT


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def kill(child):
    if child.poll() is None:
        child.kill()
    child.wait()


def limits():
    if os.name == 'posix':
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (45, 46))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT, MAX_OUTPUT))
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
        if sys.platform != 'darwin':
            resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 * 1024, 1536 * 1024 * 1024))
    else:
        from document_parser import windows_resource_limits
        windows_resource_limits(processes=32, memory=1024 * 1024 * 1024)


def main():
    source, suffix, executable, budget = Path(sys.argv[1]), sys.argv[2], sys.argv[3], float(sys.argv[4])
    options = json.loads(sys.argv[6]) if len(sys.argv) > 6 else {}
    mode = options.get('mode', 'parse')
    if suffix not in (*OFFICE_TARGETS, '.docx', '.pptx', '.xlsx', '.pdf') or not source.is_file() or source.stat().st_size > (MAX_OUTPUT if mode in ('page', 'pdf') else 100 * 1024 * 1024):
        raise ParseFailure('文件格式或大小不支持')
    limits()
    parent = os.getppid()
    deadline = time.monotonic() + budget
    children, stopped = [], threading.Event()
    failure = ['文件处理超时或超出资源限制，请拆分或重新导出后上传']
    def stop(*_):
        raise InterruptedError(failure[0])
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    workspace = Path(sys.argv[5])
    if not workspace.is_dir() or workspace.is_symlink():
        raise ParseFailure('文件处理目录不可用')
    (workspace / 'owner.json').write_text(json.dumps({'worker': parent, 'supervisor': os.getpid()}))
    def watch():
        while not stopped.wait(.2):
            if os.getppid() != parent or time.monotonic() >= deadline:
                os.kill(os.getpid(), signal.SIGTERM); return
            try:
                size = sum(p.stat().st_size for p in workspace.rglob('*') if p.is_file())
                if size > MAX_OFFICE_WORKSPACE:
                    os.kill(os.getpid(), signal.SIGTERM); return
                if os.name == 'posix':
                    # Includes the supervisor and every process in its child groups.
                    result = subprocess.run(['/bin/ps', '-axo', 'pgid=,rss='], capture_output=True, timeout=2, check=True)
                    groups = {os.getpgrp()}
                    rows = [line.split() for line in result.stdout.splitlines()]
                    resident = [int(row[1]) for row in rows if len(row) == 2 and int(row[0]) in groups]
                    if sum(resident) > 1024 * 1024 or len(resident) > 32:
                        os.kill(os.getpid(), signal.SIGTERM); return
            except (OSError, subprocess.SubprocessError):
                failure[0] = '文件转换资源监测失败，请稍后重新解析'
                os.kill(os.getpid(), signal.SIGTERM); return
    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        if mode == 'page':
            from pypdf import PdfReader
            reader = PdfReader(source, strict=True)
            page = int(options.get('start', 1))
            if reader.is_encrypted or not 1 <= page <= len(reader.pages):
                raise ParseFailure('页面不存在或文件已加密')
            destination = Path(options['destination'])
            output = workspace / 'page'
            pixels = 2400 if options.get('sheet') == 'detail' else 1440
            child = subprocess.Popen([executable, '-f', str(page), '-l', str(page), '-singlefile', '-scale-to', str(pixels), '-png', str(source), str(output)],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={'LANG': 'C.UTF-8', 'PATH': os.defpath}, cwd=workspace)
            children.append(child)
            child.wait(timeout=max(.01, deadline - time.monotonic()))
            output = output.with_suffix('.png')
            if child.returncode or not output.is_file() or not 0 < output.stat().st_size <= 12 * 1024 * 1024:
                raise ParseFailure('页面图片无法读取')
            temporary = destination.with_name(destination.name + '.pending-' + str(os.getpid()))
            shutil.copyfile(output, temporary); temporary.chmod(0o600); temporary.replace(destination)
            emit({'result': {'status': 'ready', 'chunks': [], 'info': {'totalPages': len(reader.pages), 'page': page}}})
            return
        if suffix in OFFICE_TARGETS:
            actual, formulas = inspect(source, suffix)
        else:
            office_check(source, suffix)
            from office_visual_validation import validate
            validate(source)
            actual, formulas = suffix, {}
        target = '.pdf' if mode == 'pdf' else OFFICE_TARGETS.get(suffix, suffix)
        if actual == target:
            output = source
        else:
            profile, out = workspace / 'profile', workspace / 'output'
            (profile / 'user').mkdir(parents=True); out.mkdir()
            (profile / 'user' / 'registrymodifications.xcu').write_text(PROFILE)
            original = workspace / ('source' + actual)
            shutil.copyfile(source, original)
            if actual == '.xlsx' and options.get('sheet'):
                from office_visual_validation import select_sheet
                select_sheet(original, options['sheet'])
            env = {'HOME': str(workspace), 'TMPDIR': str(workspace), 'TMP': str(workspace), 'TEMP': str(workspace), 'LANG': 'C.UTF-8', 'PATH': os.defpath}
            if 'SYSTEMROOT' in os.environ:
                env['SYSTEMROOT'] = os.environ['SYSTEMROOT']
            emit({'stage': 'converting'})
            child = subprocess.Popen([executable, '-env:UserInstallation=' + profile.as_uri(), '--headless', '--nologo', '--nodefault', '--norestore', '--convert-to', target[1:] + ':' + ({'.docx': 'writer_pdf_Export', '.pptx': 'impress_pdf_Export', '.xlsx': 'calc_pdf_Export'}.get(actual, 'writer_pdf_Export') if target == '.pdf' else FILTERS[target]), '--outdir', str(out), str(original)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, cwd=workspace)
            children.append(child)
            try:
                code = child.wait(timeout=max(.01, deadline - time.monotonic()))
            finally:
                kill(child)
            output = out / ('source' + target)
            if code or not output.is_file() or not 0 < output.stat().st_size <= MAX_OUTPUT:
                raise ParseFailure('文件转换失败，请确认能正常打开，或用 Office／WPS 重新导出后上传')
            if target != '.pdf':
                office_check(output, target)
            if target == '.xlsx':
                verify_formula_caches(output, formulas)
        if options.get('destination'):
            destination = Path(options['destination'])
            temporary = destination.with_name(destination.name + '.pending-' + str(os.getpid()))
            shutil.copyfile(output, temporary)
            temporary.chmod(0o600)
            temporary.replace(destination)
        if mode in ('pdf', 'convert'):
            info = {'convertedFormat': target[1:]}
            if mode == 'pdf':
                from pypdf import PdfReader
                info['totalPages'] = len(PdfReader(output, strict=True).pages)
            emit({'result': {'status': 'ready', 'chunks': [], 'info': info}})
            return
        emit({'stage': 'parsing'})
        child = subprocess.Popen([sys.executable, '-I', str(Path(__file__).with_name('document_parser.py')), str(output), target, str(options.get('start', 0))], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env={'LANG': 'C.UTF-8', **({'SYSTEMROOT': os.environ['SYSTEMROOT']} if 'SYSTEMROOT' in os.environ else {})})
        children.append(child)
        try:
            raw = child.stdout.read(2 * 1024 * 1024 + 1)
            child.wait(timeout=max(.01, deadline - time.monotonic()))
            if child.returncode or len(raw) > 2 * 1024 * 1024:
                raise ParseFailure('文件读取超出资源限制，请拆分后上传')
            result = json.loads(raw)
        finally:
            kill(child)
            child.stdout.close()
        result['info'].update(originalFormat=suffix[1:], convertedFormat=target[1:])
        result['info'].setdefault('warnings', []).insert(0, f'内容由 {suffix[1:].upper()} 转换为 {target[1:].upper()} 后提取，复杂版式、图形及嵌入内容可能不完整。')
        if target == '.xlsx':
            result['info']['warnings'].append('读取的是转换后的表格；公式保存结果已核对，未运行宏或刷新外部数据。')
        emit({'result': result})
    finally:
        stopped.set()
        for child in children:
            kill(child)
        watcher.join(timeout=3)
        # All descendants inherit this private group. The worker always kills
        # the group too, including after a supervisor crash or hard timeout.
        if os.name == 'posix':
            try:
                rows = subprocess.run(['/bin/ps', '-axo', 'pid=,pgid='], capture_output=True, timeout=2, check=True).stdout.splitlines()
                for row in rows:
                    pid, group = map(int, row.split())
                    if group == os.getpgrp() and pid != os.getpid():
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
            except (OSError, subprocess.SubprocessError):
                pass
        try:
            shutil.rmtree(workspace)
        except OSError:
            # Only this private directory; a crash/removal error never deletes originals.
            emit({'cleanupFailed': True})


if __name__ == '__main__':
    try:
        main()
    except (ParseFailure, InterruptedError) as error:
        emit({'result': {'status': 'failed', 'chunks': [], 'info': {'error': str(error)}}})
    except subprocess.TimeoutExpired:
        emit({'result': {'status': 'failed', 'chunks': [], 'info': {'error': '文件处理超时，请拆分或重新导出后上传'}}})
    except Exception:
        emit({'result': {'status': 'failed', 'chunks': [], 'info': {'error': '文件读取失败，请确认能正常打开，或重新导出后上传'}}})
