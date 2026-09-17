"""Compare the official Community-1 pipeline with the frozen speaker benchmark.

Manual experiment only; no application dependency or user recording is changed.
Install dependencies in artifacts/speaker-evaluation/community-1/env. Download
the authorized, pinned Community-1 snapshot to that directory's model folder.
The protocol is frozen before inference; reference labels never reach either
diarization pipeline or the identity matcher.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import resource
import time

os.environ.setdefault('PYANNOTE_METRICS_ENABLED', '0')

import torch
from pyannote.audio import Pipeline

SOURCE = Path(__file__).with_name('speaker-evaluation.py')
SPEC = importlib.util.spec_from_file_location('speaker_benchmark', SOURCE)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)
ROOT = benchmark.MODEL_DIR / 'community-1'
PREVIOUS = benchmark.DEFAULT_DATA / 'correction'


def data_directory(meeting, protocol):
    if meeting in protocol['freshRecordings']:
        return ROOT / 'holdout'
    if meeting in benchmark.AUTOMATIC_HOLDOUT:
        return PREVIOUS / 'automatic-holdout'
    if meeting == 'S_R003S02C01':
        return PREVIOUS
    return benchmark.DEFAULT_DATA


def synchronize(device):
    if device == 'mps':
        torch.mps.synchronize()


def infer(pipeline, data, protocol, device):
    cache = ROOT / 'cache' / f'{data["meeting"]}-diarization.json'
    signature = {
        'pipeline': protocol['pipeline'], 'revision': protocol['revision'],
        'models': protocol['modelFiles'], 'audio': data['audioHash'],
        'runtime': importlib.metadata.version('pyannote.audio'),
        'torch': torch.__version__, 'device': device,
        'speakerCount': 'automatic', 'exclusive': False,
    }
    if cache.exists():
        saved = json.loads(cache.read_text())
        if saved['signature'] == signature:
            print(data['meeting'], 'reuse Community-1 inference', flush=True)
            return saved
    started = time.perf_counter()
    last_report = [0.]

    def progress(step_name, _artifact, file=None, total=None, completed=None):
        current = time.perf_counter()
        if current - last_report[0] >= 25:
            print(data['meeting'], step_name, completed, '/', total, flush=True)
            last_report[0] = current

    with torch.inference_mode():
        result = pipeline(
            {'waveform': torch.from_numpy(data['audio']).unsqueeze(0),
             'sample_rate': benchmark.RATE},
            hook=progress,
        )
    synchronize(device)
    segments = [
        {'start': float(turn.start), 'end': float(turn.end), 'speaker': str(speaker)}
        for turn, _, speaker in result.speaker_diarization.itertracks(yield_label=True)
    ]
    saved = {
        'signature': signature, 'segments': segments,
        'performance': {'diarizationSeconds': time.perf_counter() - started,
                        'processPeakRSSBytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
    }
    benchmark.write_json(cache, saved)
    return saved


def summarize(paths):
    rows = [json.loads(path.read_text()) for path in paths]
    protocol = json.loads((ROOT / 'protocol.json').read_text())
    summaries = {}
    for scope, chosen in (
        ('previous', [r for r in rows if r['meeting'] not in protocol['freshRecordings']]),
        ('fresh', [r for r in rows if r['meeting'] in protocol['freshRecordings']]),
        ('all', rows),
    ):
        if not chosen:
            continue
        summaries[scope] = {
            'recordings': [r['meeting'] for r in chosen],
            'audioMinutes': sum(r['community']['durationSeconds'] for r in chosen) / 60,
        }
        for name in ('baseline', 'community'):
            def summed(*keys):
                total = 0.
                for row in chosen:
                    value = row[name]
                    for key in keys:
                        value = value[key]
                    total += value
                return total

            known_seconds = summed('identity', 'known', 'speechSeconds')
            unknown_seconds = summed('identity', 'unknown', 'speechSeconds')
            reference = summed('diarization', 'allSpeech', 'referenceSpeakerSeconds')
            mistakes = sum(summed('diarization', 'allSpeech', key)
                           for key in ('missSeconds', 'falseAlarmSeconds', 'confusionSeconds'))
            summaries[scope][name] = {
                'DER': mistakes / reference,
                'knownCorrect': summed('identity', 'known', 'correctSeconds') / known_seconds,
                'unknownFalseNaming': summed('identity', 'unknown', 'falselyNamedSeconds') / unknown_seconds,
                'unknownCorrect': summed('identity', 'unknown', 'correctSeconds') / unknown_seconds,
                'meetsEveryRecordingIdentityTarget': all(
                    r[name]['identity']['known']['accuracy'] >= .8
                    and r[name]['identity']['unknown']['falselyNamedSeconds']
                    / r[name]['identity']['unknown']['speechSeconds'] <= .05 for r in chosen
                ),
            }
    benchmark.write_json(ROOT / 'summary.json', summaries)
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--meeting', action='append')
    parser.add_argument('--device', choices=['cpu', 'mps'], default='mps')
    parser.add_argument('--smoke', action='store_true', help='30s pipeline execution only; not scored')
    args = parser.parse_args()
    protocol = json.loads((ROOT / 'protocol.json').read_text())
    for relative, expected in protocol['modelFiles'].items():
        if benchmark.sha256(ROOT / 'model' / relative) != expected:
            raise ValueError(f'Pinned model file changed: {relative}')
    policy_file = PREVIOUS / 'frozen-local-config.json'
    if benchmark.sha256(policy_file) != protocol['identityPolicySHA256']:
        raise ValueError('Frozen identity policy changed')
    if args.device == 'mps' and not torch.backends.mps.is_available():
        raise RuntimeError('MPS unavailable; explicitly choose --device cpu')
    torch.set_num_threads(4)
    torch.manual_seed(0)
    pipeline = Pipeline.from_pretrained(ROOT / 'model')
    pipeline.to(torch.device(args.device))
    print('Loaded pinned Community-1 on', args.device, flush=True)
    previous = benchmark.Experiment(PREVIOUS)
    candidate = benchmark.Experiment(ROOT)
    meetings = args.meeting or [*protocol['previouslyUsedRecordings'], *protocol['freshRecordings']]
    for meeting in meetings:
        if meeting not in protocol['previouslyUsedRecordings'] + protocol['freshRecordings']:
            raise ValueError('Meeting not in frozen protocol')
        data = previous.prepare(data_directory(meeting, protocol), meeting)
        if args.smoke:
            start = time.perf_counter()
            with torch.inference_mode():
                result = pipeline({'waveform': torch.from_numpy(data['audio'][:30 * benchmark.RATE]).unsqueeze(0),
                                   'sample_rate': benchmark.RATE})
            synchronize(args.device)
            print('30s smoke:', len(result.speaker_diarization), 'segments;',
                  round(time.perf_counter() - start, 2), 'seconds. Not an accuracy result.', flush=True)
            return
        target = ROOT / 'results' / f'{meeting}.json'
        print('Start', meeting, round(data['duration'] / 60, 2), 'minutes', flush=True)
        raw = infer(pipeline, data, protocol, args.device)
        feature_start = time.perf_counter()
        processed = candidate.local_features(data, raw)
        features_seconds = time.perf_counter() - feature_start
        community = benchmark.score(data, processed, protocol['identityPolicy'])
        community['performance'] = {**community['performance'], 'localIdentityFeatureSeconds': features_seconds}
        print(meeting, 'Community-1 scored; compare frozen baseline', flush=True)
        baseline_raw = previous.infer(data, protocol['identityPolicy']['clusteringThreshold'])
        baseline_local = previous.local_features(data, baseline_raw)
        baseline = benchmark.score(data, baseline_local, protocol['identityPolicy'])
        output = {
            'meeting': meeting, 'audioHash': data['audioHash'], 'enrollment': data['enrollment'],
            'sourceOffsetSeconds': benchmark.TEST_START,
            'protocolSHA256': benchmark.sha256(ROOT / 'protocol.json'),
            'baseline': baseline, 'community': community,
        }
        benchmark.write_json(target, output)
        benchmark.write_json(ROOT / 'segments' / f'{meeting}.json', {
            'meeting': meeting, 'audioHash': data['audioHash'],
            'sourceOffsetSeconds': benchmark.TEST_START,
            'anonymous': raw['segments'],
            'identified': benchmark.window_assignments(data, processed, protocol['identityPolicy']),
        })
        for name, score in (('baseline', baseline), ('community', community)):
            unknown = score['identity']['unknown']
            print(meeting, name, 'DER', round(100 * score['diarization']['allSpeech']['DER'], 2),
                  'known', round(100 * score['identity']['known']['accuracy'], 2),
                  'unknown false', round(100 * unknown['falselyNamedSeconds'] / unknown['speechSeconds'], 2),
                  flush=True)
        summarize(sorted((ROOT / 'results').glob('*.json')))


if __name__ == '__main__':
    main()
