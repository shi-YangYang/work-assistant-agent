"""Manual voiceprint/diarization experiment on public AISHELL-4 recordings.

Does not read user recordings or alter Electron. Dependencies are installed only
for this experiment: sherpa-onnx 1.13.8, numpy, scipy and soundfile. Data/models and
results stay in ignored artifacts. Each candidate is frozen before evaluation.
A failed holdout may become development data, but final validation then uses a
new recording. These candidates are experiments, not production defaults.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.cluster.vq import kmeans2
from scipy.linalg import eigh
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import pdist
import sherpa_onnx
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / 'artifacts/speaker-evaluation/real-meetings'
MODEL_DIR = ROOT / 'artifacts/speaker-evaluation'
RATE = 16000
REGISTER_END = 900.
TEST_START = 930.
CLUSTER_GRID = [.75, .9, 1.05]
IDENTITY_GRID = [.4, .45, .5, .55, .6]
MARGIN_GRID = [0., .05, .1]
CALIBRATION = 'M_R003S02C01'
FRESH_HOLDOUT = 'S_R003S02C01'
FINAL_HOLDOUT = 'L_R004S01C01'
REGROUP_HOLDOUT = 'S_R004S01C01'
AUTOMATIC_HOLDOUT = ['L_R004S02C01', 'S_R004S02C01']
REGRESSION = ['L_R003S01C02', 'M_R003S01C01', 'S_R003S01C01']
BASELINE_IDENTITY_THRESHOLD = .4035935699939728


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def annotation(path):
    result = []
    for line in path.read_text().splitlines():
        parts = line.split()
        start, duration = float(parts[3]), float(parts[4])
        if duration > 0:
            result.append({'start': start, 'end': start + duration, 'speaker': parts[7]})
    return result


def clipped(rows, start, end, relative=False):
    return [{'start': max(start, r['start']) - (start if relative else 0),
             'end': min(end, r['end']) - (start if relative else 0),
             'speaker': r['speaker']} for r in rows if r['end'] > start and r['start'] < end]


def timeline(reference, hypothesis, end):
    points = np.unique([0., end] + [max(0., min(end, r[k])) for r in reference + hypothesis for k in ('start', 'end')])
    widths = np.diff(points)
    mid = (points[:-1] + points[1:]) / 2
    ref_names = sorted({r['speaker'] for r in reference})
    hyp_names = sorted({r['speaker'] for r in hypothesis})
    ref = np.zeros((len(mid), len(ref_names)), dtype=bool)
    hyp = np.zeros((len(mid), len(hyp_names)), dtype=bool)
    for rows, names, matrix in ((reference, ref_names, ref), (hypothesis, hyp_names, hyp)):
        for row in rows:
            matrix[(mid >= row['start']) & (mid < row['end']), names.index(row['speaker'])] = True
    return points, widths, ref_names, hyp_names, ref, hyp


def solo_intervals(rows, start, end):
    rows = clipped(rows, start, end)
    points, _, names, _, ref, _ = timeline(rows, [], end)
    solo = []
    for i in np.flatnonzero(ref.sum(axis=1) == 1):
        name = names[int(np.argmax(ref[i]))]
        a, b = max(start, points[i]), points[i + 1]
        if b <= a:
            continue
        if solo and solo[-1]['speaker'] == name and abs(solo[-1]['end'] - a) < 1e-7:
            solo[-1]['end'] = b
        else:
            solo.append({'start': a, 'end': b, 'speaker': name})
    return solo


def diarization_metrics(reference, hypothesis, duration):
    _, weights, refs, hyps, ref, hyp = timeline(reference, hypothesis, duration)
    intersections = (ref.astype(float) * weights[:, None]).T @ hyp.astype(float)
    ref_indices, hyp_indices = linear_sum_assignment(-intersections)
    matched = (ref[:, ref_indices] & hyp[:, hyp_indices]).sum(axis=1)
    nr, nh = ref.sum(axis=1), hyp.sum(axis=1)
    def score(mask):
        w = weights * mask
        total = float(w @ nr)
        miss = float(w @ np.maximum(nr - nh, 0))
        false_alarm = float(w @ np.maximum(nh - nr, 0))
        confusion = float(w @ (np.minimum(nr, nh) - matched))
        return {'referenceSpeakerSeconds': total, 'missSeconds': miss, 'falseAlarmSeconds': false_alarm,
                'confusionSeconds': confusion, 'DER': (miss + false_alarm + confusion) / total if total else None}
    return {'allSpeech': score(np.ones(len(weights))), 'excludingOverlap': score(nr <= 1),
            'overlapWallSeconds': float(weights @ (nr > 1)), 'speechWallSeconds': float(weights @ (nr > 0)),
            'speakerMappingForScoringOnly': {hyps[h]: refs[r] for r, h in zip(ref_indices, hyp_indices)}}


def identity_metrics(reference, hypothesis, duration, known):
    _, weights, refs, hyps, ref, hyp = timeline(reference, hypothesis, duration)
    nr, nh = ref.sum(axis=1), hyp.sum(axis=1)
    correct = np.zeros(len(weights), dtype=bool)
    known_active = np.zeros(len(weights), dtype=bool)
    unknown_claimed_known = np.zeros(len(weights), dtype=bool)
    for i, name in enumerate(refs):
        wanted = name if name in known else 'unknown'
        if name in known:
            known_active |= ref[:, i]
        if wanted in hyps:
            correct |= ref[:, i] & hyp[:, hyps.index(wanted)]
    for i, name in enumerate(hyps):
        if name in known:
            unknown_claimed_known |= hyp[:, i]
    single = nr == 1
    correct &= nh == 1
    output = {}
    for label, mask in [('known', single & known_active), ('unknown', single & ~known_active)]:
        total = float(weights @ mask)
        good = float(weights @ (mask & correct))
        output[label] = {'speechSeconds': total, 'correctSeconds': good, 'accuracy': good / total if total else None,
                         'missedSeconds': float(weights @ (mask & (nh == 0)))}
    output['unknown']['falselyNamedSeconds'] = float(weights @ (single & ~known_active & unknown_claimed_known))
    return output


def chunks(start, end, minimum=1.):
    while end - start >= minimum:
        finish = min(end, start + 10.)
        yield start, finish
        start = finish


class Experiment:
    def __init__(self, output, identity_model=None):
        self.output = output
        self.embedding_path = MODEL_DIR / 'embedding.onnx'
        self.segmentation_path = MODEL_DIR / 'sherpa-onnx-pyannote-segmentation-3-0/model.onnx'
        self.model_hashes = {'embedding': sha256(self.embedding_path), 'segmentation': sha256(self.segmentation_path)}
        self.raw_extractor = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(self.embedding_path), num_threads=4, provider='cpu'))
        self.extractor = self.raw_extractor
        if identity_model:
            self.model_hashes['identity'] = sha256(identity_model)
            self.extractor = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(identity_model), num_threads=4, provider='cpu'))
        self.config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(self.segmentation_path)),
                num_threads=4, provider='cpu'),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(self.embedding_path), num_threads=4, provider='cpu'),
            clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=.5),
            min_duration_on=.3, min_duration_off=.5)
        if not self.config.validate():
            raise ValueError('Invalid diarization configuration')
        self.diarizer = sherpa_onnx.OfflineSpeakerDiarization(self.config)

    def embed(self, audio, raw=False):
        extractor = self.raw_extractor if raw else self.extractor
        stream = extractor.create_stream()
        stream.accept_waveform(RATE, np.ascontiguousarray(audio, dtype=np.float32))
        stream.input_finished()
        if not extractor.is_ready(stream):
            raise ValueError('Insufficient audio')
        vector = np.asarray(extractor.compute(stream), dtype=np.float32)
        if not np.isfinite(vector).all() or np.linalg.norm(vector) == 0:
            raise ValueError('Invalid speaker embedding')
        return vector / np.linalg.norm(vector)

    def prepare(self, directory, meeting, end=None):
        mono = directory / f'{meeting}-channel1.wav'
        if not mono.exists():
            with sf.SoundFile(directory / f'{meeting}.flac') as reader:
                if reader.samplerate != RATE:
                    raise ValueError('Expected 16 kHz audio')
                with sf.SoundFile(mono, 'w', samplerate=RATE, channels=1, subtype='PCM_16') as writer:
                    while len(block := reader.read(65536, dtype='int16', always_2d=True)):
                        writer.write(block[:, 0])
        info = sf.info(mono)
        if info.samplerate != RATE or info.channels != 1:
            raise ValueError('Expected single-channel 16 kHz input')
        reference = annotation(directory / f'{meeting}.rttm')
        label_map = {name: f'speaker_{i + 1:02}' for i, name in enumerate(sorted({r['speaker'] for r in reference}))}
        reference = [{**r, 'speaker': label_map[r['speaker']]} for r in reference]
        solo = solo_intervals(reference, 0., REGISTER_END)
        available = defaultdict(float)
        for row in solo:
            available[row['speaker']] += row['end'] - row['start']
        # Register at most four voices to retain unknown speakers in these
        # five-or-more-person recordings; select by enrollment availability only.
        known = sorted(s for s, seconds in available.items() if seconds >= 60.)[:4]
        if not known:
            raise ValueError('No speaker has 60 seconds of enrollment speech')
        profiles, enrollment = [], {}
        for speaker in known:
            pieces, intervals = [], []
            remaining = 60 * RATE
            for row in solo:
                if row['speaker'] != speaker or remaining <= 0:
                    continue
                begin = round(row['start'] * RATE)
                stop = min(round(row['end'] * RATE), begin + remaining)
                value, _ = sf.read(mono, start=begin, stop=stop, dtype='float32')
                pieces.append(value)
                intervals.append({'start': begin / RATE, 'end': stop / RATE})
                remaining -= len(value)
            if remaining:
                raise ValueError('Enrollment audio is truncated')
            speech = np.concatenate(pieces)
            profile = np.mean([self.embed(speech[i:i + 10 * RATE]) for i in range(0, len(speech), 10 * RATE)], axis=0)
            profiles.append(profile / np.linalg.norm(profile))
            enrollment[speaker] = intervals
        end = min(info.duration, end) if end else info.duration
        audio, _ = sf.read(mono, start=round(TEST_START * RATE), stop=round(end * RATE), dtype='float32')
        held_reference = clipped(reference, TEST_START, end, relative=True)
        return {'meeting': meeting, 'audio': audio, 'reference': held_reference, 'known': known,
                'profiles': np.stack(profiles), 'enrollment': enrollment, 'duration': len(audio) / RATE,
                'start': TEST_START, 'end': end, 'audioHash': hashlib.sha256(audio.tobytes()).hexdigest(),
                'sourceLabelMap': label_map}

    def infer(self, data, threshold):
        key = f'{data["meeting"]}-{data["start"]:g}-{data["end"]:g}-{threshold:g}'
        cache = self.output / 'cache' / f'{key}.json'
        signature = {'models': {k: self.model_hashes[k] for k in ('embedding', 'segmentation')}, 'audio': data['audioHash'], 'threshold': threshold,
                     'runtime': sherpa_onnx.__version__, 'featureVersion': 1}
        for existing in [cache, self.output.parent / 'cache' / cache.name]:
            if existing.exists():
                saved = json.loads(existing.read_text())
                if saved['signature'] == signature:
                    return saved
        self.config.clustering.threshold = threshold
        self.diarizer.set_config(self.config)
        started = time.perf_counter()
        segments = [{'start': float(s.start), 'end': float(s.end), 'speaker': str(s.speaker)}
                    for s in self.diarizer.process(data['audio']).sort_by_start_time()]
        diar_seconds = time.perf_counter() - started
        features = defaultdict(list)
        started = time.perf_counter()
        for row in solo_intervals(segments, 0., data['duration']):
            for a, b in chunks(row['start'], row['end'], minimum=.5):
                features[row['speaker']].append({'seconds': b - a, 'embedding': self.embed(data['audio'][round(a * RATE):round(b * RATE)], raw=True).tolist()})
        saved = {'signature': signature, 'segments': segments, 'features': dict(features),
                 'performance': {'diarizationSeconds': diar_seconds, 'featureSeconds': time.perf_counter() - started}}
        write_json(cache, saved)
        return saved

    def local_features(self, data, inference):
        path = self.output / 'cache' / f'{data["meeting"]}-{data["start"]:g}-{data["end"]:g}-local3s.json'
        signature = {**inference['signature'], 'localWindowSeconds': 3., 'localStepSeconds': 1.,
                     'identityModel': self.model_hashes.get('identity', self.model_hashes['embedding'])}
        if path.exists():
            saved = json.loads(path.read_text())
            if saved['signature'] == signature:
                return {**inference, 'localWindows': saved['windows']}
        windows = []
        for row in solo_intervals(inference['segments'], 0., data['duration']):
            a = row['start']
            while a < row['end']:
                b = min(row['end'], a + 1.)
                center = (a + b) / 2
                left, right = max(row['start'], center - 1.5), min(row['end'], center + 1.5)
                vector = self.embed(data['audio'][round(left * RATE):round(right * RATE)]) if right - left >= .5 else None
                windows.append({'start': a, 'end': b, 'contextSeconds': right - left,
                                'embedding': vector.tolist() if vector is not None else None})
                a = b
        write_json(path, {'signature': signature, 'windows': windows})
        return {**inference, 'localWindows': windows}


def assignments(data, features, policy, legacy=False):
    result = {}
    for cluster, values in features.items():
        eligible = values if legacy else [v for v in values if v['seconds'] >= policy['minimumWindowSeconds']]
        if not eligible:
            result[cluster] = {'prediction': 'unknown', 'reason': 'insufficient_speech'}
            continue
        vectors = np.asarray([v['embedding'] for v in eligible])
        weights = np.ones(len(eligible)) if legacy else np.asarray([v['seconds'] for v in eligible])
        mean = np.average(vectors, axis=0, weights=weights)
        mean /= np.linalg.norm(mean)
        scores = data['profiles'] @ mean
        order = np.argsort(scores)[::-1]
        best = int(order[0])
        second = float(scores[order[1]]) if len(order) > 1 else -1.
        margin = float(scores[best]) - second
        accepted = float(scores[best]) >= policy['identityThreshold']
        support = None
        if not legacy:
            local_scores = vectors @ data['profiles'].T
            local_sorted = np.sort(local_scores, axis=1)
            local_margin = local_sorted[:, -1] - (local_sorted[:, -2] if len(order) > 1 else -1.)
            consistent = ((np.argmax(local_scores, axis=1) == best)
                          & (local_scores[:, best] >= policy['identityThreshold'])
                          & (local_margin >= policy['minimumMargin']))
            support = float(np.average(consistent, weights=weights))
            accepted = (accepted and margin >= policy['minimumMargin']
                        and support >= policy['minimumSupport']
                        and float(weights.sum()) >= policy['minimumEvidenceSeconds'])
        result[cluster] = {'prediction': data['known'][best] if accepted else 'unknown',
                           'top1': data['known'][best], 'score': float(scores[best]), 'margin': margin,
                           'support': support, 'evidenceSeconds': sum(v['seconds'] for v in eligible)}
    return result


def window_assignments(data, inference, policy):
    """Do not propagate one centroid's identity across a mixed cluster."""
    positions = defaultdict(int)
    named = []
    if 'localWindows' in inference:
        for window in inference['localWindows']:
            prediction = 'unknown'
            if window['embedding'] is not None and window['contextSeconds'] >= policy['minimumWindowSeconds']:
                values = data['profiles'] @ np.asarray(window['embedding'])
                order = np.argsort(values)[::-1]
                margin = float(values[order[0]] - values[order[1]]) if len(order) > 1 else float(values[order[0]] + 1.)
                if values[order[0]] >= policy['identityThreshold'] and margin >= policy['minimumMargin']:
                    prediction = data['known'][int(order[0])]
            named.append({'start': window['start'], 'end': window['end'], 'speaker': prediction})
        points, _, _, _, active, _ = timeline(inference['segments'], [], data['duration'])
        for index in np.flatnonzero(active.sum(axis=1) > 1):
            named.append({'start': float(points[index]), 'end': float(points[index + 1]), 'speaker': 'unknown'})
        return named
    for row in solo_intervals(inference['segments'], 0., data['duration']):
        last = row['start']
        for a, b in chunks(row['start'], row['end'], minimum=.5):
            entry = inference['features'][row['speaker']][positions[row['speaker']]]
            positions[row['speaker']] += 1
            if abs(entry['seconds'] - (b - a)) > 1e-5:
                raise ValueError('Cached embedding does not match its audio interval')
            values = data['profiles'] @ np.asarray(entry['embedding'])
            order = np.argsort(values)[::-1]
            margin = float(values[order[0]] - values[order[1]]) if len(order) > 1 else float(values[order[0]] + 1.)
            accepted = (b - a >= policy['minimumWindowSeconds']
                        and values[order[0]] >= policy['identityThreshold']
                        and margin >= policy['minimumMargin'])
            named.append({'start': a, 'end': b, 'speaker': data['known'][int(order[0])] if accepted else 'unknown'})
            last = b
        if last < row['end']:
            named.append({'start': last, 'end': row['end'], 'speaker': 'unknown'})
    # Overlapped predicted speech carries no safe per-person waveform evidence.
    points, _, _, _, active, _ = timeline(inference['segments'], [], data['duration'])
    for index in np.flatnonzero(active.sum(axis=1) > 1):
        named.append({'start': float(points[index]), 'end': float(points[index + 1]), 'speaker': 'unknown'})
    return named


def score(data, inference, policy, legacy=False):
    if policy.get('identityMode') in ('window', 'local'):
        named = {}
        hypothesis = window_assignments(data, inference, policy)
    else:
        named = assignments(data, inference['features'], policy, legacy=legacy)
        hypothesis = [{**r, 'speaker': named.get(r['speaker'], {'prediction': 'unknown'})['prediction']}
                      for r in inference['segments']]
    return {'meeting': data['meeting'], 'durationSeconds': data['duration'],
            'registeredSpeakers': data['known'], 'actualSpeakers': len({r['speaker'] for r in data['reference']}),
            'detectedSpeakers': len({r['speaker'] for r in inference['segments']}),
            'diarization': diarization_metrics(data['reference'], inference['segments'], data['duration']),
            'identity': identity_metrics(data['reference'], hypothesis, data['duration'], data['known']),
            'assignments': named, 'performance': inference['performance']}


def cluster_windows(vectors, policy):
    """Anonymous grouping only; no enrollment profiles or reference labels.

    Compare average-link cosine clustering and sparse-affinity spectral
    clustering (the latter also used by the official 3D-Speaker recipe).
    https://github.com/modelscope/3D-Speaker/blob/main/speakerlab/process/cluster.py
    """
    vectors = np.asarray(vectors, dtype=float)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    if len(vectors) <= 1:
        return np.zeros(len(vectors), dtype=int)
    if policy['method'] == 'average':
        tree = linkage(np.maximum(pdist(vectors, metric='cosine'), 0), method='average')
        return fcluster(tree, policy['distance'], criterion='distance') - 1
    affinity = np.maximum(vectors @ vectors.T, 0.)
    neighbors = min(len(vectors), max(6, round(len(vectors) * policy['neighborsFraction'])))
    keep = np.argpartition(affinity, -neighbors, axis=1)[:, -neighbors:]
    sparse = np.zeros_like(affinity)
    rows = np.arange(len(vectors))[:, None]
    sparse[rows, keep] = affinity[rows, keep]
    affinity = (sparse + sparse.T) / 2
    np.fill_diagonal(affinity, 0.)
    laplacian = np.diag(affinity.sum(axis=1)) - affinity
    maximum = min(policy['maximumSpeakers'], len(vectors) - 1)
    values, eigenvectors = eigh(laplacian, subset_by_index=[0, maximum])
    count = int(np.argmax(np.diff(values)) + 1)
    if count == 1:
        return np.zeros(len(vectors), dtype=int)
    embedded = eigenvectors[:, :count]
    trials = []
    for seed in range(5):
        centers, labels = kmeans2(embedded, count, iter=100, minit='++', seed=seed)
        trials.append((float(np.square(embedded - centers[labels]).sum()), labels))
    return min(trials, key=lambda item: item[0])[1]


def regroup(inference, duration, policy):
    windows = inference['localWindows']
    eligible = [w for w in windows if w['embedding'] is not None and w['contextSeconds'] >= 1.5]
    if not eligible:
        return [{**r, 'needsReview': True} for r in inference['segments']]
    vectors = np.asarray([w['embedding'] for w in eligible])
    labels = cluster_windows(vectors, policy)
    unique = sorted(set(labels))
    centers = np.stack([vectors[labels == label].mean(axis=0) for label in unique])
    centers /= np.linalg.norm(centers, axis=1, keepdims=True)
    # Preserve each eligible window's cluster; only short windows use a center.
    chosen = {id(w): unique.index(label) for w, label in zip(eligible, labels)}
    predictions, votes = [], defaultdict(lambda: defaultdict(float))
    for window in windows:
        if window['embedding'] is None:
            continue
        similarities = centers @ np.asarray(window['embedding'])
        label = chosen.get(id(window), int(np.argmax(similarities)))
        alternative = float(np.max(np.delete(similarities, label))) if len(centers) > 1 else -1.
        item = {'start': window['start'], 'end': window['end'], 'speaker': f'group_{label + 1:02}',
                'similarity': float(similarities[label]), 'margin': float(similarities[label] - alternative),
                'needsReview': bool(window['contextSeconds'] < 1.5 or similarities[label] < .5
                                    or similarities[label] - alternative < .1)}
        predictions.append(item)
        midpoint = (window['start'] + window['end']) / 2
        for original in inference['segments']:
            if original['start'] <= midpoint < original['end']:
                votes[original['speaker']][item['speaker']] += window['end'] - window['start']
    mapping = {speaker: max(counts, key=counts.get) for speaker, counts in votes.items()}
    points, _, names, _, active, _ = timeline(inference['segments'], [], duration)
    for index in np.flatnonzero(active.sum(axis=1) > 1):
        used = set()
        for speaker_index in np.flatnonzero(active[index]):
            original = names[speaker_index]
            label = mapping.get(original, f'unresolved_{original}')
            if label in used:
                label = f'unresolved_overlap_{original}'
            used.add(label)
            predictions.append({'start': float(points[index]), 'end': float(points[index + 1]),
                                'speaker': label, 'needsReview': True})
    # Retain short speech lacking an embedding, rather than deleting hard cases.
    for window in windows:
        if window['embedding'] is None:
            predictions.append({'start': window['start'], 'end': window['end'],
                                'speaker': 'unresolved_short', 'needsReview': True})
    return sorted(predictions, key=lambda item: (item['start'], item['speaker']))


def calibrate_groups(experiment, directory):
    destination = experiment.output / 'frozen-regroup-config.json'
    if destination.exists():
        raise SystemExit('Regrouping is frozen; do not retune using validation.')
    policies = ([{'method': 'spectral', 'neighborsFraction': p, 'maximumSpeakers': 15}
                 for p in [.012, .03, .06]]
                + [{'method': 'average', 'distance': d} for d in [.35, .45, .55]])
    protocol = {'developmentRecordings': [CALIBRATION, FRESH_HOLDOUT], 'freshHoldout': REGROUP_HOLDOUT,
                'models': experiment.model_hashes, 'runtime': sherpa_onnx.__version__,
                'policies': policies, 'selection': 'Lowest mean DER on the two development recordings; no oracle speaker count.',
                'baseClusteringThreshold': 1.05, 'localWindowSeconds': 3., 'localStepSeconds': 1.}
    write_json(experiment.output / 'regroup-protocol.json', protocol)
    prepared = []
    for meeting, end in [(CALIBRATION, 1530.), (FRESH_HOLDOUT, None)]:
        data = experiment.prepare(directory, meeting, end=end)
        inference = experiment.local_features(data, experiment.infer(data, 1.05))
        prepared.append((data, inference))
    trials = []
    for policy in policies:
        metrics = []
        for data, inference in prepared:
            predicted = regroup(inference, data['duration'], policy)
            metric = diarization_metrics(data['reference'], predicted, data['duration'])
            metrics.append({'meeting': data['meeting'], 'DER': metric['allSpeech']['DER'],
                            'detectedSpeakers': len({r['speaker'] for r in predicted})})
        trials.append({'policy': policy, 'metrics': metrics, 'meanDER': float(np.mean([m['DER'] for m in metrics]))})
        print('REGROUP', json.dumps(trials[-1]), flush=True)
        write_json(experiment.output / 'regroup-calibration.json', trials)
    winner = min(trials, key=lambda trial: trial['meanDER'])
    write_json(destination, {'policy': winner['policy'], 'calibrationMetrics': winner, 'protocol': protocol})


def evaluate_groups(experiment, directory, meeting, config_path):
    frozen = json.loads(config_path.read_text())
    if frozen['protocol']['models'] != experiment.model_hashes or frozen['protocol']['runtime'] != sherpa_onnx.__version__:
        raise ValueError('Models/runtime differ from calibration')
    if meeting in frozen['protocol']['developmentRecordings']:
        raise ValueError('Development recordings cannot be used as validation')
    data = experiment.prepare(directory, meeting)
    started = time.perf_counter()
    inference = experiment.local_features(data, experiment.infer(data, 1.05))
    predicted = regroup(inference, data['duration'], frozen['policy'])
    result = {'meeting': meeting, 'durationSeconds': data['duration'],
              'actualSpeakers': len({r['speaker'] for r in data['reference']}),
              'previousSpeakers': len({r['speaker'] for r in inference['segments']}),
              'detectedSpeakers': len({r['speaker'] for r in predicted}),
              'before': diarization_metrics(data['reference'], inference['segments'], data['duration']),
              'after': diarization_metrics(data['reference'], predicted, data['duration']),
              'reviewSpeechSeconds': sum(r['end'] - r['start'] for r in predicted if r['needsReview']),
              'policy': frozen['policy'], 'audioHash': data['audioHash'], 'frozenConfigHash': sha256(config_path),
              'wallSeconds': time.perf_counter() - started}
    write_json(experiment.output / f'{meeting}-regrouped.json', result)
    write_json(experiment.output / f'{meeting}-review-segments.json', predicted)
    print('RESULT', json.dumps(result), flush=True)


def group_identity_features(inference, grouped):
    by_interval = {(w['start'], w['end']): w for w in inference['localWindows']}
    features = defaultdict(list)
    for row in grouped:
        window = by_interval.get((row['start'], row['end']))
        if row['speaker'].startswith('group_') and window and window['embedding'] is not None and window['contextSeconds'] >= 1.5:
            features[row['speaker']].append({'embedding': window['embedding'], 'seconds': row['end'] - row['start']})
    return features


def joint_assignments(data, features, policy):
    """Use voice evidence only; names compete with an explicit unknown choice."""
    groups, vectors = [], []
    for group, windows in sorted(features.items()):
        seconds = np.array([w['seconds'] for w in windows])
        if seconds.sum() < 3.:
            continue
        mean = np.average([w['embedding'] for w in windows], weights=seconds, axis=0)
        if np.linalg.norm(mean) == 0:
            continue
        groups.append(group)
        vectors.append(mean / np.linalg.norm(mean))
    if not groups:
        return {}
    scores = np.asarray(vectors) @ data['profiles'].T
    order = np.argsort(scores, axis=1)[:, ::-1]
    choices = []
    for row in range(len(groups)):
        best = int(order[row, 0])
        margin = float(scores[row, best] - scores[row, order[row, 1]]) if len(data['known']) > 1 else float(scores[row, best] + 1.)
        choices.append({'top1': best, 'score': float(scores[row, best]), 'margin': margin,
                        'eligible': bool(scores[row, best] >= policy['identityThreshold'] and margin >= policy['minimumMargin'])})
    if policy['uniqueIdentity']:
        # Only the strongest eligible group claims a registered name. Do not
        # assign a weaker group its second-choice identity just to fill slots.
        utility = np.full((len(groups), len(data['known']) + len(groups)), -1.)
        utility[:, len(data['known']):] = 0.
        for row, choice in enumerate(choices):
            if choice['eligible']:
                utility[row, choice['top1']] = choice['score'] - policy['identityThreshold'] + 1e-9
        rows, columns = linear_sum_assignment(-utility)
        winners = {int(row): int(column) for row, column in zip(rows, columns) if column < len(data['known'])}
    else:
        winners = {row: c['top1'] for row, c in enumerate(choices) if c['eligible']}
    return {group: {**choices[row], 'prediction': data['known'][winners[row]] if row in winners else 'unknown'}
            for row, group in enumerate(groups)}


def named_groups(grouped, assignments):
    return [{**r, 'speaker': assignments.get(r['speaker'], {'prediction': 'unknown'})['prediction']}
            for r in grouped]


def background_identity(data, inference, features, assignments, policy):
    """Use automatically unmatched voice groups as an unknown-speaker cohort.

    No reference labels enter this step. Re-score windows against known AND
    unmatched group centers instead of spreading a group name to every window.
    """
    centers, names = [], []
    for group, windows in sorted(features.items()):
        weights = np.array([w['seconds'] for w in windows])
        if weights.sum() < 3.:
            continue
        mean = np.average([w['embedding'] for w in windows], weights=weights, axis=0)
        if np.linalg.norm(mean) == 0:
            continue
        centers.append(mean / np.linalg.norm(mean))
        names.append(assignments.get(group, {'prediction': 'unknown'})['prediction'])
    if not centers:
        return window_assignments(data, inference, {**policy, 'minimumWindowSeconds': 1.5})
    centers = np.asarray(centers)
    unknown = np.array([name == 'unknown' for name in names])
    named = []
    for window in inference['localWindows']:
        prediction = 'unknown'
        if window['embedding'] is not None and window['contextSeconds'] >= 1.:
            similarities = centers @ np.asarray(window['embedding'])
            best = int(np.argmax(similarities))
            rival = float(np.max(similarities[unknown])) if unknown.any() else -1.
            if names[best] != 'unknown' and similarities[best] >= policy['windowThreshold'] and similarities[best] - rival >= policy['backgroundMargin']:
                prediction = names[best]
        named.append({'start': window['start'], 'end': window['end'], 'speaker': prediction})
    points, _, _, _, active, _ = timeline(inference['segments'], [], data['duration'])
    for index in np.flatnonzero(active.sum(axis=1) > 1):
        named.append({'start': float(points[index]), 'end': float(points[index + 1]), 'speaker': 'unknown'})
    return named


def calibrate_background(experiment, directory):
    path = experiment.output / 'frozen-background-config.json'
    if path.exists():
        raise SystemExit('Background policy is frozen; do not retune using validation.')
    group_config = json.loads((experiment.output / 'frozen-regroup-config.json').read_text())
    joint_config = json.loads((experiment.output / 'frozen-automatic-config.json').read_text())
    prepared = []
    protocol = {**joint_config['protocol'], 'windowThresholds': [.4, .5, .6],
                'backgroundMargins': [0., .03, .06, .1, .15], 'jointPolicy': joint_config['policy']}
    write_json(experiment.output / 'background-protocol.json', protocol)
    for meeting, end in [(CALIBRATION, 1530.), (FRESH_HOLDOUT, None)]:
        data = experiment.prepare(directory, meeting, end=end)
        inference = experiment.local_features(data, experiment.infer(data, 1.05))
        grouped = regroup(inference, data['duration'], group_config['policy'])
        features = group_identity_features(inference, grouped)
        names = joint_assignments(data, features, joint_config['policy'])
        prepared.append((data, inference, features, names))
    trials = []
    for threshold in protocol['windowThresholds']:
        for margin in protocol['backgroundMargins']:
            policy = {**joint_config['policy'], 'identityMode': 'background', 'windowThreshold': threshold, 'backgroundMargin': margin}
            metrics = []
            for data, inference, features, names in prepared:
                hypothesis = background_identity(data, inference, features, names, policy)
                metric = identity_metrics(data['reference'], hypothesis, data['duration'], data['known'])
                metrics.append({'meeting': data['meeting'], 'known': metric['known']['accuracy'], 'unknown': metric['unknown']['accuracy'],
                                'falseNamingRate': metric['unknown']['falselyNamedSeconds'] / metric['unknown']['speechSeconds']})
            trials.append({'policy': policy, 'metrics': metrics, 'feasible': all(m['falseNamingRate'] <= .05 and m['known'] >= .8 for m in metrics)})
    eligible = [t for t in trials if t['feasible']]
    if eligible:
        winner = max(eligible, key=lambda t: (min(m['known'] for m in t['metrics']), np.mean([m['unknown'] for m in t['metrics']])))
    else:
        retained = [t for t in trials if all(m['known'] >= .8 for m in t['metrics'])]
        winner = min(retained or trials, key=lambda t: (max(m['falseNamingRate'] for m in t['metrics']), -min(m['known'] for m in t['metrics'])))
    write_json(experiment.output / 'background-calibration.json', trials)
    write_json(path, {'policy': winner['policy'], 'calibrationMetrics': winner, 'protocol': protocol})
    print('BACKGROUND FROZEN', json.dumps(winner), flush=True)


def calibrate_automatic(experiment, directory):
    destination = experiment.output / 'frozen-automatic-config.json'
    if destination.exists():
        raise SystemExit('Automatic policy is frozen; do not retune using validation.')
    grouping = json.loads((experiment.output / 'frozen-regroup-config.json').read_text())['policy']
    protocol = {'developmentRecordings': [CALIBRATION, FRESH_HOLDOUT], 'freshHoldouts': AUTOMATIC_HOLDOUT,
                'models': experiment.model_hashes, 'runtime': sherpa_onnx.__version__,
                'identityGrid': [.4, .45, .5, .55, .6, .65, .7], 'marginGrid': [0., .05, .1, .15],
                'selection': 'Require <=5% unknown false naming and >=80% known correctness on each development recording; maximize minimum known correctness, then mean unknown rejection. If infeasible, minimize worst false naming among policies retaining >=80% known correctness.',
                'uniqueIdentityOptions': [False, True], 'grouping': grouping}
    write_json(experiment.output / 'automatic-protocol.json', protocol)
    prepared = []
    for meeting, end in [(CALIBRATION, 1530.), (FRESH_HOLDOUT, None)]:
        data = experiment.prepare(directory, meeting, end=end)
        inference = experiment.local_features(data, experiment.infer(data, 1.05))
        grouped = regroup(inference, data['duration'], grouping)
        prepared.append((data, grouped, group_identity_features(inference, grouped)))
    trials = []
    for threshold in protocol['identityGrid']:
        for margin in protocol['marginGrid']:
            for unique in protocol['uniqueIdentityOptions']:
                policy = {'identityThreshold': threshold, 'minimumMargin': margin, 'uniqueIdentity': unique}
                metrics = []
                for data, grouped, features in prepared:
                    names = joint_assignments(data, features, policy)
                    metric = identity_metrics(data['reference'], named_groups(grouped, names), data['duration'], data['known'])
                    metrics.append({'meeting': data['meeting'], 'known': metric['known']['accuracy'],
                                    'unknown': metric['unknown']['accuracy'],
                                    'falseNamingRate': metric['unknown']['falselyNamedSeconds'] / metric['unknown']['speechSeconds']})
                feasible = all(m['falseNamingRate'] <= .05 and m['known'] >= .8 for m in metrics)
                trials.append({'policy': policy, 'metrics': metrics, 'feasible': feasible})
    eligible = [t for t in trials if t['feasible']]
    if eligible:
        winner = max(eligible, key=lambda t: (min(m['known'] for m in t['metrics']), np.mean([m['unknown'] for m in t['metrics']])))
    else:
        retained = [t for t in trials if all(m['known'] >= .8 for m in t['metrics'])]
        winner = min(retained or trials, key=lambda t: (max(m['falseNamingRate'] for m in t['metrics']), -min(m['known'] for m in t['metrics'])))
    write_json(experiment.output / 'automatic-calibration.json', trials)
    write_json(destination, {'policy': winner['policy'], 'calibrationMetrics': winner, 'protocol': protocol})
    print('AUTOMATIC FROZEN', json.dumps(winner), flush=True)


def evaluate_automatic(experiment, directory, meeting, config_path):
    frozen = json.loads(config_path.read_text())
    if frozen['protocol']['models'] != experiment.model_hashes or frozen['protocol']['runtime'] != sherpa_onnx.__version__:
        raise ValueError('Models/runtime differ from calibration')
    if meeting in frozen['protocol']['developmentRecordings']:
        raise ValueError('Development recordings cannot be used as validation')
    data = experiment.prepare(directory, meeting)
    inference = experiment.local_features(data, experiment.infer(data, 1.05))
    grouped = regroup(inference, data['duration'], frozen['protocol']['grouping'])
    features = group_identity_features(inference, grouped)
    names = joint_assignments(data, features, frozen['policy'])
    hypothesis = (background_identity(data, inference, features, names, frozen['policy'])
                  if frozen['policy'].get('identityMode') == 'background' else named_groups(grouped, names))
    previous_path = experiment.output / 'frozen-local-config.json'
    if not previous_path.exists():
        previous_path = experiment.output.parent / 'frozen-local-config.json'
    previous_config = json.loads(previous_path.read_text())
    previous = previous_config['policy']
    previous_identity = (identity_metrics(data['reference'], window_assignments(data, inference, previous), data['duration'], data['known'])
                         if previous_config['protocol']['models'] == experiment.model_hashes else None)
    result = {'meeting': meeting, 'durationSeconds': data['duration'], 'actualSpeakers': len({r['speaker'] for r in data['reference']}),
              'registeredSpeakers': data['known'], 'enrollment': data['enrollment'],
              'previousIdentity': previous_identity,
              'identity': identity_metrics(data['reference'], hypothesis, data['duration'], data['known']),
              'diarization': diarization_metrics(data['reference'], grouped, data['duration']),
              'groupAssignments': names, 'policy': frozen['policy'], 'audioHash': data['audioHash'],
              'frozenConfigHash': sha256(config_path)}
    variant = 'background' if frozen['policy'].get('identityMode') == 'background' else 'automatic'
    write_json(experiment.output / f'{meeting}-{variant}.json', result)
    write_json(experiment.output / f'{meeting}-{variant}-segments.json', hypothesis)
    print('RESULT', json.dumps({k:result[k] for k in ['meeting','actualSpeakers','previousIdentity','identity']}), flush=True)


def calibrate(experiment, directory):
    config_path = experiment.output / 'frozen-config.json'
    if config_path.exists():
        raise SystemExit('Configuration is already frozen; do not retune after evaluation.')
    protocol = {'calibrationRecording': CALIBRATION, 'calibrationInterval': [TEST_START, 1530.],
                'freshHoldout': FRESH_HOLDOUT, 'regressionRecordings': REGRESSION,
                'clusterGrid': CLUSTER_GRID, 'identityGrid': IDENTITY_GRID, 'marginGrid': MARGIN_GRID,
                'selection': 'Minimum calibration DER, then maximum mean of known/unknown time accuracy; tie favors unknown rejection.',
                'models': experiment.model_hashes, 'runtime': sherpa_onnx.__version__}
    write_json(experiment.output / 'protocol.json', protocol)
    data = experiment.prepare(directory, CALIBRATION, end=1530.)
    cluster_trials = []
    candidates = {}
    for threshold in CLUSTER_GRID:
        inference = experiment.infer(data, threshold)
        metrics = diarization_metrics(data['reference'], inference['segments'], data['duration'])
        trial = {'threshold': threshold, 'DER': metrics['allSpeech']['DER'],
                 'detectedSpeakers': len({r['speaker'] for r in inference['segments']})}
        cluster_trials.append(trial)
        candidates[threshold] = inference
        write_json(experiment.output / 'calibration-clustering.json', cluster_trials)
        print('CLUSTER', json.dumps(trial), flush=True)
    winner = min(cluster_trials, key=lambda row: row['DER'])
    inference = candidates[winner['threshold']]
    matches = []
    for threshold in IDENTITY_GRID:
        for margin in MARGIN_GRID:
            policy = {'clusteringThreshold': winner['threshold'], 'identityThreshold': threshold,
                      'minimumMargin': margin, 'minimumSupport': .6, 'minimumWindowSeconds': 1.5,
                      'minimumEvidenceSeconds': 3.}
            metrics = score(data, inference, policy)['identity']
            known, unknown = metrics['known']['accuracy'], metrics['unknown']['accuracy']
            if known is None or unknown is None:
                raise ValueError('Calibration requires both registered and unregistered speech')
            matches.append({'policy': policy, 'knownAccuracy': known, 'unknownRejection': unknown,
                            'balancedAccuracy': (known + unknown) / 2})
    choice = max(matches, key=lambda row: (row['balancedAccuracy'], row['unknownRejection']))
    write_json(experiment.output / 'calibration-identity.json', matches)
    config = {'policy': choice['policy'], 'calibrationMetrics': choice, 'protocol': protocol,
              'calibrationAudioHash': data['audioHash'], 'enrollment': data['enrollment']}
    write_json(config_path, config)
    print('FROZEN', json.dumps(choice), flush=True)


def calibrate_windows(experiment, directory, local=False):
    mode = 'local' if local else 'window'
    path = experiment.output / f'frozen-{mode}-config.json'
    if path.exists():
        raise SystemExit('Window policy is already frozen; do not retune on held-out results.')
    old = json.loads((experiment.output / 'frozen-config.json').read_text())
    # The former holdout exposed centroid contamination and is now development
    # data. The new room-R004 recording remains untouched until this is frozen.
    prepared = []
    for meeting, end in [(CALIBRATION, 1530.), (FRESH_HOLDOUT, None)]:
        data = experiment.prepare(directory, meeting, end=end)
        inference = experiment.infer(data, old['policy']['clusteringThreshold'])
        if local:
            inference = experiment.local_features(data, inference)
        prepared.append((data, inference))
    protocol = {'calibrationRecording': CALIBRATION, 'developmentRecordings': [CALIBRATION, FRESH_HOLDOUT],
                'freshHoldout': FINAL_HOLDOUT, 'models': experiment.model_hashes, 'runtime': sherpa_onnx.__version__,
                'selection': 'Require <=5% falsely named unknown speech and >=80% known correctness in each development recording; among feasible policies maximize mean known correctness. Otherwise report the failed criterion and select minimum worst false-naming rate among policies retaining >=80% known correctness.',
                'identityGrid': [.4, .45, .5, .55, .6, .65, .7], 'marginGrid': [0., .05, .1, .15, .2]}
    write_json(experiment.output / f'{mode}-protocol.json', protocol)
    trials = []
    for threshold in protocol['identityGrid']:
        for margin in protocol['marginGrid']:
            policy = {**old['policy'], 'identityMode': mode, 'identityThreshold': threshold, 'minimumMargin': margin}
            metrics = []
            for data, inference in prepared:
                hypothesis = window_assignments(data, inference, policy)
                metric = identity_metrics(data['reference'], hypothesis, data['duration'], data['known'])
                metrics.append({'meeting': data['meeting'], 'known': metric['known']['accuracy'],
                                'unknown': metric['unknown']['accuracy'],
                                'falseNamingRate': metric['unknown']['falselyNamedSeconds'] / metric['unknown']['speechSeconds']})
            feasible = all(m['falseNamingRate'] <= .05 and m['known'] >= .8 for m in metrics)
            trials.append({'policy': policy, 'metrics': metrics, 'feasible': feasible})
    eligible = [t for t in trials if t['feasible']]
    if eligible:
        winner = max(eligible, key=lambda t: (np.mean([m['known'] for m in t['metrics']]), -max(m['falseNamingRate'] for m in t['metrics'])))
    else:
        retained = [t for t in trials if all(m['known'] >= .8 for m in t['metrics'])]
        winner = min(retained or trials, key=lambda t: (max(m['falseNamingRate'] for m in t['metrics']), -np.mean([m['known'] for m in t['metrics']])))
    write_json(experiment.output / f'{mode}-calibration.json', trials)
    write_json(path, {'policy': winner['policy'], 'calibrationMetrics': winner, 'protocol': protocol})
    print('WINDOW FROZEN', json.dumps(winner), flush=True)


def evaluate(experiment, directory, meeting, baseline, config_path):
    frozen = json.loads(config_path.read_text())
    if frozen['protocol']['models'] != experiment.model_hashes or frozen['protocol']['runtime'] != sherpa_onnx.__version__:
        raise ValueError('Models/runtime differ from the calibrated configuration')
    if meeting == frozen['protocol']['calibrationRecording']:
        raise ValueError('Calibration recording cannot be used as validation')
    data = experiment.prepare(directory, meeting)
    if baseline:
        policy = {'clusteringThreshold': .5, 'identityThreshold': BASELINE_IDENTITY_THRESHOLD}
    else:
        policy = frozen['policy']
    inference = experiment.infer(data, policy['clusteringThreshold'])
    if policy.get('identityMode') == 'local':
        inference = experiment.local_features(data, inference)
    result = score(data, inference, policy, legacy=baseline)
    result.update(policy=policy, enrollment=data['enrollment'], sourceLabelMap=data['sourceLabelMap'],
                  audioHash=data['audioHash'], frozenConfigHash=sha256(config_path),
                  peakProcessRSSMiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024**2)
    variant = 'baseline' if baseline else (f'{policy["identityMode"]}-corrected' if policy.get('identityMode') else 'corrected')
    write_json(experiment.output / f'{meeting}-{variant}.json', result)
    print('RESULT', json.dumps({k: v for k, v in result.items() if k in ['meeting', 'actualSpeakers', 'detectedSpeakers', 'diarization', 'identity', 'performance']}), flush=True)


def self_check():
    ref = [{'start': 0., 'end': 1., 'speaker': 'a'}, {'start': 1., 'end': 2., 'speaker': 'b'}]
    hyp = [{'start': 0., 'end': 1., 'speaker': 'y'}, {'start': 1., 'end': 2., 'speaker': 'x'}]
    assert diarization_metrics(ref, hyp, 3.)['allSpeech']['DER'] == 0
    assert diarization_metrics(ref, [], 3.)['allSpeech']['DER'] == 1
    data = {'profiles': np.eye(2), 'known': ['a', 'b']}
    policy = {'identityThreshold': .5, 'minimumMargin': .1, 'minimumSupport': .6,
              'minimumWindowSeconds': 1.5, 'minimumEvidenceSeconds': 3.}
    assert assignments(data, {'x': [{'embedding': [1., 0.], 'seconds': 5.}]}, policy)['x']['prediction'] == 'a'
    assert assignments(data, {'x': [{'embedding': [1., 0.], 'seconds': .6}]}, policy)['x']['prediction'] == 'unknown'
    assert assignments(data, {'x': [{'embedding': [.71, .70], 'seconds': 5.}]}, policy)['x']['prediction'] == 'unknown'
    # Opposing local evidence must not produce a name from an averaged centroid.
    assert assignments(data, {'x': [{'embedding': [1., 0.], 'seconds': 5.}, {'embedding': [0., 1.], 'seconds': 5.}]}, policy)['x']['prediction'] == 'unknown'
    # Majority registered speech must not lend its name to a weak local window.
    mixed = {'segments': [{'start': 0., 'end': 20., 'speaker': 'x'}],
             'features': {'x': [{'embedding': [1., 0.], 'seconds': 10.}, {'embedding': [.4, .39], 'seconds': 10.}]}}
    windows = window_assignments({**data, 'duration': 20.}, mixed, policy)
    assert [w['speaker'] for w in windows] == ['a', 'unknown']
    local = {**mixed, 'localWindows': [{'start': 0., 'end': 1., 'contextSeconds': 3., 'embedding': [1., 0.]},
                                     {'start': 1., 'end': 2., 'contextSeconds': 3., 'embedding': [.4, .39]}]}
    assert [w['speaker'] for w in window_assignments({**data, 'duration': 20.}, local, policy)] == ['a', 'unknown']
    # Recover three separated voices without supplying their number.
    vectors = np.repeat(np.eye(3), 20, axis=0)
    for grouping in [{'method': 'average', 'distance': .45},
                     {'method': 'spectral', 'neighborsFraction': .06, 'maximumSpeakers': 15}]:
        grouped = cluster_windows(vectors, grouping)
        assert len(set(grouped)) == 3
        assert all(len(set(grouped[i:i + 20])) == 1 for i in (0, 20, 40))
    # Simultaneous speakers must remain two tracks even if grouping is uncertain.
    overlap = {'segments': [{'start': 0., 'end': 3., 'speaker': 'x'},
                            {'start': 2., 'end': 4., 'speaker': 'y'}],
               'localWindows': [{'start': 0., 'end': 2., 'contextSeconds': 2., 'embedding': [1., 0.]},
                                {'start': 3., 'end': 4., 'contextSeconds': 1., 'embedding': [1., 0.]}]}
    regrouped = regroup(overlap, 4., {'method': 'average', 'distance': .45})
    assert len({r['speaker'] for r in regrouped if r['start'] <= 2.5 < r['end']}) == 2
    # A lower-scoring impostor group cannot also claim an already matched name.
    features = {'group_a': [{'embedding': [1., 0.], 'seconds': 5.}],
                'group_b': [{'embedding': [.8, .6], 'seconds': 5.}],
                'group_c': [{'embedding': [0., 1.], 'seconds': 5.}]}
    joint = joint_assignments(data, features, {'identityThreshold': .5, 'minimumMargin': .1, 'uniqueIdentity': True})
    assert [joint[k]['prediction'] for k in features] == ['a', 'unknown', 'b']
    # An unmatched group is evidence for unknown speech, even inside a group
    # containing known speech; the anonymous cluster is not a blanket name.
    cohort_data = {'profiles': np.eye(3)[:2], 'known': ['a', 'b'], 'duration': 3.}
    cohort_features = {f'group_{i}': [{'embedding': vector, 'seconds': 5.}]
                       for i, vector in enumerate(np.eye(3).tolist())}
    cohort_policy = {'identityThreshold': .5, 'minimumMargin': .1, 'uniqueIdentity': True,
                     'windowThreshold': .4, 'backgroundMargin': .1}
    cohort_names = joint_assignments(cohort_data, cohort_features, cohort_policy)
    cohort_inference = {'segments': [{'start': 0., 'end': 3., 'speaker': 'mixed'}],
                        'localWindows': [{'start': float(i), 'end': float(i + 1), 'contextSeconds': 3., 'embedding': vector}
                                         for i, vector in enumerate([[1., 0., 0.], [.1, .1, .99], [.707, 0., .707]])]}
    assert [r['speaker'] for r in background_identity(cohort_data, cohort_inference, cohort_features, cohort_names, cohort_policy)] == ['a', 'unknown', 'unknown']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['calibrate', 'calibrate-windows', 'calibrate-local', 'calibrate-groups', 'calibrate-automatic', 'calibrate-background', 'evaluate-automatic', 'evaluate-groups', 'evaluate', 'self-check'])
    parser.add_argument('--data', type=Path, default=DEFAULT_DATA / 'correction')
    parser.add_argument('--output', type=Path, default=DEFAULT_DATA / 'correction')
    parser.add_argument('--meeting', choices=[FRESH_HOLDOUT, FINAL_HOLDOUT, REGROUP_HOLDOUT, *AUTOMATIC_HOLDOUT, *REGRESSION])
    parser.add_argument('--config', type=Path)
    parser.add_argument('--identity-model', type=Path)
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    if args.command == 'self-check':
        self_check()
        print('Scoring and identity-policy checks passed.')
        return
    if args.command in ('evaluate', 'evaluate-groups', 'evaluate-automatic') and not args.meeting:
        parser.error('--meeting is required for evaluation')
    if args.identity_model and args.baseline:
        parser.error('Baseline must use the original identity model')
    experiment = Experiment(args.output, args.identity_model)
    if args.command == 'calibrate':
        calibrate(experiment, args.data)
    elif args.command in ('calibrate-windows', 'calibrate-local'):
        calibrate_windows(experiment, args.data, local=args.command == 'calibrate-local')
    elif args.command == 'calibrate-groups':
        calibrate_groups(experiment, args.data)
    elif args.command == 'evaluate-groups':
        evaluate_groups(experiment, args.data, args.meeting, args.config or args.output / 'frozen-regroup-config.json')
    elif args.command == 'calibrate-automatic':
        calibrate_automatic(experiment, args.data)
    elif args.command == 'calibrate-background':
        calibrate_background(experiment, args.data)
    elif args.command == 'evaluate-automatic':
        evaluate_automatic(experiment, args.data, args.meeting, args.config or args.output / 'frozen-automatic-config.json')
    else:
        evaluate(experiment, args.data, args.meeting, args.baseline, args.config or args.output / 'frozen-config.json')


if __name__ == '__main__':
    main()
