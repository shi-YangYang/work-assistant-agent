"""Offline Community-1 inference in a disposable, cancellable child process."""
from __future__ import annotations

import hashlib
import multiprocessing
import os
import threading
import sys
import time
from pathlib import Path

from .repository import DomainError

MODEL_ID = 'pyannote/speaker-diarization-community-1'
REVISION = '3533c8cf8e369892e6b79ff1bf80f7b0286a54ee'
FILES = {
    'config.yaml': '5ce2bfa9a938dc132cec1172592d65173cbb8f444ea1e4133f10f9391de155be',
    'README.md': '2db91f9265bd81f1653ff088b5bff22bf6aebebea03328513af65501643f8a31',
    'segmentation/pytorch_model.bin': '7ad24338d844fb95985486eb1a464e32d229f6d7a03c9abe60f978bacf3f816e',
    'embedding/README.md': 'fa9e5105ae95edb231d841476cdb91eef4be0621c372ed4f7d3421294b5f8ad7',
    'embedding/pytorch_model.bin': '6f10ff60898a1d185fa22e1d11e0bfa8a92efec811f11bca48cb8cafebefd929',
    'plda/xvec_transform.npz': '325f1ce8e48f7e55e9c8aa47e05d2766b7c48c4b25b8de8dd751e7a4cc5fbe8f',
    'plda/README.md': 'e1316dbbeb3261431478d48ceebbd4bba395c3587e7b80c254dbab00f1209d0a',
    'plda/plda.npz': '9b77bcd840692710dd3496f62ecfeed8d8e5f002fd991b785079b244eab7d255',
}


def bundled_model_path():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'models' / 'speaker-community-1'
    return Path(__file__).resolve().parents[3] / 'resources' / 'models' / 'speaker-community-1'


def verified(path):
    path = Path(path)
    try:
        for name, digest in FILES.items():
            file = path / name
            if not file.resolve().is_relative_to(path.resolve()) or file.is_symlink() or not file.is_file() or file.stat().st_size > 50_000_000:
                return False
            with file.open('rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != digest:
                    return False
        return True
    except OSError:
        return False


def infer(model, audio, preference, progress):
    os.environ['PYANNOTE_METRICS_ENABLED'] = '0'
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '1'
    import torch
    from faster_whisper.audio import decode_audio
    from pyannote.audio import Pipeline
    torch.set_num_threads(4)
    torch.manual_seed(0)
    device = 'cpu'
    if preference == 'gpu':
        if torch.cuda.is_available():
            device = 'cuda'
        elif torch.backends.mps.is_available():
            device = 'mps'
    progress('正在加载模型')
    pipeline = Pipeline.from_pretrained(str(model))
    pipeline.to(torch.device(device))
    audio = decode_audio(str(audio), sampling_rate=16000)
    progress('正在区分说话人')
    last = 0
    def hook(step_name, _artifact=None, *args, **kwargs):
        nonlocal last
        if time.monotonic() - last < 1:
            return
        last = time.monotonic()
        label = {'segmentation': '分析发言片段', 'embeddings': '提取声音特征', 'discrete_diarization': '整理说话人'}.get(step_name, '区分说话人')
        done, total = kwargs.get('completed'), kwargs.get('total')
        progress(f'{label} {done}/{total}' if done is not None and total else label)
    output = pipeline({'waveform': torch.from_numpy(audio).unsqueeze(0), 'sample_rate': 16000}, hook=hook)
    turns = [[round(turn.start * 1000), round(turn.end * 1000), label] for turn, _, label in output.speaker_diarization.itertracks(yield_label=True) if turn.end > turn.start]
    return {'turns': turns, 'device': device}


def worker_main(connection, parent_pid, params):
    def guard():
        while True:
            time.sleep(.5)
            if (multiprocessing.parent_process() and not multiprocessing.parent_process().is_alive()) or os.getppid() != parent_pid:
                os._exit(0)
    threading.Thread(target=guard, daemon=True).start()
    try:
        result = infer(params['model'], params['audio'], params['device'], lambda message: connection.send({'progress': message}))
        connection.send({'result': result})
    except Exception as exc:
        connection.send({'error': type(exc).__name__})
    finally:
        connection.close()


def run_worker(params, cancelled, progress, timeout, target=worker_main):
    ctx = multiprocessing.get_context('spawn')
    receiver, sender = ctx.Pipe(duplex=False)
    child = ctx.Process(target=target, args=(sender, os.getpid(), params), daemon=True)
    try:
        child.start()
        sender.close()
        deadline = time.monotonic() + timeout
        while not cancelled.is_set():
            if time.monotonic() > deadline:
                raise DomainError('speaker_timeout', '区分说话人超时，原文字已保留，可重试。')
            if receiver.poll(.1):
                message = receiver.recv()
                if 'progress' in message:
                    progress(message['progress'])
                elif 'result' in message:
                    return message['result']
                else:
                    raise DomainError('speaker_inference', '说话人处理失败，原文字已保留。请检查模型及推理设备后重试。')
            elif not child.is_alive():
                raise DomainError('speaker_worker', '说话人处理进程已退出，原文字已保留，可重试。')
        raise DomainError('speaker_cancelled', '已停止区分说话人。')
    except EOFError:
        raise DomainError('speaker_worker', '说话人处理进程已退出，原文字已保留，可重试。') from None
    finally:
        if child.pid is not None:
            child.join(.2)
            if child.is_alive():
                child.terminate()
                child.join(2)
            if child.is_alive():
                child.kill()
                child.join(2)
            child.close()
        receiver.close()
        sender.close()
