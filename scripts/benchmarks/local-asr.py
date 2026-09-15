"""Manual, public-audio Spec 013 benchmark. Never reads meetings or changes defaults.

Prepare pins references before inference. Each `run` is a fresh process; invoke it
once per model/mode, sequentially. Artifacts are local and are not application data.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import re
import resource
import ssl
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import wave
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / 'artifacts/spec013'
RATE = 16000
NORMALIZATION = ('NFKC + casefold; retain Unicode letters/numbers only; no traditional/'
                 'simplified, homophone or number-word equivalence. CER: each letter/number '
                 'character. WER: punctuation/space-separated words (apostrophes removed). '
                 'MER: individual Han characters + contiguous non-Han letters/numbers; '
                 'digits form one contiguous token; punctuation separates tokens.')
SOURCES = {
    'zh': {'dataset': 'google/fleurs', 'config': 'cmn_hans_cn',
           'revision': '70bb2e84b976b7e960aa89f1c648e09c59f894dd', 'license': 'CC-BY-4.0',
           'metric': 'CER', 'firstRow': 20},
    'en': {'dataset': 'google/fleurs', 'config': 'en_us',
           'revision': '70bb2e84b976b7e960aa89f1c648e09c59f894dd', 'license': 'CC-BY-4.0',
           'metric': 'WER', 'firstRow': 20},
    'mixed': {'dataset': 'CAiRE/ASCEND', 'config': 'main',
              'revision': '737e9800ae31be9932ba8464c80366559bd28424', 'license': 'CC-BY-SA-4.0',
              'metric': 'MER', 'firstRow': 0},
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def fetch(url):
    import certifi
    context = ssl.create_default_context(cafile=certifi.where())
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30, context=context) as response:
                return response.read()
        except (OSError, urllib.error.URLError):
            if attempt == 2:
                raise
            time.sleep(1)


def is_han(char):
    return '\u3400' <= char <= '\u9fff' or '\U00020000' <= char <= '\U0003134f'


def tokens(text, mode):
    text = unicodedata.normalize('NFKC', text).casefold()
    if mode == 'zh':
        return [c for c in text if unicodedata.category(c)[0] in 'LN']
    text = text.replace("'", '').replace('’', '')
    output, word = [], ''
    for char in text:
        if mode == 'mixed' and is_han(char):
            if word:
                output.append(word)
                word = ''
            output.append(char)
        elif unicodedata.category(char)[0] in 'LN':
            word += char
        elif word:
            output.append(word)
            word = ''
    if word:
        output.append(word)
    return output


def edits(reference, hypothesis):
    # Stable tie order: match, substitution, deletion, insertion.
    table = [list(range(len(hypothesis) + 1))]
    for i, expected in enumerate(reference, 1):
        row = [i]
        for j, actual in enumerate(hypothesis, 1):
            row.append(min(table[-1][j - 1] + (expected != actual),
                           table[-1][j] + 1, row[-1] + 1))
        table.append(row)
    i, j = len(reference), len(hypothesis)
    result = {'substitutions': 0, 'deletions': 0, 'insertions': 0,
              'referenceUnits': i}
    while i or j:
        if i and j and reference[i - 1] == hypothesis[j - 1] and table[i][j] == table[i - 1][j - 1]:
            i, j = i - 1, j - 1
        elif i and j and table[i][j] == table[i - 1][j - 1] + 1:
            result['substitutions'] += 1
            i, j = i - 1, j - 1
        elif i and table[i][j] == table[i - 1][j] + 1:
            result['deletions'] += 1
            i -= 1
        else:
            result['insertions'] += 1
            j -= 1
    result['errorRate'] = sum(result[k] for k in ('substitutions', 'deletions', 'insertions')) / max(1, len(reference))
    return result


def prepare():
    manifest_path = ARTIFACTS / 'dataset-manifest.json'
    if manifest_path.exists():
        raise SystemExit('Dataset already frozen; do not reselect after seeing model output.')
    from faster_whisper.audio import decode_audio
    import numpy as np
    folder = ARTIFACTS / 'audio'
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {'frozenAt': datetime.now(timezone.utc).isoformat(), 'normalization': NORMALIZATION,
                'selection': 'Ascending validation rows from firstRow; all FLEURS rows. ASCEND '
                'requires language=mixed and both Han and ASCII English letters in the '
                'original utterance. Keep entire clips until >=120 source-audio seconds AND '
                '>=10 clips. No output-dependent selection. Between clips add 0.5s silence.',
                'groups': {}}
    for mode, source in SOURCES.items():
        card = fetch(f"https://huggingface.co/datasets/{source['dataset']}/raw/{source['revision']}/README.md")
        (ARTIFACTS / f'{mode}-dataset-card.md').write_bytes(card)
        count, seconds, offset, pcm_parts, selected = 0, 0.0, source['firstRow'], [], []
        while count < 10 or seconds < 120:
            query = urllib.parse.urlencode({'dataset': source['dataset'], 'config': source['config'],
                                            'split': 'validation', 'offset': offset, 'length': 40})
            payload = json.loads(fetch('https://datasets-server.huggingface.co/rows?' + query))
            write_json(ARTIFACTS / f'{mode}-rows-{offset}.json', payload)
            if not payload['rows']:
                raise RuntimeError('Not enough eligible rows')
            for entry in payload['rows']:
                row, index = entry['row'], entry['row_idx']
                text = row.get('raw_transcription', row['transcription'])
                if mode == 'mixed' and not (row['language'] == 'mixed' and
                                              any(is_han(c) for c in text) and re.search('[A-Za-z]', text)):
                    continue
                audio_url = row['audio'][0]['src']
                if f"/--/{source['revision']}/--/" not in audio_url:
                    raise RuntimeError('Dataset server returned a different revision')
                audio_path = folder / f'{mode}-{index}.wav'
                if audio_path.exists():
                    data = audio_path.read_bytes()
                else:
                    data = fetch(audio_url)
                    audio_path.write_bytes(data)
                audio = decode_audio(io.BytesIO(data), sampling_rate=RATE)
                pcm = (np.clip(audio, -1, 32767 / 32768) * 32768).round().astype('<i2').tobytes()
                duration = len(pcm) / 2 / RATE
                if pcm_parts:
                    pcm_parts.append(bytes(RATE))  # 0.5 seconds mono PCM16.
                start = sum(len(part) for part in pcm_parts) // 2
                pcm_parts.append(pcm)
                selected.append({'row': index, 'id': str(row['id']), 'name': Path(row['path']).name,
                                 'audioSha256': digest(data), 'pcmSha256': digest(pcm),
                                 'durationSeconds': duration, 'startFrame': start,
                                 'endFrame': start + len(pcm) // 2, 'reference': text})
                count += 1
                seconds += duration
                if count >= 10 and seconds >= 120:
                    break
            offset += 40
        combined = folder / f'{mode}-combined.wav'
        with wave.open(str(combined), 'wb') as wav:
            wav.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
            wav.writeframes(b''.join(pcm_parts))
        reference = ' '.join(item['reference'] for item in selected)
        manifest['groups'][mode] = {**source, 'split': 'validation', 'sampleCount': count,
                                    'sourceAudioSeconds': seconds,
                                    'audioSeconds': seconds + 0.5 * (count - 1),
                                    'source': f"https://huggingface.co/datasets/{source['dataset']}",
                                    'cardSha256': digest(card), 'audioSha256': digest(combined.read_bytes()),
                                    'reference': reference, 'referenceUnits': len(tokens(reference, mode)),
                                    'samples': selected}
        print(mode, count, round(seconds, 3), [x['row'] for x in selected], flush=True)
    write_json(manifest_path, manifest)
    print('Frozen manifest SHA256:', digest(manifest_path.read_bytes()), flush=True)


def run(model, mode, cache):
    sys.path.insert(0, str(ROOT / 'apps/desktop/core/src'))
    from paa_core.asr_worker import WhisperProvider, config_for_mode
    from paa_core.model_catalog import CATALOG
    from paa_core.transcription import choose_boundary, owned_segments
    provider_start_sha = digest((ROOT / 'apps/desktop/core/src/paa_core/asr_worker.py').read_bytes())
    manifest_path = ARTIFACTS / 'dataset-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    spec, group = CATALOG[model], manifest['groups'][mode]
    path = cache / f"whisper-{model}-{spec['revision']}"
    output = ARTIFACTS / f'result-{model}-{mode}.json'
    if output.exists() or output.with_suffix('.failure.json').exists():
        raise SystemExit('Result already exists; preserve measurements and failure evidence.')
    audio_path = ARTIFACTS / f'audio/{mode}-combined.wav'
    if digest(audio_path.read_bytes()) != group['audioSha256']:
        raise RuntimeError('Frozen audio hash mismatch')
    config = config_for_mode(mode)
    started = time.monotonic()
    provider = WhisperProvider(path, config)
    load_seconds = time.monotonic() - started
    chunks, start = [], 0
    with wave.open(str(audio_path), 'rb') as wav:
        frames = wav.getnframes()
        while start < frames:
            end = min(frames, start + RATE * config['chunkSeconds'])
            context_start = max(0, start - RATE * config['contextSeconds'])
            context_end = min(frames, end + RATE * config['contextSeconds'])
            wav.setpos(context_start)
            pcm = wav.readframes(context_end - context_start)
            if end < frames:
                boundary = choose_boundary(pcm[(start - context_start) * 2:], RATE,
                                           RATE * config['chunkSeconds'])
                end = start + boundary
                context_end = min(frames, end + RATE * config['contextSeconds'])
                pcm = pcm[:(context_end - context_start) * 2]
            chunk = {'startFrame': start, 'endFrame': end,
                     'contextStart': context_start, 'contextEnd': context_end}
            then = time.monotonic()
            words = provider.transcribe(pcm, RATE)
            segments = owned_segments(words, chunk, RATE)
            chunks.append({'chunk': chunk, 'segments': segments, 'seconds': time.monotonic() - then})
            print(model, mode, len(chunks), round(end / RATE, 2),
                  'computeSeconds', round(chunks[-1]['seconds'], 3), flush=True)
            start = end
    # Silence has no denominator, so retain it as a separate hallucination check.
    silence = provider.transcribe(bytes(RATE * 2 * 10), RATE)
    text = ' '.join(segment['text'] for chunk in chunks for segment in chunk['segments'])
    score = edits(tokens(group['reference'], mode), tokens(text, mode))
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result = {'model': model, 'mode': mode, 'modelRevision': spec['revision'], 'config': config,
              'measuredAt': datetime.now(timezone.utc).isoformat(), 'datasetManifestSha256': digest(manifest_path.read_bytes()),
              'providerStartSha256': provider_start_sha,
              'providerSha256': digest((ROOT / 'apps/desktop/core/src/paa_core/asr_worker.py').read_bytes()),
              'platform': platform.platform(), 'peakRssBytes': rss if sys.platform == 'darwin' else rss * 1024,
              'loadSeconds': load_seconds, 'inferenceSeconds': sum(c['seconds'] for c in chunks),
              'score': score, 'hypothesis': text, 'chunks': chunks, 'silenceWords': silence}
    write_json(output, result)
    print(json.dumps({k: result[k] for k in ('model', 'mode', 'score', 'peakRssBytes', 'inferenceSeconds')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run'))
    parser.add_argument('--model', choices=('tiny', 'base', 'small', 'medium', 'large-v3-turbo', 'large-v3'))
    parser.add_argument('--mode', choices=tuple(SOURCES))
    parser.add_argument('--cache', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare()
    elif not all((args.model, args.mode, args.cache)):
        parser.error('run needs --model, --mode and --cache')
    else:
        try:
            run(args.model, args.mode, args.cache)
        except Exception as error:
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            failure = {'model': args.model, 'mode': args.mode, 'state': 'failed',
                       'measuredAt': datetime.now(timezone.utc).isoformat(),
                       'errorType': type(error).__name__, 'reason': str(error),
                       'partialPeakRssBytes': rss if sys.platform == 'darwin' else rss * 1024}
            write_json(ARTIFACTS / f'result-{args.model}-{args.mode}.failure.json', failure)
            raise
